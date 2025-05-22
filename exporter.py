#!/usr/bin/env python3

import logging
import sys
import os
import time
import subprocess
import signal
import argparse
import redis
from decouple import Config, RepositoryEnv, RepositoryEmpty
from datetime import datetime, timedelta
from prometheus_client import start_http_server, CollectorRegistry, Gauge, write_to_textfile
from dataclasses import dataclass, asdict


class MyLogger:
    """Custom logger that outputs INFO messages to stdout and ERROR messages to stderr."""

    def __init__(self, name: str, level=logging.INFO):
        """
        Initialize the logger.

        Args:
            name (str): Name of the logger.
            level (int): Logging level (default is logging.INFO).
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        if not self.logger.hasHandlers():
            formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s')
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(logging.INFO)
            stdout_handler.setFormatter(formatter)
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.ERROR)
            stderr_handler.setFormatter(formatter)
            self.logger.addHandler(stdout_handler)
            self.logger.addHandler(stderr_handler)


class ReConfig(Config):
    """Extended Config class to support environment variable discovery by prefix."""

    def find(self, regex):
        """
        Find environment variables starting with a specific prefix.

        Args:
            regex (str): Prefix to filter environment variables.

        Returns:
            dict: Filtered environment variables.
        """
        return {k: v for k, v in os.environ.items() if k.startswith(regex)}


class Decouwrapper:
    """Wrapper for Decouple's Config to support dynamic discovery and loading."""

    def __init__(self, envfile: str = None):
        """
        Initialize the wrapper with an optional .env file.

        Args:
            envfile (str): Path to the .env file.
        """
        repository = RepositoryEnv(envfile) if envfile else RepositoryEmpty()
        self.__config = ReConfig(repository)

    def discovery(self, regex):
        """
        Discover environment variables with a given prefix, returning them in lowercase without prefix.

        Args:
            regex (str): Prefix string to search.

        Returns:
            dict: Discovered key-value pairs with prefix removed.
        """
        discovered = self.__config.find(regex)
        prefix_len = len(regex)
        return {key[prefix_len:].lower(): value for key, value in discovered.items()}

    def get(self, key, default=None):
        """
        Get a configuration value.

        Args:
            key (str): Configuration key.
            default: Default value if the key is not found.

        Returns:
            str or default: Retrieved value or default.
        """
        return self.__config.get(key, default)


@dataclass
class ExporterConfig:
    """Dataclass for holding configuration options for the exporter."""

    scrape_interval: int
    http_port: int
    addr: str
    metrics_file: str
    ops_mode: str
    awg_executable: str
    redis_host: str
    redis_port: int
    redis_db: int
    extra_labels: dict


class PersistenceWrapper:
    """Handles Redis-based persistence for tracking peer activity over time."""

    FIVE_MINUTES = timedelta(minutes=5)
    ONE_DAY = timedelta(days=1)
    ONE_MONTH = timedelta(days=30)

    def __init__(self, host: str, port: int, db: int):
        """
        Initialize Redis connection and set up metrics counters.

        Args:
            host (str): Redis host.
            port (int): Redis port.
            db (int): Redis database number.
        """
        self.log = MyLogger(self.__class__.__name__).logger
        self.connection = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        try:
            self.connection.ping()
        except redis.ConnectionError:
            self.log.error("Redis connection failed.")
            raise
        self.dau = self.mau = self.mau_abs = self.online = 0
        self.current_month = ''

    def update_peer(self, peer: str, handshake_time: int):
        """
        Update a peer's last handshake time in Redis.

        Args:
            peer (str): Peer identifier.
            handshake_time (int): Timestamp of the latest handshake.
        """
        try:
            self.connection.set(peer, handshake_time)
        except redis.RedisError as e:
            self.log.error(f"Error updating peer {peer}: {e}")

    def recalculate(self):
        """
        Recalculate activity metrics (DAU, MAU, online peers) based on stored timestamps.
        """
        now = datetime.now()
        five_minutes_ago = (now - self.FIVE_MINUTES).timestamp()
        day_ago = (now - self.ONE_DAY).timestamp()
        month_ago = (now - self.ONE_MONTH).timestamp()
        first_day_of_month = datetime(now.year, now.month, 1).timestamp()
        counts = dict(mau_abs=0, mau=0, dau=0, online=0)
        try:
            for peer in self.connection.keys():
                ts = self.connection.get(peer)
                if ts:
                    ts = float(ts)
                    if ts >= first_day_of_month: counts['mau_abs'] += 1
                    if ts >= month_ago: counts['mau'] += 1
                    if ts >= day_ago: counts['dau'] += 1
                    if ts >= five_minutes_ago: counts['online'] += 1
            self.mau_abs, self.mau, self.dau, self.online = counts.values()
            self.current_month = f"{now:%Y-%m}"
        except redis.RedisError as e:
            self.log.error(f"Error during recalculation: {e}")


    def __getitem__(self, key):
        """
        Allow dictionary-style access to internal metric attributes.
        
        Args:
            key (str): One of 'dau', 'mau', 'mau_abs', 'online'.

        Returns:
            int: Corresponding metric value.
        """
        if key in ['dau', 'mau', 'mau_abs', 'online']:
            return getattr(self, key)
        raise KeyError(f"Invalid key: {key}")


class AwgShowWrapper:
    """Handles execution and parsing of the AWG binary output."""

    @staticmethod
    def parse(text_block: str) -> list:
        """
        Parse AWG output text to extract peer info.

        Args:
            text_block (str): Output from AWG binary.

        Returns:
            list: List of peers with handshake info.
        """
        lines = text_block.strip().splitlines()[1:]  # Skip header
        peers = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                peers.append({'peer': parts[4], 'latest_handshake': parts[5]})
        return peers

    @staticmethod
    def run_bin(command: list) -> str:
        """
        Execute a shell command and return the output.

        Args:
            command (list): Command to run as a list.

        Returns:
            str: Standard output from the command.
        """
        log = MyLogger('AwgShowWrapper').logger
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            log.error(f"Subprocess failed: {e.stderr.strip()}")
        except FileNotFoundError:
            log.error("AWG binary not found.")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
        return ''


class Exporter:
    """Prometheus exporter that collects and exposes metrics based on AWG output."""

    def __init__(self, config: ExporterConfig):
        """
        Initialize the exporter with configuration and setup metrics.

        Args:
            config (ExporterConfig): Exporter configuration object.
        """
        self.config = config
        self.log = MyLogger(self.__class__.__name__).logger
        self.registry = CollectorRegistry()
        self.storage = PersistenceWrapper(config.redis_host, config.redis_port, config.redis_db)
        self.awg_show_command = config.awg_executable.split()
        labels = list(config.extra_labels.keys())
        self.has_labels = True if len(labels) > 0 else False
        self.metrics = {
            'online': Gauge('awg_current_online', 'Online users', labels, registry=self.registry),
            'dau': Gauge('awg_dau', 'Daily Active Users', labels, registry=self.registry),
            'mau': Gauge('awg_mau', 'Monthly Active Users', labels, registry=self.registry),
            'mau_abs': Gauge('awg_mau_abs', 'Absolute Monthly Active Users', ['month'] + labels, registry=self.registry),
            'status': Gauge('awg_status', 'Exporter status', labels, registry=self.registry)
        }
        self.log.info("Exporter initialized")

    def set_metric(self, name):
        if name != 'status':
            value = self.storage[name]
        else:
            value = 1
        if self.has_labels:
            if name == 'mau_abs':
                self.metrics[name].labels(month=self.storage.current_month, **self.config.extra_labels).set(value)
            else:
                self.metrics[name].labels(**self.config.extra_labels).set(value)
        else:
            if name == 'mau_abs':
                self.metrics[name].labels(month=self.storage.current_month).set(value)
            else:
                self.metrics[name].set(value)

    def update_metrics(self):
        """
        Fetch the latest peer data, update Redis, and export metrics.
        """
        output = AwgShowWrapper.run_bin(self.awg_show_command)
        peers = AwgShowWrapper.parse(output)
        if not peers:
            self.metrics['status'].labels(**self.config.extra_labels).set(0)
            self.metrics['online'].labels(**self.config.extra_labels).set(0)
            return
        for peer in peers:
            if peer.get('latest_handshake') != '0':
                self.storage.update_peer(peer['peer'], peer['latest_handshake'])
        self.storage.recalculate()
        for metric in self.metrics.keys():
            self.set_metric(metric)

    def run(self):
        """
        Start the exporter based on the configured operational mode.
        Supports 'http', 'metricsfile', and 'oneshot'.
        """
        self.log.info("Exporter running")
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        if self.config.ops_mode == 'http':
            start_http_server(self.config.http_port, addr=self.config.addr, registry=self.registry)
        while True:
            self.update_metrics()
            if self.config.ops_mode in ['metricsfile', 'oneshot']:
                write_to_textfile(self.config.metrics_file, self.registry)
            if self.config.ops_mode == 'oneshot':
                break
            time.sleep(self.config.scrape_interval)


def main():
    """
    Entry point for the exporter script. Parses arguments, loads config,
    initializes and runs the exporter.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--envfile', type=str, help='Path to env file')
    args = parser.parse_args()
    raw = Decouwrapper(args.envfile)
    config = ExporterConfig(
        scrape_interval=int(raw.get('AWG_EXPORTER_SCRAPE_INTERVAL', 60)),
        http_port=int(raw.get('AWG_EXPORTER_HTTP_PORT', 9351)),
        addr=raw.get('AWG_EXPORTER_LISTEN_ADDR', '0.0.0.0'),
        metrics_file=raw.get('AWG_EXPORTER_METRICS_FILE', '/tmp/prometheus/awg.prom'),
        ops_mode=raw.get('AWG_EXPORTER_OPS_MODE', 'http'),
        awg_executable=raw.get('AWG_EXPORTER_AWG_SHOW_EXEC', 'awg show all dump'),
        redis_host=raw.get('AWG_EXPORTER_REDIS_HOST', 'localhost'),
        redis_port=int(raw.get('AWG_EXPORTER_REDIS_PORT', 6379)),
        redis_db=int(raw.get('AWG_EXPORTER_REDIS_DB', 0)),
        extra_labels=raw.discovery('AWG_EXPORTER_EXTRA_LABEL_')
    )

    logger = MyLogger("Main").logger
    logger.info("Starting Exporter")
    logger.info('Exporter config:')
    for key, value in asdict(config).items():
        if key == 'metrics_file' and config.ops_mode != 'metricsfile':
            continue
        logger.info(f"--> {key}: {value}")
    exporter = Exporter(config)
    exporter.run()


if __name__ == '__main__':
    main()

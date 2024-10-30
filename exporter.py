#!/usr/bin/env python3

import logging
import sys
import time
import subprocess
import signal
import argparse
import redis
from decouple import Config, RepositoryEnv, RepositoryEmpty
from datetime import datetime, timedelta
from prometheus_client import start_http_server, CollectorRegistry, Gauge, write_to_textfile, generate_latest
from prometheus_client.parser import text_string_to_metric_families
import requests


class MyLogger:
    """
    A simple wrapper around Python's logging module to set up loggers with stdout and stderr handlers.

    Parameters:
        name (str): The name of the logger.
        level (int): The logging level (default is logging.INFO).
    """
    def __init__(self, name: str, level=logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s')
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.INFO)
        stdout_handler.setFormatter(formatter)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(formatter)
        self.logger.addHandler(stdout_handler)
        self.logger.addHandler(stderr_handler)


class Decouwrapper:
    """
    A wrapper class providing access to configuration options.

    This class reads configuration options from a file specified by the `--envfile` argument
    or uses an empty repository if the argument is not provided.

    Attributes:
        __config (dict): A dictionary storing the configuration options.
    """
    def __init__(self):
        self.__config = {}
        self.__read_config()

    def __read_config(self):
        """
        Reads configuration options from the file specified by the `--envfile` argument.

        If the `--envfile` argument is not provided, configuration options are fetched from the system environment.
        """
        parser = argparse.ArgumentParser(description='AWG exporter options')
        parser.add_argument('--envfile', type=str, help='Path to config.env file')
        if parser.parse_args().envfile is None:
            repository = RepositoryEmpty()
        else:
            repository = RepositoryEnv(parser.parse_args().envfile)
        self.__config = Config(repository)

    def __call__(self, *args, **kwargs):
        """
        Provides access to configuration options via the Config object.

        Args:
            *args: Variable length argument list for configuration key.
            **kwargs: Arbitrary keyword arguments for default values.

        Returns:
            str: The configuration value for the given key.
        """
        return self.__config.get(*args, **kwargs)


class PersistenceWrapper:
    """
    A wrapper for interacting with Redis to maintain active user statistics.

    Attributes:
        connection (redis.Redis): The Redis connection object.
        mau (int): Monthly active users, calculated based on recent activity.
        dau (int): Daily active users, calculated based on recent activity.
        online (int): Users currently online (last 5 minutes).
    """

    FIVE_MINUTES = timedelta(minutes=5)
    ONE_DAY = timedelta(days=1)
    ONE_MONTH = timedelta(days=30)

    def __init__(self, host: str, port: int, db: int):
        """
        Initializes the Redis connection and user activity counters.

        Args:
            host (str): Redis server hostname. Defaults to 'localhost'.
            port (int): Redis server port. Defaults to 6379.
            db (int): Redis database number. Defaults to 0.
        """
        self.log = MyLogger(self.__class__.__name__).logger
        self.connection = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.log.info('Redis storage initialized')
        self.dau: int = 0
        self.mau: int = 0
        self.mau_abs: int = 0
        self.online: int = 0
        self.current_month: str = ''

    def update_peer(self, peer: str, handshake_time: int) -> None:
        """
        Updates the last handshake time for a specific peer in Redis.

        Args:
            peer (str): Unique identifier for the peer.
            handshake_time (int): Timestamp of the handshake event.
        """
        try:
            self.connection.set(peer, handshake_time)
        except redis.RedisError as e:
            self.log.error(f"Error updating peer {peer}: {e}")

    def recalculate(self) -> None:
        """
        Recalculates the MAU, DAU, and online user counts by iterating over all peer entries
        in Redis and comparing their handshake times to current time thresholds.

        MAU (Monthly Active Users): Users active within the last 30 days.
        DAU (Daily Active Users): Users active within the last 24 hours.
        Online: Users active within the last 5 minutes.
        """
        try:
            now = datetime.now()
            five_minutes_ago = (now - self.FIVE_MINUTES).timestamp()
            day_ago = (now - self.ONE_DAY).timestamp()
            month_ago = (now - self.ONE_MONTH).timestamp()
            first_day_of_month = datetime(now.year, now.month, 1).timestamp()
            mau_abs_count = 0
            mau_count = 0
            dau_count = 0
            online_count = 0
            for peer in self.connection.keys():
                handshake_time = self.connection.get(peer)
                if handshake_time:
                    handshake_time = float(handshake_time)
                    if handshake_time >= first_day_of_month:
                        mau_abs_count += 1
                    if handshake_time >= month_ago:
                        mau_count += 1
                    if handshake_time >= day_ago:
                        dau_count += 1
                    if handshake_time >= five_minutes_ago:
                        online_count += 1
            self.mau_abs = mau_abs_count
            self.mau = mau_count
            self.dau = dau_count
            self.online = online_count
            self.current_month = f"{now.strftime('%Y')}-{now.strftime('%m')}"
        except redis.RedisError as e:
            self.log.error(f"Error recalculating active users: {e}")


class AwgShowWrapper:
    """
    A wrapper class providing utility methods for parsing output from the 'awg show' command.

    This class includes static methods for parsing text blocks into structured data and running 'awg show' commands.

    Attributes:
        None
    """

    @staticmethod
    def parse(text_block: str) -> list:
        """
        Parse a text block containing information about AmneziaWG peers into a list of dictionaries.

        Args:
            text_block (str): The text block to parse.
        """
        lines = text_block.strip().splitlines()
        peers = []
        for line in lines[1:]:  # exclude 1st line with host data
            parts = line.split()
            current_peer = {}
            if len(parts) >= 6:
                current_peer['peer'] = parts[1]
                current_peer['latest_handshake'] = parts[5]
                peers.append(current_peer)

        return peers

    @staticmethod
    def run_bin(command: list) -> str:
        """
        Run an 'awg show' command (or its replacement) and return the output.

        Args:
            command (list): The 'awg show' command to run.

        Returns:
            str: The output of the 'awg show' command.
        """
        log = MyLogger('AwgShowWrapper').logger
        try:
            process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return process.stdout.strip()
        except subprocess.CalledProcessError as e:
            log.error(f"Error: Subprocess failed with exit code {e.returncode} and stderr: {e.stderr.strip()}")
            return ''
        except FileNotFoundError as e:
            log.error(f"{e}")
            log.error('Cannot execute awg binary because of the previous exception. Exporter will not work as expected.')
            return ''
        except Exception as e:
            log.error(f"{e}")
            return ''


class Exporter:
    """
    A class to handle exporting of metrics to Grafana Cloud or local storage based on configuration settings.

    Attributes:
        config (dict): Configuration parameters for the exporter.
        registry (CollectorRegistry): Registry to store Prometheus metrics.
        storage (PersistenceWrapper): Redis storage wrapper to handle peer data persistence.
        log (Logger): Logger for monitoring and debugging.
        current_online_metric (Gauge): Gauge metric for tracking current online users.
        dau_metric (Gauge): Gauge metric for daily active users.
        mau_metric (Gauge): Gauge metric for monthly active users.
        status (Gauge): Gauge metric for exporter status.
    """

    def __init__(self, config: dict) -> None:
        """
        Initializes the Exporter instance with the given configuration.

        Args:
            config (dict): Dictionary containing exporter configuration.
        """
        self.config = config
        self.awg_show_command = self.config['awg_executable'].split(' ')
        self.log = MyLogger(self.__class__.__name__).logger
        self.registry = CollectorRegistry()
        self.storage = PersistenceWrapper(self.config['redis_host'], self.config['redis_port'], self.config['redis_db'])
        self.current_online_metric = Gauge('awg_current_online', 'Current online users', registry=self.registry)
        self.dau_metric = Gauge('awg_dau', 'Daily active users', registry=self.registry)
        self.mau_metric = Gauge('awg_mau', 'Monthly active users', registry=self.registry)
        self.mau_abs_metric = Gauge('awg_mau_abs', 'Monthly active users (Absolute)', ['month'], registry=self.registry)
        self.status = Gauge('awg_status', 'Exporter status. 1 - OK, 0 - not OK', registry=self.registry)
        self.log.info('AmneziaWG exporter initialized')

    def sigterm_handler(self, sig, frame) -> None:
        """
        Handles SIGTERM signal for graceful shutdown.
        """
        self.log.info('SIGTERM received, preparing to shut down...')
        sys.exit(0)

    def sigint_handler(self, sig, frame) -> None:
        """
        Handles SIGINT (Ctrl+C) signal for graceful shutdown.
        """
        self.log.info('SIGINT (Ctrl+C) received, preparing to shut down...')
        sys.exit(0)

    def update_metrics(self) -> None:
        """
        Updates and recalculates metrics for online, daily, and monthly active users.
        """
        try:
            awg_show_result = AwgShowWrapper.run_bin(self.awg_show_command)
            peers = AwgShowWrapper.parse(awg_show_result)
            if not peers:
                self.status.set(0)
                self.current_online_metric.set(0)
                return
            for peer in peers:
                if peer.get('latest_handshake') == "0":
                    continue
                self.storage.update_peer(peer['peer'], peer['latest_handshake'])
            self.storage.recalculate()
            self.dau_metric.set(self.storage.dau)
            self.mau_metric.set(self.storage.mau)
            self.mau_abs_metric.labels(self.storage.current_month).set(self.storage.mau_abs)
            self.current_online_metric.set(self.storage.online)
            self.status.set(1)
        except Exception as e:
            self.log.error(f"Error updating metrics: {e}")

    def send_to_grafana_cloud(self) -> None:
        """
        Sends collected metrics to Grafana Cloud.
        """
        metrics = generate_latest(self.registry)
        for family in text_string_to_metric_families(metrics.decode('utf-8')):
            for sample in family.samples:
                name = sample.name
                labels = sample.labels
                value = sample.value
                labels_string = ','.join([f"{key}={value}" for key, value in labels.items()])
                # Dirty hack: We might need to add some labels (usually Prometheus does this for us).
                if self.config['grafana_additional_labels'] != '':
                    labels_string = f"{labels_string},{self.config['grafana_additional_labels']}"
                response = requests.post(self.config['grafana_write_url'],
                                         headers={"Authorization": f"Bearer {self.config['grafana_write_token']}", "Content-Type": "text/plain"},
                                         data=f"{name},{labels_string} value={value}")
                if response.status_code != 204:
                    self.log.info(f"Failed to send metrics to Grafana Cloud: {response.status_code}, {response.text}")

    def validate(self) -> None:
        """
        Validates the configuration, ensuring required fields are set for Grafana Cloud mode.
        """
        if self.config['ops_mode'] == 'grafana_cloud':
            if self.config['grafana_write_url'] == '':
                self.log.error('AWG_GRAFANA_WRITE_URL variable must be set!')
                sys.exit(1)
            if self.config['grafana_write_token'] == '':
                self.log.error('AWG_GRAFANA_WRITE_TOKEN variable must be set!')
                sys.exit(1)

    def main_loop(self) -> None:
        self.log.info('Starting main loop')
        signal.signal(signal.SIGTERM, self.sigterm_handler)
        signal.signal(signal.SIGINT, self.sigint_handler)
        self.validate()
        if self.config['ops_mode'] == 'http':
            # Start up the server to expose the metrics.
            start_http_server(port=self.config['http_port'], addr=self.config['addr'], registry=self.registry)
        while True:
            try:
                self.update_metrics()
                if self.config['ops_mode'] in ['metricsfile', 'oneshot']:
                    write_to_textfile(self.config['metrics_file'], self.registry)
                if self.config['ops_mode'] == 'oneshot':
                    self.log.info("Exiting after successful metrics fetch...")
                    break
                if self.config['ops_mode'] == 'grafana_cloud':
                    self.send_to_grafana_cloud()
                time.sleep(self.config['scrape_interval'])
            except Exception as e:
                self.log.error(f"{str(e)}")
                time.sleep(self.config['scrape_interval'])


if __name__ == '__main__':
    log = MyLogger("Main").logger
    log.info('Starting AmneziaWG exporter')
    config = Decouwrapper()
    exporter_config = {
        'scrape_interval': config('AWG_EXPORTER_SCRAPE_INTERVAL', default=60),
        'http_port': config('AWG_EXPORTER_HTTP_PORT', default=9351),
        'addr': config('AWG_EXPORTER_LISTEN_ADDR', default='0.0.0.0'),
        'metrics_file': config('AWG_EXPORTER_METRICS_FILE', default='/tmp/prometheus/awg.prom'),
        'ops_mode': config('AWG_EXPORTER_OPS_MODE', default='http'),
        'grafana_write_url': config('AWG_GRAFANA_WRITE_URL', default=''),
        'grafana_write_token': config('AWG_GRAFANA_WRITE_TOKEN', default=''),
        'grafana_additional_labels': config('AWG_GRAFANA_ADDITIONAL_LABELS', default=''),
        'awg_executable': config('AWG_EXPORTER_AWG_SHOW_EXEC', default='awg show all dump'),
        'redis_host': config('AWG_EXPORTER_REDIS_HOST', default='localhost'),
        'redis_port': config('AWG_EXPORTER_REDIS_PORT', default=6379),
        'redis_db': config('AWG_EXPORTER_REDIS_DB', default=0)
    }
    log.info('Exporter config:')
    for key, value in exporter_config.items():
        if key == 'metrics_file' and exporter_config['ops_mode'] != 'metricsfile':
            continue
        log.info(f"--> {key}: {value}")
    exporter = Exporter(exporter_config)
    exporter.main_loop()

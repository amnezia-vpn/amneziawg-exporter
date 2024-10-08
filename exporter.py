#!/usr/bin/env python3

import logging
import sys
import time
import re
import subprocess
import signal
import argparse
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


class AwgShowWrapper:
    """
    A wrapper class providing utility methods for parsing output from the 'awg show' command.

    This class includes static methods for parsing time strings, converting string representations of byte sizes
    to integer byte counts, parsing text blocks into structured data, and running 'awg show' commands.

    Attributes:
        None
    """

    @staticmethod
    def parse_time_string(time_string: str) -> datetime:
        """
        Parse a time string from `awg show` output and return the corresponding datetime.

        Args:
            time_string (str): The time string to parse.

        Returns:
            datetime: The exact date and time calculated from the time string.
        """
        patterns = {
            'days': r'(\d+) days?',
            'hours': r'(\d+) hours?',
            'minutes': r'(\d+) minutes?',
            'seconds': r'(\d+) seconds?'
        }
        components = {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}
        for key, pattern in patterns.items():
            match = re.search(pattern, time_string)
            if match:
                components[key] = int(match.group(1))
        delta = timedelta(days=components['days'],
                          hours=components['hours'],
                          minutes=components['minutes'],
                          seconds=components['seconds'])
        return datetime.now() - delta

    @staticmethod
    def parse(text_block: str) -> list:
        """
        Parse a text block containing information about AmneziaWG peers into a list of dictionaries.

        Args:
            text_block (str): The text block to parse.
            peers (list): A list to store parsed peer data.
        """
        peers = []
        current_peer = {}
        for line in text_block.split('\n'):
            if line.strip():
                key, value = line.split(': ', 1)
                key = key.strip().replace(" ", "_")
                value = value.strip()
                if key == 'latest_handshake':
                    current_peer[key] = AwgShowWrapper.parse_time_string(value)
                if key == 'peer':
                    current_peer[key] = value
            else:
                if current_peer.get('peer'):
                    peers.append(current_peer)
                current_peer = {}
        if current_peer:
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
    A Prometheus exporter for collecting Amnezia WG client connection metrics.

    This class initializes the exporter, updates metrics periodically,
    and optionally exposes them via an HTTP server or writes them to a file.

    Args:
        config (dict): A dictionary containing configuration options.

    Attributes:
        config (dict): A dictionary containing configuration options.
        awg_show_command (list): A list containing the command to run the `awg show` command.
        log (Logger): A logger object for logging messages.
        peers (list): A list to store parsed peer data.
        registry (CollectorRegistry): A registry for registering metrics.
        current_online_metric (Gauge): A Prometheus gauge for the current number of online users.
        dau_metric (Gauge): A Prometheus gauge for daily active users.
        status (Gauge): A Prometheus gauge for the exporter's status.

    Methods:
        sigterm_handler: Handles the SIGTERM signal.
        sigint_handler: Handles the SIGINT signal.
        write_metrics_to_file: Writes metrics to a file.
        update_metrics: Updates metrics based on `awg show` output.
        send_to_grafana_cloud: Sends metrics to Grafana Cloud.
        validate: Validates the configuration before starting the exporter.
        main_loop: Starts the main loop for updating metrics periodically.
    """
    def __init__(self, config: dict) -> None:
        self.config = config
        self.awg_show_command = self.config['awg_executable'].split(' ')
        self.log = MyLogger(self.__class__.__name__).logger
        self.registry = CollectorRegistry()
        self.current_online_metric = Gauge('awg_current_online', 'Current online users', registry=self.registry)
        self.dau_metric = Gauge('awg_dau', 'Daily active users', registry=self.registry)
        self.status = Gauge('awg_status',
                            'Exporter status. 1 - OK, 0 - not OK',
                            registry=self.registry)
        self.log.info('AmneziaWG exporter initialized')

    def sigterm_handler(self, sig, frame):
        """
        Handles the SIGTERM signal to gracefully shut down the exporter.

        Args:
            sig (int): The signal number.
            frame: The current stack frame.
        """
        self.log.info('SIGTERM received, preparing to shut down...')
        sys.exit(0)

    def sigint_handler(self, sig, frame):
        """
        Handles the SIGINT signal (typically Ctrl+C) to gracefully shut down the exporter.

        Args:
            sig (int): The signal number.
            frame: The current stack frame.
        """
        self.log.info('SIGINT (Ctrl+C) received, preparing to shut down...')
        sys.exit(0)

    def write_metrics_to_file(self, metrics_file: str):
        """
        Writes metrics to a specified file.

        Args:
            metrics_file (str): The path to the metrics file.
        """
        write_to_textfile(metrics_file, self.registry)

    def update_metrics(self):
        """
        Updates Prometheus metrics based on `awg show` command output.
        """
        try:
            awg_show_result = AwgShowWrapper.run_bin(self.awg_show_command)
            peers = AwgShowWrapper.parse(awg_show_result)
            if not peers:
                self.status.set(0)
                self.current_online_metric.set(0)
                return
            current_online = 0
            dau = 0
            for peer in peers:
                if peer.get('latest_handshake') is None:
                    continue
                if peer['latest_handshake'].date() == datetime.now().date():
                    dau += 1
                delta_time = datetime.now() - peer['latest_handshake']
                five_minutes = timedelta(minutes=5)
                if delta_time < five_minutes:
                    current_online += 1
            self.dau_metric.set(dau)
            self.current_online_metric.set(current_online)
            self.status.set(1)
        except Exception as e:
            self.log.error(f"Error updating metrics: {e}")

    def send_to_grafana_cloud(self):
        """
        Sends the collected metrics to Grafana Cloud.

        Metrics are sent using a custom format expected by Grafana Cloud.

        Raises:
            RuntimeError: If the request to Grafana Cloud fails.
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

    def validate(self):
        """
        Validates the exporter configuration.

        Ensures that necessary configuration options are set, especially for Grafana Cloud mode.
        """
        if self.config['ops_mode'] == 'grafana_cloud':
            if self.config['grafana_write_url'] == '':
                self.log.error('AWG_GRAFANA_WRITE_URL variable must be set!')
                sys.exit(1)
            if self.config['grafana_write_token'] == '':
                self.log.error('AWG_GRAFANA_WRITE_TOKEN variable must be set!')
                sys.exit(1)

    def main_loop(self):
        """
        Starts the main loop for updating metrics periodically based on the configured operation mode.

        The loop can run indefinitely, or exit after a single update if in 'oneshot' mode.
        """
        self.log.info('Start main loop')
        self.log.info(f"Ops mode: {self.config['ops_mode']}")
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
                    self.write_metrics_to_file(self.config['metrics_file'])
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
        'awg_executable': config('AWG_EXPORTER_AWG_SHOW_EXEC', default='awg show')
    }
    log.info('Exporter config:')
    for key, value in exporter_config.items():
        if key == 'metrics_file' and exporter_config['ops_mode'] != 'metricsfile':
            continue
        log.info(f"--> {key}: {value}")
    exporter = Exporter(exporter_config)
    exporter.main_loop()

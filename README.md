![License](https://img.shields.io/github/license/amnezia-vpn/amneziawg-exporter)
![Docker Latest Version](https://img.shields.io/docker/v/amneziavpn/amneziawg-exporter)
![Docker Image Size](https://img.shields.io/docker/image-size/amneziavpn/amneziawg-exporter)
![Docker Pulls](https://img.shields.io/docker/pulls/amneziavpn/amneziawg-exporter)

# AmneziaWG exporter

AmneziaWG exporter is a Prometheus exporter for gathering AmneziaWG client connection metrics.

## Features and limitations

### Client identification

amneziawg-exporter can optionally identify WireGuard clients using a client table. If this feature is enabled, clients are identified by their names; otherwise, they are marked as "unidentified."

### Operating modes

amneziawg-exporter has three operating modes (`AWG_EXPORTER_OPS_MODE` environment variable):

- `http` - Run an HTTP server on `AWG_EXPORTER_HTTP_PORT` to make metrics accessible, like most exporters. *Default*
- `metricsfile` - Write metrics to `AWG_EXPORTER_METRICS_FILE` instead of serving them on an HTTP port.
- `oneshot` - Same as in `metricsfile` mode, but the service creates a metrics file and then shuts down. In Docker, you can use a volume to save the file on disk. It can then be used by [node-exporter](https://github.com/prometheus/node_exporter) to serve your exporter metrics.
- `grafana_cloud` - Sends metrics directly to Grafana Cloud using the provided API URL and token.

> [!TIP]
> Open [this link](https://github.com/prometheus/node_exporter#textfile-collector) to read more about the textfile collector.

## Configuration

The following environment variables can be used to configure amneziawg-exporter.

| Variable Name                        | Default Value               | Description                                                             |
|--------------------------------------|-----------------------------|-------------------------------------------------------------------------|
| AWG_EXPORTER_SCRAPE_INTERVAL         | 60                          | Interval for scraping WireGuard metrics (for the `http` mode).          |
| AWG_EXPORTER_HTTP_PORT               | 9351                        | Port for HTTP service.                                                  |
| AWG_EXPORTER_LISTEN_ADDR             | 0.0.0.0                     | Listen address for HTTP service.                                        |
| AWG_EXPORTER_METRICS_FILE            | /tmp/prometheus/awg.prom    | Path to the metrics file for Node exporter textfile collector.          |
| AWG_EXPORTER_OPS_MODE                | http                        | Operation mode for the exporter (`http`, `metricsfile`, `oneshot` or `grafana_cloud`). |
| AWG_EXPORTER_AWG_SHOW_EXEC           | "awg show all dump"         | Command to run the `awg show` command.                                  |
| AWG_EXPORTER_LABEL_*                 |                             | Additional labels to add to each metric (`AWG_EXPORTER_LABEL_(.*)` - lowercase key by this regexp) |
| AWG_EXPORTER_REDIS_HOST              | localhost                   | Redis server host to store peers data                                   |
| AWG_EXPORTER_REDIS_PORT              | 6379                        | Redis server port to store peers data                                   |
| AWG_EXPORTER_REDIS_DB                | 0                           | Redis server db number to store peers data                              |
## Metrics

| Metric name                          | Labels               | Description                                                                 |
|--------------------------------------|----------------------|-----------------------------------------------------------------------------|
| awg_current_online                   |                      | Current number of online users.                                             |
| awg_dau                              |                      | Daily active users.                                                         |
| awg_mau                              |                      | Monthly active users.                                                       |
| awg_status                           |                      | Exporter status. 1 - OK, 0 - not OK                                         |

## Docker image

The Docker image is built using the [Dockerfile](Dockerfile) available in this repository. You can easily obtain it from [DockerHub](https://hub.docker.com/r/amneziavpn/amneziawg-exporter) by running the command `docker pull amneziavpn/amneziawg-exporter.`


## Example usage

You can use example [docker-compose.yml](docker-compose.yml) with Docker Compose v2 to run AmneziaWG exporter:

```sh
# docker compose up -d
[+] Running 3/3
 ✔ Network amneziawg-exporter_default  Created          0.2s
 ✔ Container amneziawg-exporter-redis  Started          0.1s
 ✔ Container amneziawg-exporter        Started          0.1s
# docker compose ps
NAME                 IMAGE                                          COMMAND                         SERVICE              CREATED          STATUS          PORTS
amneziawg-exporter         amneziavpn/amneziawg-exporter:latest   "/exporter.py"           amneziawg-exporter         15 seconds ago   Up 14 seconds   0.0.0.0:9351->9351/tcp, :::9351->9351/tcp
amneziawg-exporter-redis   redis:alpine                           "docker-entrypoint.s…"   amneziawg-exporter-redis   15 seconds ago   Up 14 seconds   6379/tcp
```

> [!TIP]
> Run `docker compose build` before, if you want to build image by yourself.

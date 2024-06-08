##############################################################################
#=======================| Wal-g exporter Builder Image |=====================#
##############################################################################
FROM python:bookworm AS builder
ARG DEBIAN_FRONTEND=noninteractive
RUN pip3 install python-decouple prometheus-client pyinstaller
COPY . /exporter
WORKDIR /exporter
RUN pyinstaller --name amneziawg-exporter --onefile exporter.py

FROM debian:bookworm-slim as exporter
COPY --from=builder /exporter/dist/amneziawg-exporter /usr/bin/amneziawg-exporter
COPY ./Dockerfile /
CMD ["/usr/bin/amneziawg-exporter"]
ARG VERSION
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.source=https://github.com/shipilovds/amneziawg-exporter
LABEL org.opencontainers.image.description='Prometheus Exporter for AmneziaWG Server'
LABEL org.opencontainers.image.authors='@shipilovds (shipilovds@gmail.com)'
LABEL org.opencontainers.image.url=https://github.com/shipilovds/amneziawg-exporter
LABEL org.opencontainers.image.documentation=https://github.com/shipilovds/amneziawg-exporter/blob/main/README.md

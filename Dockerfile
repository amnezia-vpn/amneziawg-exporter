##############################################################################
#=======================| Wal-g exporter Builder Image |=====================#
##############################################################################
FROM python:bookworm@sha256:ece3e93bb15459b7683aa1b205ab43086750cc64a088a948cf0a176f2166712c AS builder
ARG DEBIAN_FRONTEND=noninteractive
RUN pip3 install python-decouple prometheus-client pyinstaller requests
COPY . /exporter
WORKDIR /exporter
RUN pyinstaller --name amneziawg-exporter --onefile exporter.py

FROM debian:bookworm-slim@sha256:5f7d5664eae4a192c2d2d6cb67fc3f3c7891a8722cd2903cc35aa649a12b0c8d as exporter-old
COPY --from=builder /exporter/dist/amneziawg-exporter /usr/bin/amneziawg-exporter
COPY ./Dockerfile /
CMD ["/usr/bin/amneziawg-exporter"]
ARG VERSION
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.source=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.description='Prometheus Exporter for AmneziaWG Server'
LABEL org.opencontainers.image.authors='@shipilovds (shipilovds@gmail.com)'
LABEL org.opencontainers.image.url=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.documentation=https://github.com/amnezia-vpn/amneziawg-exporter/blob/main/README.md


FROM python:alpine as exporter
ARG DEBIAN_FRONTEND=noninteractive
RUN pip3 install python-decouple prometheus-client requests
COPY ./exporter.py /
COPY ./Dockerfile /
CMD ["/exorter.py"]
ARG VERSION
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.source=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.description='Prometheus Exporter for AmneziaWG Server'
LABEL org.opencontainers.image.authors='@shipilovds (shipilovds@gmail.com)'
LABEL org.opencontainers.image.url=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.documentation=https://github.com/amnezia-vpn/amneziawg-exporter/blob/main/README.md

FROM python:3.12.5-slim-bookworm AS exporter
ARG DEBIAN_FRONTEND=noninteractive
RUN pip3 install --no-cache-dir \
    prometheus_client==0.20.0 \
    python-decouple==3.8 \
    requests==2.32.3
COPY --chmod=755 ./exporter.py ./Dockerfile /
CMD ["/exporter.py"]
ARG VERSION
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.source=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.description='Prometheus Exporter for AmneziaWG Server'
LABEL org.opencontainers.image.authors='@shipilovds (shipilovds@gmail.com)'
LABEL org.opencontainers.image.url=https://github.com/amnezia-vpn/amneziawg-exporter
LABEL org.opencontainers.image.documentation=https://github.com/amnezia-vpn/amneziawg-exporter/blob/main/README.md

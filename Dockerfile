##############################################################################
#=======================| Wal-g exporter Builder Image |=====================#
##############################################################################
FROM python:bookworm AS exporter-builder
ARG DEBIAN_FRONTEND=noninteractive
RUN pip3 install python-decouple prometheus-client pyinstaller
COPY . /exporter
WORKDIR /exporter
RUN pyinstaller --name awg-exporter --onefile exporter.py

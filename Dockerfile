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
CMD ["/usr/bin/amneziawg-exporter"]

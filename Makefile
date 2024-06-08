.PHONY: build docker
VERSION := 0.9.3


build:
	docker build -t amneziawg-exporter-builder --target builder .
	$(eval _CONTANER_ID := $(shell docker create amneziawg-exporter-builder))
	docker cp $(_CONTANER_ID):/exporter/dist/amneziawg-exporter .
	docker rm $(_CONTANER_ID)

docker:
	docker build -t ghcr.io/shipilovds/amneziawg-exporter:$(VERSION) --target exporter .

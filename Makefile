all:

build:
	docker build -t awg-builder --target builder .
	$(eval _CONTANER_ID := $(shell docker create amnezia-exporter))
	docker cp $(_CONTANER_ID):/exporter/dist/awg-exporter .
	docker rm $(_CONTANER_ID)

docker:
	docker build -t ghcr.io/shipilovds/awg-exporter --target exporter .

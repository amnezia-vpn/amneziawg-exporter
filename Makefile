all:
	docker build -t amnezia-exporter .
	$(eval _CONTANER_ID := $(shell docker create amnezia-exporter))
	docker cp $(_CONTANER_ID):/exporter/dist/awg-exporter .
	docker rm $(_CONTANER_ID)

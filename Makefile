.PHONY: build docker docker_build docker_retag docker_login docker_push

VERSION            := 1.0.0
PROJECT_NAME       ?= amneziawg-exporter
DOCKER_BUILDKIT    ?= 1
DOCKER_REGISTRY    ?= ghcr.io
DOCKER_USER        ?= none
DOCKER_PASSWORD    ?= none
DOCKER_IMAGE       ?= $(PROJECT_NAME)
DOCKER_TAG         ?= latest


ifeq ($(DOCKER_IMAGE), $(PROJECT_NAME))
    DOCKER_TARGETS := docker_build
else
	DOCKER_TAG     := $(VERSION)
    DOCKER_TARGETS := docker_build docker_push
endif


build: $(PROJECT_NAME)

$(PROJECT_NAME):
	docker build . -t $(PROJECT_NAME)-builder --target builder --build-arg VERSION=$(VERSION)
	$(eval _CONTANER_ID := $(shell docker create $(PROJECT_NAME)-builder))
	docker cp $(_CONTANER_ID):/exporter/dist/$(PROJECT_NAME) .
	docker rm $(_CONTANER_ID)

docker: $(DOCKER_TARGETS)

docker_build:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) --target exporter .

docker_retag:
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_IMAGE):latest

docker_login:
	@echo "docker login -u ******* -p ******** $(DOCKER_REGISTRY)"
	@docker login -u $(DOCKER_USER) -p $(DOCKER_PASSWORD) $(DOCKER_REGISTRY)

docker_push: docker_login docker_retag
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest

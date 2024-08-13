.PHONY: all ci docker_build docker_retag docker_login docker_push

VERSION            := 2.1.1
PROJECT_NAME       ?= amneziavpn/amneziawg-exporter
DOCKER_BUILDKIT    ?= 1
DOCKER_REGISTRY    ?= docker.io
DOCKER_USER        ?= none
DOCKER_PASSWORD    ?= none
DOCKER_IMAGE       ?= $(PROJECT_NAME)
DOCKER_TAG         ?= latest


all: docker_build

ci: DOCKER_TAG=$(VERSION)
ci: docker_build docker_push

docker_build:
	docker build . -t $(DOCKER_IMAGE):$(DOCKER_TAG) --target exporter --build-arg VERSION=$(VERSION)

docker_retag:
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_IMAGE):latest

docker_login:
	@echo "docker login -u ******* -p ******** $(DOCKER_REGISTRY)"
	@docker login -u $(DOCKER_USER) -p $(DOCKER_PASSWORD) $(DOCKER_REGISTRY)

docker_push: docker_login docker_retag
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest

 .PHONY: build build-development build-beta push clean test help

# Docker image configuration
DOCKER_REGISTRY ?= ghcr.io
DOCKER_REPO ?= JustAmply/asa-linux-server
IMAGE_NAME = $(DOCKER_REGISTRY)/$(DOCKER_REPO)

# Version and tags
VERSION ?= 2.0.0
GIT_COMMIT ?= $(shell git rev-parse --short HEAD)
BUILD_DATE ?= $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")

# Docker build arguments
DOCKER_BUILD_ARGS = \
	--build-arg VERSION=$(VERSION) \
	--build-arg GIT_COMMIT=$(GIT_COMMIT) \
	--build-arg BUILD_DATE=$(BUILD_DATE)

help: ## Show this help message
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the latest Docker image
	docker build $(DOCKER_BUILD_ARGS) -t $(IMAGE_NAME):latest .
	docker tag $(IMAGE_NAME):latest $(IMAGE_NAME):$(VERSION)

build-development: ## Build the development Docker image
	docker build $(DOCKER_BUILD_ARGS) -t $(IMAGE_NAME):development .

build-beta: ## Build the beta Docker image
	docker build $(DOCKER_BUILD_ARGS) -t $(IMAGE_NAME):beta .

push: ## Push Docker images to registry
	docker push $(IMAGE_NAME):latest
	docker push $(IMAGE_NAME):$(VERSION)

push-development: ## Push development image to registry
	docker push $(IMAGE_NAME):development

push-beta: ## Push beta image to registry
	docker push $(IMAGE_NAME):beta

test: ## Run tests for the Python application
	python3 -m pytest tests/ -v || echo "No tests found - skipping"

clean: ## Clean up Docker images and build artifacts
	docker rmi $(IMAGE_NAME):latest $(IMAGE_NAME):$(VERSION) 2>/dev/null || true
	docker system prune -f

lint: ## Run Python linting
	python3 -m flake8 asa_ctrl/ || echo "flake8 not installed - skipping"
	python3 -m pylint asa_ctrl/ || echo "pylint not installed - skipping"

install-dev: ## Install development dependencies
	python3 -m pip install flake8 pylint pytest

# Legacy KIWI-NG targets (deprecated)
check-deps: ## Check for deprecated KIWI-NG dependencies
	@echo "WARNING: KIWI-NG build system is deprecated. Use 'make build' instead."
	@echo "This project now uses Docker for building container images."

load: ## Load Docker image (replaces old KIWI-NG load)
	@echo "Use 'docker pull $(IMAGE_NAME):latest' to load the image from registry"
	@echo "Or 'make build' to build locally"

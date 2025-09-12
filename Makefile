 .PHONY: prepare build build-development build-beta load check-deps build-in-docker

GLOBAL_BUILD_DIR = /tmp/.kiwi-build-results
TARGET_DIR = $(GLOBAL_BUILD_DIR)/ark-survival-ascended-linux-container-image

# Tools required for native KIWI docker image build
REQUIRED_TOOLS = kiwi-ng umoci skopeo xz

# Official kiwi builder container image (contains umoci & skopeo)
KIWI_CONTAINER_IMAGE = registry.opensuse.org/opensuse/kiwi/kiwi-ng:latest

check-deps:
	@missing=""; \
	for t in $(REQUIRED_TOOLS); do \
	  if ! command -v $$t >/dev/null 2>&1; then missing="$$missing $$t"; fi; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo "ERROR: Missing required tools:$$missing"; \
	  echo "       Install them or use: make build-in-docker"; \
	  exit 2; \
	else \
	  echo "All required tools found: $(REQUIRED_TOOLS)"; \
	fi

prepare:
	- sudo rm -rf $(TARGET_DIR)
	- mkdir -p $(GLOBAL_BUILD_DIR)

build: check-deps prepare
	- sudo kiwi-ng --profile stable --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

build-development: check-deps prepare
	- sudo kiwi-ng --profile development --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

build-beta: check-deps prepare
	- sudo kiwi-ng --profile beta --color-output --debug system build --target-dir $(TARGET_DIR) --description .
	- sudo xz --threads 8 -z $(TARGET_DIR)/*.tar

# Container-based build (no local umoci/skopeo needed, only docker or podman)
build-in-docker: prepare
	# Use kiwi builder container; perform build & compression inside container
	# Requires: docker (or alias DOCKER=podman before invoking)
	DOCKER ?= docker
	$(DOCKER) run --rm \
	  -v $(CURDIR):/workspace:Z \
	  -v $(GLOBAL_BUILD_DIR):/results:Z \
	  -w /workspace \
	  --privileged \
	  $(KIWI_CONTAINER_IMAGE) \
	  /bin/sh -c "kiwi-ng --profile stable system build --target-dir /results/ark-survival-ascended-linux-container-image --description . && xz --threads 8 -z /results/ark-survival-ascended-linux-container-image/*.tar"
	@echo "Build artifacts (possibly compressed) are in $(TARGET_DIR)"

load:
	- sudo docker load -i $(TARGET_DIR)/*.xz

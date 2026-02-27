FROM ubuntu:24.04

ARG TARGETARCH=amd64

# Build arguments for metadata
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"
ARG DEBIAN_FRONTEND=noninteractive
ARG FEX_ROOTFS_METADATA_URL="https://rootfs.fex-emu.gg/RootFS_links.json"
ARG FEX_ROOTFS_ENTRY="Ubuntu 24.04 (SquashFS)"
ARG FEX_EMU_PACKAGE="fex-emu-armv8.0"
ARG FEX_EMU_VERSION="2601~n"

# Add metadata labels
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.title="ARK: Survival Ascended Linux Server" \
      org.opencontainers.image.description="Dockerized ARK: Survival Ascended server with asa_ctrl management tool" \
      org.opencontainers.image.source="https://github.com/JustAmply/ark-survival-ascended-server"

# Ensure timezone data is available and default to UTC inside the container
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    locales \
    python-is-python3 \
    python3 \
    software-properties-common \
    tzdata \
    unzip \
    wget \
    xxhash \
    libc6-dev \
    libfreetype6 \
    && if [ "$TARGETARCH" = "amd64" ]; then \
      apt-get install -y --no-install-recommends \
        lib32stdc++6 \
        lib32z1 \
        lib32gcc-s1; \
    fi \
    && if [ "$TARGETARCH" = "arm64" ]; then \
      add-apt-repository -y ppa:fex-emu/fex; \
      apt-get update; \
      apt-get install -y --no-install-recommends "${FEX_EMU_PACKAGE}=${FEX_EMU_VERSION}"; \
      mkdir -p /home/gameserver/.fex-emu/RootFS; \
      FEX_ROOTFS_TARGET="/home/gameserver/.fex-emu/RootFS/Ubuntu_24_04.sqsh"; \
      FEX_ROOTFS_METADATA_URL="$FEX_ROOTFS_METADATA_URL" \
      FEX_ROOTFS_ENTRY="$FEX_ROOTFS_ENTRY" \
      FEX_ROOTFS_TARGET="$FEX_ROOTFS_TARGET" \
      python3 - <<'PY' > /tmp/fex_rootfs.xxhash
import json
import os
import pathlib
import urllib.request

metadata_url = os.environ["FEX_ROOTFS_METADATA_URL"]
entry_name = os.environ["FEX_ROOTFS_ENTRY"]
target = pathlib.Path(os.environ["FEX_ROOTFS_TARGET"])

with urllib.request.urlopen(metadata_url, timeout=30) as response:
    metadata = json.load(response)

entry = (metadata.get("v1") or {}).get(entry_name)
if not isinstance(entry, dict):
    raise SystemExit(f"FEX RootFS entry not found: {entry_name!r}")

url = str(entry.get("URL", "")).strip()
expected_hash = str(entry.get("Hash", "")).strip().lower()
if not url or not expected_hash:
    raise SystemExit("FEX RootFS metadata entry is incomplete")

target.parent.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(url, timeout=120) as source, target.open("wb") as destination:
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        destination.write(chunk)

print(f"{expected_hash}  {target}")
PY
      xxhsum -c /tmp/fex_rootfs.xxhash; \
      rm -f /tmp/fex_rootfs.xxhash; \
    fi \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \
    && locale-gen

# Set locale-related environment variables early (inherit to runtime)
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PYTHONPATH=/usr/share \
    FEX_APP_DATA_LOCATION=/home/gameserver/.fex-emu \
    FEX_ROOTFS=/home/gameserver/.fex-emu/RootFS/Ubuntu_24_04.sqsh

# Create gameserver user
RUN groupadd -g 25000 gameserver && \
    useradd -u 25000 -g gameserver -m -d /home/gameserver gameserver

# Create necessary directories
RUN mkdir -p \
    /home/gameserver/Steam \
    /home/gameserver/steamcmd \
    /home/gameserver/server-files \
    /home/gameserver/cluster-shared \
    /home/gameserver/.fex-emu/RootFS && \
    chown -R gameserver:gameserver /home/gameserver

# Copy Python applications
COPY asa_ctrl /usr/share/asa_ctrl
COPY server_runtime /usr/share/server_runtime

# Create launcher script for Python application (avoid pip install to prevent PEP 668 issues)
WORKDIR /usr/share
RUN echo '#!/bin/bash' > /usr/local/bin/asa-ctrl && \
    echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' >> /usr/local/bin/asa-ctrl && \
    echo 'exec python -m asa_ctrl "$@"' >> /usr/local/bin/asa-ctrl && \
    sed -i 's/\\"/"/g' /usr/local/bin/asa-ctrl && \
    chmod +x /usr/local/bin/asa-ctrl

# Ensure PYTHONPATH is available for all shells
RUN echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' > /etc/profile.d/asa_ctrl.sh

# Copy server management script
COPY scripts/start_server.sh /usr/bin/start_server.sh

# Set permissions
RUN chmod +x /usr/bin/start_server.sh

# Declare persistent data volumes
VOLUME ["/home/gameserver/Steam", \
        "/home/gameserver/steamcmd", \
        "/home/gameserver/server-files", \
        "/home/gameserver/cluster-shared"]

# Set working directory
WORKDIR /home/gameserver

# Entry point
ENTRYPOINT ["python", "-m", "server_runtime"]

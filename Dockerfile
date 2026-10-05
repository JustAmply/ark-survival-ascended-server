ARG TARGETARCH

FROM python:3.14-slim AS runtime-amd64

# Ensure timezone data is available and default to UTC inside the container
ENV TZ=UTC
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    tzdata \
    lib32stdc++6 \
    lib32z1 \
    lib32gcc-s1 \
    libfreetype6 \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/* && \
    echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen

# Keep all emulation dependencies out of the stable AMD64 image.
FROM ubuntu:24.04 AS runtime-arm64
ARG DEBIAN_FRONTEND=noninteractive
ARG FEX_EMU_VERSION="2609.1-1~n"
ARG FEX_ROOTFS_URL="https://rootfs.fex-emu.gg/Ubuntu_24_04/2026-08-11/Ubuntu_24_04.sqsh"
ARG FEX_ROOTFS_HASH="3517e0e5ea25a473"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    locales \
    python-is-python3 \
    python3 \
    software-properties-common \
    squashfs-tools \
    tzdata \
    wget \
    xxhash \
    libc6-dev \
    libfreetype6 \
    libvulkan1 \
    && add-apt-repository -y ppa:fex-emu/fex \
    && apt-get update \
    && apt-get install -y --no-install-recommends "fex-emu-armv8.0=${FEX_EMU_VERSION}" \
    && wget --https-only -q "${FEX_ROOTFS_URL}" -O /tmp/fex-rootfs.sqsh \
    && printf '%s  /tmp/fex-rootfs.sqsh\n' "${FEX_ROOTFS_HASH}" | xxhsum -c - \
    && unsquashfs -no-progress -d /opt/fex-rootfs /tmp/fex-rootfs.sqsh \
    && rm /tmp/fex-rootfs.sqsh \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \
    && locale-gen

# An extracted directory works without FUSE or elevated container privileges.
ENV FEX_APP_DATA_LOCATION=/home/gameserver/.fex-emu \
    FEX_ROOTFS=/opt/fex-rootfs

FROM runtime-${TARGETARCH} AS runtime
ENV TZ=UTC

# Set locale-related environment variables early (inherit to runtime)
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PYTHONPATH=/usr/share

# Wine spawns several hundred threads for ASA; glibc would otherwise open up to
# 8 malloc arenas per core and fragment the heap across all of them.
ENV MALLOC_ARENA_MAX=2

# Create gameserver user
RUN groupadd -g 25000 gameserver && \
    useradd -u 25000 -g gameserver -m -d /home/gameserver gameserver

# Create necessary directories
RUN mkdir -p \
    /home/gameserver/Steam \
    /home/gameserver/steamcmd \
    /home/gameserver/server-files \
    /home/gameserver/cluster-shared && \
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

# Keep changing metadata after all filesystem layers so it cannot invalidate
# the OS installation or application cache.
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.title="ARK: Survival Ascended Linux Server" \
      org.opencontainers.image.description="Dockerized ARK: Survival Ascended server with asa_ctrl management tool" \
      org.opencontainers.image.source="https://github.com/JustAmply/ark-survival-ascended-server"

# The Proton preflight cache must still see the resolved image version.
ENV ASA_IMAGE_VERSION=${VERSION}

# Declare persistent data volumes
VOLUME ["/home/gameserver/Steam", \
        "/home/gameserver/steamcmd", \
        "/home/gameserver/server-files", \
        "/home/gameserver/cluster-shared"]

# Set working directory
WORKDIR /home/gameserver

# Entry point
ENTRYPOINT ["python", "-m", "server_runtime"]

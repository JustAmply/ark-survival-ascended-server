# syntax=docker/dockerfile:1
ARG TARGETARCH

# Build against Ubuntu's libc instead of copying Debian-built Python into FEX's
# Ubuntu host. Only this stage contains compilers and development headers.
FROM ubuntu:24.04 AS arm64-python
ARG DEBIAN_FRONTEND=noninteractive
ARG PYTHON_VERSION="3.14.8"
ARG PYTHON_SHA256="c2215904f02b175596dc49351585104f4bc20341e1c47378b26a2c274360ce73"
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget build-essential libbz2-dev libffi-dev libgdbm-dev \
    libgdbm-compat-dev liblzma-dev libncursesw5-dev libreadline-dev \
    libsqlite3-dev libssl-dev libzstd-dev uuid-dev zlib1g-dev \
    && wget --https-only -q "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz" -O /tmp/python.tar.xz \
    && echo "${PYTHON_SHA256}  /tmp/python.tar.xz" | sha256sum -c - \
    && mkdir /tmp/python \
    && tar -xJf /tmp/python.tar.xz -C /tmp/python --strip-components=1 \
    && cd /tmp/python \
    && ./configure --enable-shared --with-lto --with-ensurepip=no \
    && make -j "$(nproc)" LDFLAGS="-Wl,--strip-all" \
    && make altinstall \
    && ln -s python3.14 /usr/local/bin/python3 \
    && ln -s python3.14 /usr/local/bin/python \
    && find /usr/local -depth \( \
        \( -type d \( -name test -o -name tests -o -name idle_test -o -name __pycache__ \) \) \
        -o \( -type f \( -name '*.pyc' -o -name '*.pyo' -o -name 'libpython*.a' \) \) \
       \) -exec rm -rf '{}' + \
    && rm -rf /usr/local/include /usr/local/lib/pkgconfig /usr/local/share

# RootFS files are x86 data; download and extract them on the build host.
# Cross-builds do not need to emulate ARM64 for this expensive preparation.
FROM --platform=$BUILDPLATFORM ubuntu:24.04 AS fex-rootfs
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget xxhash squashfs-tools \
    && rm -rf /var/lib/apt/lists/*

ARG FEX_ROOTFS_URL="https://rootfs.fex-emu.gg/Ubuntu_24_04/2026-08-11/Ubuntu_24_04.sqsh"
ARG FEX_ROOTFS_HASH="3517e0e5ea25a473"
# FEX metadata uses XXH3-64, while xxhsum defaults to the older XXH64.
RUN wget --https-only -q "${FEX_ROOTFS_URL}" -O /tmp/fex-rootfs.sqsh \
    && printf 'XXH3 (/tmp/fex-rootfs.sqsh) = %s\n' "${FEX_ROOTFS_HASH}" | xxhsum -c - \
    && unsquashfs -no-progress -d /opt/fex-rootfs /tmp/fex-rootfs.sqsh \
    && rm /tmp/fex-rootfs.sqsh

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
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    locales \
    software-properties-common \
    tzdata \
    libfreetype6 \
    libvulkan1 \
    libbz2-1.0 libffi8 libgdbm6t64 libgdbm-compat4t64 liblzma5 \
    libncursesw6 libreadline8t64 libsqlite3-0 libssl3t64 libzstd1 libuuid1 zlib1g \
    && add-apt-repository -y ppa:fex-emu/fex \
    && apt-get update \
    && apt-get install -y --no-install-recommends "fex-emu-armv8.0=${FEX_EMU_VERSION}" \
    && apt-get purge -y --auto-remove software-properties-common gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \
    && locale-gen

COPY --link --from=arm64-python /usr/local /usr/local
RUN ldconfig && python --version
ENV PATH="/usr/local/bin:${PATH}"
COPY --link --from=fex-rootfs /opt/fex-rootfs /opt/fex-rootfs

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

# Create launcher script for Python application (avoid pip install to prevent PEP 668 issues)
WORKDIR /usr/share
RUN echo '#!/bin/bash' > /usr/local/bin/asa-ctrl && \
    echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' >> /usr/local/bin/asa-ctrl && \
    echo 'exec python -m asa_ctrl "$@"' >> /usr/local/bin/asa-ctrl && \
    sed -i 's/\\"/"/g' /usr/local/bin/asa-ctrl && \
    chmod +x /usr/local/bin/asa-ctrl

# Ensure PYTHONPATH is available for all shells
RUN echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' > /etc/profile.d/asa_ctrl.sh

# Copy the stable launch wrapper before frequently changing application code.
COPY --chmod=0755 scripts/start_server.sh /usr/bin/start_server.sh

# Link source layers independently so base-image changes can reuse them.
COPY --link asa_ctrl /usr/share/asa_ctrl
COPY --link server_runtime /usr/share/server_runtime

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

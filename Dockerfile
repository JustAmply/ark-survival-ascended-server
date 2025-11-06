# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS base

# Build arguments for metadata
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"

# Add metadata labels
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.title="ARK: Survival Ascended Linux Server" \
      org.opencontainers.image.description="Dockerized ARK: Survival Ascended server with asa_ctrl management tool" \
      org.opencontainers.image.source="https://github.com/JustAmply/ark-survival-ascended-server"

# Ensure timezone data is available and default to UTC inside the container
ENV TZ=UTC
ARG DEBIAN_FRONTEND=noninteractive

# Install base packages (common to all architectures)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        locales \
        tzdata \
        wget \
        curl \
        ca-certificates \
        unzip \
        libfreetype6 \
    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \
    && locale-gen

# Set locale-related environment variables early (inherit to runtime)
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

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

# Copy Python application
COPY asa_ctrl /usr/share/asa_ctrl

# Copy ARM64 compatibility test script
COPY tests/test_arm64_compat.sh /usr/share/tests/test_arm64_compat.sh
RUN chmod +x /usr/share/tests/test_arm64_compat.sh

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
ENTRYPOINT ["/usr/bin/start_server.sh"]

FROM base
ARG TARGETARCH
ARG DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    # Ensure required runtime libraries (font rendering and crypto primitives)
    # are present for all supported architectures so Proton / Steam components
    # can launch under emulation.
    case "${TARGETARCH}" in \
        amd64) \
            apt-get update; \
            apt-get install -y --no-install-recommends \
                lib32stdc++6 \
                lib32z1 \
                lib32gcc-s1 \
                libfontconfig1 \
                libgcrypt20; \
            ;; \
        arm64) \
            dpkg --add-architecture armhf; \
            dpkg --add-architecture i386; \
            dpkg --add-architecture amd64; \
            mkdir -p /usr/share/keyrings /etc/apt/sources.list.d; \
            curl -fsSL https://pi-apps-coders.github.io/box64-debs/KEY.gpg -o /usr/share/keyrings/box64-archive-keyring.gpg; \
            curl -fsSL https://pi-apps-coders.github.io/box86-debs/KEY.gpg -o /usr/share/keyrings/box86-archive-keyring.gpg; \
            printf '%s\n' \
                'Types: deb' \
                'URIs: https://Pi-Apps-Coders.github.io/box64-debs/debian' \
                'Suites: ./' \
                'Signed-By: /usr/share/keyrings/box64-archive-keyring.gpg' \
                > /etc/apt/sources.list.d/box64.sources; \
            printf '%s\n' \
                'Types: deb' \
                'URIs: https://Pi-Apps-Coders.github.io/box86-debs/debian' \
                'Suites: ./' \
                'Signed-By: /usr/share/keyrings/box86-archive-keyring.gpg' \
                > /etc/apt/sources.list.d/box86.sources; \
            apt-get update; \
            apt-get install -y --no-install-recommends \
                libc6:armhf \
                libstdc++6:armhf \
                libgcc-s1:armhf \
                libtinfo6:armhf \
                zlib1g:armhf \
                libfontconfig1:armhf \
                libgcrypt20:armhf \
                libc6:i386 \
                libstdc++6:i386 \
                libgcc-s1:i386 \
                zlib1g:i386 \
                libcurl4:i386 \
                libbz2-1.0:i386 \
                libx11-6:i386 \
                libxext6:i386 \
                libfontconfig1:i386 \
                libgcrypt20:i386 \
                libc6:amd64 \
                libstdc++6:amd64 \
                libgcc-s1:amd64 \
                zlib1g:amd64 \
                libcurl4:amd64 \
                libfontconfig1:amd64 \
                libgcrypt20:amd64 \
                libfontconfig1:arm64 \
                libgcrypt20:arm64 \
                box64-generic-arm \
                box86-generic-arm:armhf; \
            ;; \
        *) \
            echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; \
            exit 1; \
            ;; \
    esac; \
    ldconfig

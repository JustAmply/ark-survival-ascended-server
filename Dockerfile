# syntax=docker/dockerfile:1.4
ARG PYTHON_IMAGE=python:3.12-slim
ARG BOX64_VERSION="v0.2.4"
ARG BOX64_PACKAGE="box64-GENERIC_ARM-RelWithDebInfo.zip"
ARG BOX64_SHA256="0ba1e169a0bc846875366162cda126341cb959b24bc3907171de7c961a6c35af"

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
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    tzdata \
    wget \
    curl \
    ca-certificates \
    unzip \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/* && \
    echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen

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

FROM base AS amd64
ARG DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        lib32stdc++6 \
        lib32z1 \
        lib32gcc-s1; \
    rm -rf /var/lib/apt/lists/*; \
    ldconfig

FROM base AS arm64
ARG BOX64_VERSION
ARG BOX64_PACKAGE
ARG BOX64_SHA256

RUN set -eux; \
    echo "Preparing to download Box64 (inputs: version=${BOX64_VERSION}, package=${BOX64_PACKAGE}, sha256=${BOX64_SHA256:-unset})"; \
    BOX64_URL="https://github.com/ptitSeb/box64/releases/download/${BOX64_VERSION}/${BOX64_PACKAGE}"; \
    curl -fsSL "$BOX64_URL" -o /tmp/box64.zip; \
    if [ -n "${BOX64_SHA256}" ]; then \
        echo "${BOX64_SHA256}  /tmp/box64.zip" | sha256sum -c -; \
    fi; \
    unzip /tmp/box64.zip -d /tmp/box64; \
    install -m 0755 /tmp/box64/box64 /usr/local/bin/box64; \
    rm -rf /tmp/box64 /tmp/box64.zip; \
    ldconfig

ARG TARGETARCH
FROM ${TARGETARCH}

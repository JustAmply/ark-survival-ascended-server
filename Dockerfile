FROM python:3.12-slim

# Build arguments for metadata
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"
ARG DEPOTDOWNLOADER_VERSION="DepotDownloader_3.4.0"

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

RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    tzdata \
    wget \
    unzip \
    ca-certificates \
    libc6-dev \
    lib32stdc++6 \
    lib32z1 \
    lib32gcc-s1 \
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
    /home/gameserver/server-files \
    /home/gameserver/cluster-shared && \
    chown -R gameserver:gameserver /home/gameserver

# Install DepotDownloader (Linux + Windows builds for Proton fallback)
ENV DEPOTDOWNLOADER_VERSION=${DEPOTDOWNLOADER_VERSION} \
    DEPOTDOWNLOADER_BASE=/opt/depotdownloader \
    DEPOTDOWNLOADER_LINUX_DIR=/opt/depotdownloader/linux \
    DEPOTDOWNLOADER_LINUX_BIN=/opt/depotdownloader/linux/DepotDownloader \
    DEPOTDOWNLOADER_WINDOWS_DIR=/opt/depotdownloader/windows \
    DEPOTDOWNLOADER_WINDOWS_BIN=/opt/depotdownloader/windows/DepotDownloader.exe

RUN set -eux; \
    mkdir -p "$DEPOTDOWNLOADER_LINUX_DIR" "$DEPOTDOWNLOADER_WINDOWS_DIR"; \
    wget -q -O /tmp/depotdownloader-linux.zip "https://github.com/SteamRE/DepotDownloader/releases/download/${DEPOTDOWNLOADER_VERSION}/DepotDownloader-linux-x64.zip"; \
    unzip -q /tmp/depotdownloader-linux.zip -d "$DEPOTDOWNLOADER_LINUX_DIR"; \
    rm /tmp/depotdownloader-linux.zip; \
    chmod +x "$DEPOTDOWNLOADER_LINUX_BIN"; \
    wget -q -O /tmp/depotdownloader-windows.zip "https://github.com/SteamRE/DepotDownloader/releases/download/${DEPOTDOWNLOADER_VERSION}/DepotDownloader-windows-x64.zip"; \
    unzip -q /tmp/depotdownloader-windows.zip -d "$DEPOTDOWNLOADER_WINDOWS_DIR"; \
    chmod +x "$DEPOTDOWNLOADER_WINDOWS_BIN"; \
    rm /tmp/depotdownloader-windows.zip

# Copy Python application
COPY asa_ctrl /usr/share/asa_ctrl

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
        "/home/gameserver/server-files", \
        "/home/gameserver/cluster-shared"]

# Set working directory
WORKDIR /home/gameserver

# Entry point
ENTRYPOINT ["/usr/bin/start_server.sh"]

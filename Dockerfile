# Dockerfile for ARK: Survival Ascended Server (Python-based)
FROM ubuntu:24.04

# Set environment variables
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

# Install required packages
RUN apt-get update && \
    apt-get install -y \
    curl \
    wget \
    tar \
    gzip \
    unzip \
    python3 \
    python3-pip \
    locales \
    libc6-dev \
    lib32stdc++6 \
    lib32z1 \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    locale-gen en_US.UTF-8

# Create gameserver user
RUN groupadd -g 25000 gameserver && \
    useradd -u 25000 -g gameserver -m -d /home/gameserver gameserver

# Create necessary directories
RUN mkdir -p /home/gameserver/{Steam,steamcmd,server-files,cluster-shared} && \
    chown -R gameserver:gameserver /home/gameserver

# Copy Python application
COPY asa_ctrl /usr/share/asa_ctrl
COPY setup.py requirements.txt /usr/share/
COPY scripts/cli-asa-mods /usr/bin/cli-asa-mods

# Install Python application
WORKDIR /usr/share
RUN python3 -m pip install --user -e . && \
    echo '#!/bin/bash' > /usr/local/bin/asa-ctrl && \
    echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' >> /usr/local/bin/asa-ctrl && \
    echo 'exec python3 -m asa_ctrl "$@"' >> /usr/local/bin/asa-ctrl && \
    chmod +x /usr/local/bin/asa-ctrl

# Copy server start script
COPY root/usr/bin/start_server /usr/bin/start_server

# Set permissions
RUN chmod +x /usr/bin/start_server && \
    chmod +x /usr/bin/cli-asa-mods

# Set working directory
WORKDIR /home/gameserver

# Default user
USER gameserver

# Entry point
ENTRYPOINT ["/usr/bin/start_server"]
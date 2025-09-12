FROM ubuntu:24.04

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
    dos2unix \
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
COPY scripts/cli-asa-mods.sh /usr/bin/cli-asa-mods.sh

# Create launcher script for Python application (avoid pip install to prevent PEP 668 issues)
WORKDIR /usr/share
RUN echo '#!/bin/bash' > /usr/local/bin/asa-ctrl && \
    echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' >> /usr/local/bin/asa-ctrl && \
    echo 'exec python3 -m asa_ctrl "$@"' >> /usr/local/bin/asa-ctrl && \
    sed -i 's/\\"/"/g' /usr/local/bin/asa-ctrl && \
    chmod +x /usr/local/bin/asa-ctrl

# Ensure PYTHONPATH is available for all shells so cli-asa-mods works
RUN echo 'export PYTHONPATH=/usr/share:$PYTHONPATH' > /etc/profile.d/asa_ctrl.sh

# Copy server start script
COPY scripts/start_server.sh /usr/bin/start_server.sh

# Set permissions
RUN dos2unix /usr/bin/start_server.sh /usr/bin/cli-asa-mods.sh && \
    chmod +x /usr/bin/start_server.sh /usr/bin/cli-asa-mods.sh

# Set working directory
WORKDIR /home/gameserver

# Entry point
ENTRYPOINT ["/usr/bin/start_server.sh"]
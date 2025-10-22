FROM python:3.12-slim

# Build arguments for metadata
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"
ARG TARGETARCH

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

# Install base dependencies (architecture-agnostic)
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    tzdata \
    wget \
    unzip \
    libc6-dev \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/* && \
    echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen

# Install architecture-specific dependencies
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            lib32stdc++6 \
            lib32z1 \
            lib32gcc-s1 \
        && rm -rf /var/lib/apt/lists/*; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            ca-certificates \
            curl \
            gnupg \
        && mkdir -p /usr/share/keyrings \
        && curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xEDB98BFE8A2310DC9C4A376E76DBFEBEA206F5AC" \
            | gpg --batch --yes --dearmor -o /usr/share/keyrings/fex-archive-keyring.gpg \
        && echo "deb [arch=arm64 signed-by=/usr/share/keyrings/fex-archive-keyring.gpg] https://ppa.launchpadcontent.net/fex-emu/fex/ubuntu jammy main" \
            > /etc/apt/sources.list.d/fex-emu.list \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            fex-emu \
        && rm -rf /var/lib/apt/lists/*; \
    fi

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

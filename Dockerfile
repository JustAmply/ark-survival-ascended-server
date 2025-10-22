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
        && curl -fsSL https://ryanfortner.github.io/box64-debs/KEY.gpg \
            | gpg --batch --yes --dearmor -o /usr/share/keyrings/box64-archive-keyring.gpg \
        && echo "deb [arch=arm64 signed-by=/usr/share/keyrings/box64-archive-keyring.gpg] https://ryanfortner.github.io/box64-debs/debian ./" \
            > /etc/apt/sources.list.d/box64.list \
        && curl -fsSL https://ryanfortner.github.io/box86-debs/KEY.gpg \
            | gpg --batch --yes --dearmor -o /usr/share/keyrings/box86-archive-keyring.gpg \
        && echo "deb [arch=armhf signed-by=/usr/share/keyrings/box86-archive-keyring.gpg] https://ryanfortner.github.io/box86-debs/debian ./" \
            > /etc/apt/sources.list.d/box86.list \
        && dpkg --add-architecture armhf \
        && dpkg --add-architecture amd64 \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            box64 \
            box86-generic-arm:armhf \
            wine64:amd64 \
            libc6:armhf \
            libstdc++6:armhf \
            libgcc-s1:armhf \
            zlib1g:armhf \
        && if ! command -v wine64 >/dev/null 2>&1; then \
            wine64_path="$(find /usr -maxdepth 5 -type f -name wine64 | head -n 1)"; \
            if [ -n "$wine64_path" ]; then \
                ln -s "$wine64_path" /usr/local/bin/wine64; \
            else \
                echo \"wine64 binary not found after installation\" >&2; \
                exit 1; \
            fi; \
        fi \
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

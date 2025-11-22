# Multi-arch Dockerfile for ARK: Survival Ascended
# Supports amd64 (Intel/AMD) and arm64 (Apple Silicon / Ampere) via FEX-Emu
FROM ubuntu:24.04

# Build arguments
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"
ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

# Add metadata labels
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.title="ARK: Survival Ascended Linux Server" \
      org.opencontainers.image.description="Dockerized ARK: Survival Ascended server with asa_ctrl management tool (Multi-arch)" \
      org.opencontainers.image.source="https://github.com/JustAmply/ark-survival-ascended-server"

# Ensure timezone data is available and default to UTC inside the container
ENV TZ=UTC

# Install common dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    software-properties-common \
    locales \
    tzdata \
    wget \
    curl \
    unzip \
    python3 \
    python3-pip \
    python3-venv \
    libfreetype6 \
    fuse3 \
    squashfuse \
    && rm -rf /var/lib/apt/lists/* && \
    echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen

# Set locale
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# --- ARM64 SPECIFIC SETUP (FEX-Emu) ---
# We install FEX and the RootFS here.
# NOTE: We DO NOT run FEXBash here to install Wine, because running FEX inside QEMU (during Docker build)
# causes 'Illegal instruction' crashes due to nested emulation issues.
# Wine installation is deferred to runtime in start_server.sh.
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      echo "Detected ARM64 build. Installing FEX-Emu..." && \
      add-apt-repository -y ppa:fex-emu/fex && \
      apt-get update && \
      apt-get install -y --no-install-recommends fex-emu-armv8.2 squashfs-tools && \
      rm -rf /var/lib/apt/lists/* && \
      mkdir -p /home/gameserver/.fex-emu/RootFS && \
      # Switch to Ubuntu 22.04 RootFS for better stability
      wget -q -O /home/gameserver/.fex-emu/RootFS/Ubuntu_22_04.sqsh https://rootfs.fex-emu.gg/Ubuntu_22_04/2025-01-08/Ubuntu_22_04.sqsh && \
      cd /home/gameserver/.fex-emu/RootFS && \
      unsquashfs -f -d Ubuntu_22_04_Extracted Ubuntu_22_04.sqsh && \
      rm Ubuntu_22_04.sqsh && \
      mv Ubuntu_22_04_Extracted Ubuntu_22_04 && \
      mkdir -p /root/.fex-emu/RootFS && \
      ln -s /home/gameserver/.fex-emu/RootFS/Ubuntu_22_04 /root/.fex-emu/RootFS/Ubuntu_22_04 && \
      rm -rf /root/.fex-emu; \
    fi

# --- AMD64 SPECIFIC SETUP ---
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      echo "Detected AMD64 build. Installing 32-bit libs..." && \
      dpkg --add-architecture i386 && \
      apt-get update && \
      apt-get install -y --no-install-recommends \
        libc6-dev \
        libstdc++6:i386 \
        lib32z1 \
        libgcc-s1:i386 \
        libfreetype6:i386 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Create gameserver user
RUN groupadd -g 25000 gameserver && \
    useradd -u 25000 -g gameserver -m -d /home/gameserver gameserver

# Ensure FEX RootFS permissions
# This is done once at build time to avoid slow startup
RUN if [ -d "/home/gameserver/.fex-emu" ]; then \
      chown -R gameserver:gameserver /home/gameserver/.fex-emu; \
    fi

# Create necessary directories
RUN mkdir -p \
    /home/gameserver/Steam \
    /home/gameserver/steamcmd \
    /home/gameserver/server-files \
    /home/gameserver/cluster-shared && \
    chown -R gameserver:gameserver /home/gameserver

# Copy Python application
COPY asa_ctrl /usr/share/asa_ctrl

# Install Python app
RUN python3 -m venv /opt/asa_env && \
    /opt/asa_env/bin/pip install --no-cache-dir --upgrade pip

COPY pyproject.toml /usr/share/
RUN /opt/asa_env/bin/pip install /usr/share/

# Create launcher script
RUN echo '#!/bin/bash' > /usr/local/bin/asa-ctrl && \
    echo 'exec /opt/asa_env/bin/asa-ctrl "$@"' >> /usr/local/bin/asa-ctrl && \
    chmod +x /usr/local/bin/asa-ctrl

# Copy server management script
COPY scripts/start_server.sh /usr/bin/start_server.sh
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

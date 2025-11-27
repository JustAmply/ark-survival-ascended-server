# Multi-arch Dockerfile for ARK: Survival Ascended
# Supports amd64 (Intel/AMD) and arm64 (Apple Silicon / Ampere) via FEX-Emu

# --- Stage 1: FEX RootFS Builder (AMD64) ---
# We build a custom Ubuntu 22.04 image (AMD64) to serve as the RootFS for FEX.
# By building this as a standard Docker stage, we avoid all the complexity and fragility
# of manually downloading, extracting, and chrooting into a RootFS image.
# We install Wine here natively.
FROM --platform=linux/amd64 ubuntu:22.04 AS fex-rootfs

ENV DEBIAN_FRONTEND=noninteractive

# Install Wine and 32-bit support
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    file \
    ca-certificates \
    software-properties-common \
    && mkdir -p /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # Copy Wine files to /usr to avoid symlink resolution issues under FEX
    # We use --remove-destination to overwrite any symlinks created by the package
    && cp -r --remove-destination /opt/wine-stable/bin/* /usr/bin/ \
    && cp -r --remove-destination /opt/wine-stable/lib/* /usr/lib/ \
    && cp -r --remove-destination /opt/wine-stable/share/* /usr/share/ \
    # wine64 binary is missing in some packages, so we alias wine to wine64
    && ln -sf /usr/bin/wine /usr/bin/wine64 \
    # Legacy symlinks for FEX compatibility
    && ln -sf /usr/lib/x86_64-linux-gnu /x86_64-linux-gnu \
    && ln -sf /usr/lib/i386-linux-gnu /i386-linux-gnu

# --- Stage 2: Final Image ---
FROM ubuntu:24.04

# Build arguments
ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

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
    xz-utils \
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
# We install FEX.
RUN if [ "$TARGETARCH" = "arm64" ]; then \
    echo "Detected ARM64 build. Installing FEX-Emu..." && \
    add-apt-repository -y ppa:fex-emu/fex && \
    apt-get update && \
    apt-get install -y --no-install-recommends fex-emu-armv8.2 && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /home/gameserver/.fex-emu/RootFS && \
    # Create Config.json to point FEX to the correct RootFS automatically
    echo '{"Config": {"RootFS": "Ubuntu_22_04"}}' > /home/gameserver/.fex-emu/Config.json; \
    fi

# Copy pre-built RootFS from the builder stage (AMD64 Ubuntu 22.04 with Wine)
# We copy the ENTIRE filesystem of the fex-rootfs stage into the directory.
COPY --from=fex-rootfs --chown=25000:25000 / /home/gameserver/.fex-emu/RootFS/Ubuntu_22_04

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
    && rm -rf /var/lib/apt/lists/* && \
    # Clean up the FEX rootfs on AMD64 to save runtime disk usage
    rm -rf /home/gameserver/.fex-emu; \
    fi

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

# Build arguments for metadata (placed at end to avoid cache invalidation)
ARG VERSION="unknown"
ARG GIT_COMMIT="unknown"
ARG BUILD_DATE="unknown"

# Add metadata labels
LABEL org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.revision="${GIT_COMMIT}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.title="ARK: Survival Ascended Linux Server" \
    org.opencontainers.image.description="Dockerized ARK: Survival Ascended server with asa_ctrl management tool (Multi-arch)" \
    org.opencontainers.image.source="https://github.com/JustAmply/ark-survival-ascended-server"

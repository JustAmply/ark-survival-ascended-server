# Multi-arch Dockerfile for ARK: Survival Ascended
# Supports amd64 (Intel/AMD) and arm64 (Apple Silicon / Ampere) via FEX-Emu

# --- Stage 1: RootFS Builder (AMD64) ---
# We use a native AMD64 builder to prepare the FEX RootFS.
# This allows us to install Wine and dependencies into the RootFS using native 'chroot' and 'apt',
# avoiding the "nested emulation" crashes (QEMU -> FEX) and filesystem instability (FEX -> OverlayFS)
# that occur when trying to do this during an ARM64 build or at runtime.
FROM --platform=linux/amd64 ubuntu:24.04 AS rootfs-builder

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    wget \
    squashfs-tools \
    ca-certificates \
    # wine dependencies for verification?
    && rm -rf /var/lib/apt/lists/*

# Setup work directory
WORKDIR /build

# Download Ubuntu 22.04 RootFS (Stable for FEX)
RUN wget -q -O Ubuntu_22_04.sqsh https://rootfs.fex-emu.gg/Ubuntu_22_04/2025-01-08/Ubuntu_22_04.sqsh

# Extract RootFS
RUN unsquashfs -f -d rootfs Ubuntu_22_04.sqsh

# Prepare for chroot (copy DNS settings)
RUN cp /etc/resolv.conf rootfs/etc/resolv.conf

# Install Wine and 32-bit support inside the RootFS via chroot
# We enable multiarch, update, and install wine.
# Note: We treat the rootfs as a directory.
RUN chroot rootfs /bin/bash -c "dpkg --add-architecture i386 && apt-get update && apt-get install -y wine wine32 wine64 libwine:i386 && apt-get clean && rm -rf /var/lib/apt/lists/*"

# Remove resolv.conf copy to be clean
RUN rm rootfs/etc/resolv.conf

# --- Stage 2: Final Image ---
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
# We install FEX.
# The RootFS (with Wine pre-installed) is copied from the builder stage.
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      echo "Detected ARM64 build. Installing FEX-Emu..." && \
      add-apt-repository -y ppa:fex-emu/fex && \
      apt-get update && \
      apt-get install -y --no-install-recommends fex-emu-armv8.2 squashfs-tools && \
      rm -rf /var/lib/apt/lists/* && \
      mkdir -p /home/gameserver/.fex-emu/RootFS; \
    fi

# Copy pre-built RootFS from the builder stage
# This adds ~500MB-1GB to the image layer.
# We put it in a temporary location first to allow conditional move/delete if desired,
# or just copy it directly. For simplicity and robustness, we copy it.
# If we are on AMD64, this is technically wasted space, but ensures the layer logic is simple.
COPY --from=rootfs-builder /build/rootfs /home/gameserver/.fex-emu/RootFS/Ubuntu_22_04

# Fix permissions for the copied RootFS (Builder created it as root)
RUN chown -R 25000:25000 /home/gameserver/.fex-emu

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
      # Clean up the FEX rootfs on AMD64 to save space in the final flattened image (if users use --squash or similar)
      # Note: Standard Docker layers will still persist the size, but runtime disk usage will be lower.
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

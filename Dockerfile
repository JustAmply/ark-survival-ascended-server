# Dockerfile for ARK: Survival Ascended Server (Python-based)
FROM opensuse/leap:15.6

# Set environment variables
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Install required packages
RUN zypper --non-interactive refresh && \
    zypper --non-interactive install \
    curl \
    wget \
    tar \
    gzip \
    unzip \
    python3 \
    python3-pip \
    glibc-locale-base \
    glibc-devel \
    libstdc++6-32bit \
    glib2-32bit \
    && zypper clean --all

# Create gameserver user
RUN groupadd -g 25000 gameserver && \
    useradd -u 25000 -g gameserver -m -d /home/gameserver gameserver

# Create necessary directories
RUN mkdir -p /home/gameserver/{Steam,steamcmd,server-files,cluster-shared} && \
    chown -R gameserver:gameserver /home/gameserver

# Copy Python application
COPY asa_ctrl /usr/share/asa-ctrl
COPY setup.py requirements.txt /usr/share/
COPY cli-asa-mods /usr/bin/cli-asa-mods

# Install Python application
WORKDIR /usr/share
RUN python3 -m pip install -e .

# Create asa-ctrl symlink
RUN ln -s /usr/bin/asa-ctrl /usr/bin/asa-ctrl

# Copy server start script (will be updated to use Python paths)
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
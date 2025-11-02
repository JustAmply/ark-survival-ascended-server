# ARM64 Testing Guide

This guide explains how to test and validate ARM64 compatibility.

## Prerequisites

- ARM64 hardware (Oracle Cloud Ampere A1, Raspberry Pi 4/5, or ARM server)
- Ubuntu 24.04 ARM64 or Debian 12 ARM64
- Docker and Docker Compose installed
- At least 16GB RAM (24GB recommended for Oracle Cloud)

## Quick Test

### 1. Build the ARM64 Image Locally

```bash
# On an ARM64 machine
git clone https://github.com/JustAmply/ark-survival-ascended-server.git
cd ark-survival-ascended-server
docker build -t asa-linux-server:arm64-test .
```

Expected: Build completes successfully with Box64 compilation (takes ~5-10 minutes).

### 2. Run Container Test

```bash
# Start container in debug mode
docker run --rm -e ENABLE_DEBUG=1 asa-linux-server:arm64-test &
CONTAINER_ID=$(docker ps -q -n 1)

# Wait for container to be ready
sleep 5

# Run compatibility tests
docker exec $CONTAINER_ID /bin/bash /usr/share/tests/test_arm64_compat.sh

# Stop debug container
docker stop $CONTAINER_ID
```

Expected output:
```
=== ARM64 Compatibility Test ===

Test 1: Architecture Detection
  Detected architecture: aarch64
  ✓ ARM64 architecture detected

Test 2: Box64 Availability
  ✓ Box64 is installed
  Box64 version: Box64 v0.x.x ...

Test 3: Directory Structure
  ✓ /home/gameserver/Steam exists
  ✓ /home/gameserver/steamcmd exists
  ✓ /home/gameserver/server-files exists
  ✓ /home/gameserver/cluster-shared exists

Test 4: asa_ctrl CLI
  ✓ asa-ctrl command is available
  ✓ asa-ctrl executes successfully

Test 5: Start Script
  ✓ start_server.sh is executable

Test 6: Start Script Architecture Functions
  ✓ Architecture detection function works
  Detected: ARCH=arm64, USE_BOX64=1

=== All Tests Passed ===
```

### 3. Full Server Test

```bash
# Download docker-compose.yml
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.yml

# Start server
docker compose up -d

# Monitor logs (first startup takes 15-20 minutes on ARM64)
docker logs -f asa-server-1
```

Look for these key log messages:
- `[asa-start] ARM64 architecture detected - using Box64 for x86_64 emulation`
- `[asa-start] Box64 environment configured for performance`
- `[asa-start] Installing steamcmd...` (Box64 wrapping SteamCMD)
- `[asa-start] Updating / validating ASA server files...`
- `[asa-start] Starting ASA dedicated server...`

## Oracle Cloud Specific Testing

### Instance Setup
```bash
# On Oracle Cloud Ampere A1 instance
# 1. Create VM.Standard.A1.Flex with:
#    - Shape: 4 OCPUs
#    - Memory: 24 GB
#    - Boot volume: 100 GB minimum
#    - Ubuntu 24.04 ARM64

# 2. Configure firewall
sudo iptables -I INPUT -p udp --dport 7777 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 27020 -j ACCEPT
sudo netfilter-persistent save

# 3. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# 4. Install Docker Compose
sudo apt-get update
sudo apt-get install -y docker-compose-plugin

# 5. Run the server
mkdir asa-server && cd asa-server
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.yml
docker compose up -d
```

### Performance Monitoring

```bash
# Monitor system resources
watch -n 1 'free -h && echo && docker stats --no-stream'

# Check Box64 performance
docker exec asa-server-1 cat /proc/$(docker exec asa-server-1 cat /home/gameserver/.asa-server.pid 2>/dev/null || echo 1)/status 2>/dev/null | grep VmRSS
```

## Expected Performance on Oracle Cloud Free Tier

- **First startup**: 15-20 minutes (Box64 JIT compilation + game download)
- **Subsequent startups**: 5-7 minutes
- **RAM usage**: 10-13 GB during gameplay
- **CPU usage**: 60-80% of 4 OCPUs during peak
- **Player capacity**: Recommended 20-30 players (can handle 50 but may lag)

## Troubleshooting ARM64 Issues

### Box64 Not Found
```bash
docker exec asa-server-1 which box64
# Should output: /usr/bin/box64
```

If missing, rebuild the image.

### SteamCMD Fails on ARM64
```bash
docker exec asa-server-1 box64 /home/gameserver/steamcmd/steamcmd.sh +quit
```

Should exit cleanly. If not, check Box64 installation.

### Performance Issues
```bash
# Check Box64 environment
docker exec asa-server-1 env | grep BOX64

# Should see:
# BOX64_NOBANNER=1
# BOX64_LOG=0
# BOX64_DYNAREC_BIGBLOCK=3
# ... (other optimizations)
```

### Memory Issues
Oracle Cloud free tier has 24GB max. If OOM occurs:
1. Reduce player limit: `-WinLiveMaxPlayers=30`
2. Disable unused features
3. Monitor with `docker stats`

## Comparison: ARM64 vs AMD64

| Metric | AMD64 | ARM64 (Ampere A1) |
|--------|-------|-------------------|
| First startup | 5-10 min | 15-20 min |
| Subsequent startup | 3-5 min | 5-7 min |
| Runtime performance | 100% | ~80-90% |
| RAM usage | 10-12 GB | 11-13 GB |
| CPU overhead | None | Box64 ~10-15% |
| Compatibility | Native | Excellent via Box64 |

## CI/CD Testing

The GitHub Actions workflow automatically builds both AMD64 and ARM64 images.

To test the built images:
```bash
# Pull multi-arch image
docker pull ghcr.io/justamply/asa-linux-server:latest

# Docker automatically pulls the correct architecture
docker run --rm ghcr.io/justamply/asa-linux-server:latest uname -m
```

## Known Limitations

1. **First startup time**: ARM64 requires Box64 JIT warmup (~15-20 min first time)
2. **Performance overhead**: ~10-20% slower than native x86_64
3. **Memory overhead**: Box64 adds ~1-2GB additional RAM usage
4. **Build time**: ARM64 Docker builds take longer due to Box64 compilation
5. **Plugin compatibility**: Some mods/plugins may have issues if they use native x86 code

## Reporting Issues

If you encounter ARM64-specific issues:

1. Include architecture: `uname -m`
2. Include Box64 version: `docker exec <container> box64 --version`
3. Include relevant logs: `docker logs <container> 2>&1 | grep -i box64`
4. Include system info: RAM, CPU count, cloud provider
5. Open an issue at: https://github.com/JustAmply/ark-survival-ascended-server/issues

# ARK: Survival Ascended Server - FAQ & Troubleshooting

This FAQ addresses common issues and questions when running ARK: Survival Ascended dedicated servers with Docker.

## Table of Contents

- [Common Issues](#common-issues)
- [Connection Problems](#connection-problems)
- [Network Configuration](#network-configuration)
- [Server Visibility](#server-visibility)
- [Getting Help](#getting-help)

## Common Issues

### Q: My server is not visible in the server browser

**A:** If you cannot discover your server in the server browser, it's most likely due to at least one of the following reasons:

* **Your server is still booting up** - Give it ~5 minutes after you see "Starting the ARK: Survival Ascended dedicated server..." in the logs
* **You are not looking at the "Unofficial" server browser list** - Make sure you're searching in the correct section
* **Your filter settings exclude your server** - Check your server browser filters and clear them if necessary
* **You forgot to enable "Show player server settings"** - By default, only Nitrado servers are shown to players when searching for unofficial servers. You need to check the "Show player server settings" option ([view screenshot](https://raw.githubusercontent.com/justamply/ark-survival-ascended-linux-container-image/main/assets/show-player-servers.jpg))

### Q: How do I find my server name?

**A:** The server name is randomly generated on first start. To find it, run:

```bash
docker exec asa-server-1 cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName
```

This will output something like `SessionName=ARK #334850`. Search for the number part (e.g., `334850`) in the "Unofficial" server browser.

### Q: The command to find server name fails with "No such file or directory"

**A:** This means the server is still starting up and the configuration file hasn't been created yet. Wait a few more minutes and try the command again.

### Q: My server shows high CPU usage on Ubuntu 22.04

**A:** Ubuntu 22.04.x LTS (Jammy Jellyfish) is currently **NOT WORKING**. As of March 28th 2025, a recent distro update causes the container to have constant high CPU usage (well beyond 400%) and the server won't launch. **Use Ubuntu 24.04.x instead**.

### Q: How do I check if my server is updated?

**A:** Updates are automatically applied when you restart the container:

```bash
docker restart asa-server-1
```

It's possible that after an update, the client is still one or more versions ahead. This happens because Wildcard sometimes releases client-only updates. As long as you can connect to your server, everything is fine.

You can check when the latest server update was published by checking [this SteamDB link](https://steamdb.info/app/2430930/depots/) and looking at the `public` branch update timestamp.

## Connection Problems

### Q: I get "Connection Timeout" errors when trying to connect

**A:** First, try connecting through the in-game console instead of the server browser:

1. Open the console in ARK (usually Tab key)
2. Type: `open YOUR_SERVER_IP:7777` (replace with your actual IP and port)
3. Press Enter

If this works but the server browser doesn't, continue reading the network configuration section below.

If neither method works and you're running a home setup (not a VPS), ensure your ports are properly forwarded on your router:
- **7777/UDP** - Game port (required)
- **27020/TCP** - RCON port (optional)

### Q: My server has multiple IP addresses and players can't connect

**A:** This is a common issue when your server has multiple network interfaces. The symptoms are:

- Server appears in browser but shows wrong IP
- Connection timeouts when joining
- Console connection (`open IP:PORT`) fails

**Diagnosis:** First, check if this is the issue:

1. Log into the container: `docker exec -ti -u root asa-server-1 bash`
2. Install curl: `apt-get update && apt-get install -y curl`
3. Check external IP: `curl icanhazip.com`
4. Compare with the IP you assigned to ASA in `docker-compose.yml`

If they're different, you need to fix the routing.

## Network Configuration

### Q: How do I fix routing issues with multiple IP addresses?

**A:** If your server has multiple IPv4 addresses and ASA is bound to a secondary one, you need to customize the routing:

1. **Modify docker-compose.yml** - Add this to the networks section:
   ```yml
   networks:
     asa-network:
       attachable: true
       driver: bridge
       driver_opts:
         com.docker.network.bridge.name: 'asanet'
         com.docker.network.bridge.enable_ip_masquerade: 'false'
   ```

2. **Stop and recreate containers:**
   ```bash
   docker stop asa-server-1
   docker rm asa-server-1
   docker network rm asa-server_asa-network
   docker compose up -d
   ```

3. **Find the container subnet:**
   ```bash
   docker network inspect asa-server_asa-network | grep Subnet
   ```

4. **Add iptables rule** (replace `$SUBNET` and `$YOUR_SECONDARY_IP`):
   ```bash
   iptables -t nat -A POSTROUTING -s $SUBNET ! -o asanet -j SNAT --to-source $YOUR_SECONDARY_IP
   ```

5. **Test the fix** by repeating the curl test from the diagnosis step.

### Q: How do I make iptables rules persistent after reboot?

**A:** Save the current iptables state and create a cron job:

1. **Save current rules:**
   ```bash
   iptables-save > /root/iptables
   ```

2. **Add to crontab:**
   ```bash
   crontab -e
   ```
   Add this line:
   ```
   @reboot /bin/bash -c 'sleep 15 ; /usr/sbin/iptables-restore < /root/iptables'
   ```

3. **Test by rebooting** and verifying the curl test still works.

### Q: Which ports do I need to forward on my router?

**A:** For home setups behind a router, forward these ports:

- **7777/UDP** - Game port (required for players to connect)
- **27020/TCP** - RCON port (optional, only needed for remote administration)

**Note:** ASA no longer offers server querying, so there's no query port needed. You cannot find ASA servers through the Steam server browser, only the in-game browser.

## Server Visibility

### Q: Why can't I find my server in Steam's server browser?

**A:** ASA servers do not appear in Steam's server browser. You can only find them through the in-game "Unofficial" server browser in ARK: Survival Ascended.

### Q: My server appears but shows the wrong IP address

**A:** This is typically caused by multiple network interfaces. See the "Network Configuration" section above for the solution.

### Q: Do I need to configure a query port?

**A:** No. ASA no longer supports server querying, so there's no query port to configure. This is different from older ARK versions.

## Getting Help

### Q: How do I enable debug mode for troubleshooting?

**A:** Enable debug mode by changing `ENABLE_DEBUG=0` to `ENABLE_DEBUG=1` in your `docker-compose.yml`:

```yml
environment:
  - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50
  - ENABLE_DEBUG=1
```

Then restart: `docker compose up -d`

In debug mode, the container starts without launching the server. You can access it with:
```bash
docker exec -ti asa-server-1 bash          # Regular access
docker exec -ti -u root asa-server-1 bash  # Root access
```

### Q: How do I check server logs?

**A:** View real-time logs with:
```bash
docker logs -f asa-server-1
```

Press `Ctrl+C` to exit the log view (this won't stop the server).

### Q: Where do I report bugs or get additional help?

**A:** For issues not covered in this FAQ:

1. **Check existing issues** on the [GitHub repository](https://github.com/justamply/ark-survival-ascended-linux-container-image/issues)
2. **Create a new issue** if your problem isn't already reported
3. **Include relevant information**:
   - Your OS and version
   - Docker version
   - Container logs (`docker logs asa-server-1`)
   - Your `docker-compose.yml` configuration (remove passwords!)
   - Steps to reproduce the issue

### Q: How do I check if Docker is working properly?

**A:** Run these basic Docker tests:

```bash
# Check Docker version
docker --version

# Check if Docker daemon is running
systemctl status docker

# Test Docker with hello-world
docker run hello-world

# Check if Docker Compose is installed
docker compose version
```

### Q: My container keeps crashing on startup

**A:** Check the logs for specific error messages:

```bash
docker logs asa-server-1
```

Common causes:
- Insufficient disk space (need ~31GB)
- Insufficient RAM (need ~13GB)
- Port conflicts (7777 or 27020 already in use)
- Invalid configuration in `docker-compose.yml`
- Corrupted download files (try `docker pull justamply/asa-linux-server:latest`)

### Q: How do I completely start over?

**A:** If you need to completely reset your server:

```bash
# Stop the container
docker stop asa-server-1

# Remove container and volumes (THIS DELETES ALL SERVER DATA!)
docker rm asa-server-1
docker volume rm asa-server_server-files-1 asa-server_steam-1 asa-server_steamcmd-1 asa-server_cluster-shared

# Remove the network
docker network rm asa-server_asa-network

# Start fresh
docker compose up -d
```

**Warning:** This deletes all server files, saves, and configuration!
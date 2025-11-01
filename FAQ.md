# ❓ ARK: Survival Ascended Server FAQ

Quick answers to the most common questions and issues! Get your server running smoothly with these solutions.

## 🔍 Server Visibility Issues

### **Q: I can't find my server in the browser!**

**A:** This is the #1 most common issue. Here's your checklist:

1. **✅ Wait for startup** - Give it 5-10 minutes after seeing "Starting the ARK server..." in logs
2. **✅ Search "Unofficial"** - Your server appears in the "Unofficial" section, not "Official"
3. **✅ Enable player servers** - Check "Show player server settings" in the filter options
4. **✅ Clear filters** - Remove any map, player count, or other filters
5. **✅ Search by number** - Find your server number and search for it specifically

### **Q: How do I find my server's name/number?**

**A:** Run this command:
```bash
docker exec asa-server-1 cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName
```

Look for something like `SessionName=ARK #334850` - search for the number part!

### **Q: The command above fails with "No such file"**

**A:** Your server is still starting up! The config file gets created during startup. Wait a few more minutes and try again.

## 🌐 Connection Problems

### **Q: I get "Connection Timeout" when joining**

**A:** Try these solutions in order:

1. **Direct connect**: Open console in ARK (Tab key) and type `open YOUR_IP:7777`
2. **Check ports**: Make sure port 7777/UDP is forwarded in your router
3. **Wait longer**: Sometimes it takes up to 10 minutes on first startup
4. **Restart server**: `docker restart asa-server-1`

### **Q: My server shows the wrong IP address**

**A:** This happens with multiple network interfaces. The quick fix:

1. Check your actual public IP: `curl icanhazip.com`
2. If it doesn't match what shows in the server browser, you have a routing issue
3. See our [advanced networking guide](SETUP.md#multi-server-clusters) for the full solution

## 🔧 Technical Issues

### **Q: High CPU usage on Ubuntu 22.04**

**A:** **Don't use Ubuntu 22.04!** It has known issues with this container. Switch to Ubuntu 24.04 or Debian 12.

### **Q: Server won't start/keeps crashing**

**A:** Check these common causes:

```bash
# View error logs
docker logs asa-server-1

# Check disk space (need ~31GB)
df -h

# Check RAM (need ~13GB)
free -h

# Test if ports are busy
netstat -tlnp | grep :7777
```

### **Q: Does this work on ARM64 / Oracle Cloud / Raspberry Pi?**

**A:** Yes! ARM64 is fully supported via Box64 emulation:

- **Oracle Cloud Free Tier**: Works great on Ampere A1 instances (4 OCPU, 24GB RAM)
- **Raspberry Pi**: Requires Pi 4/5 with at least 16GB RAM (performance may vary)
- **ARM Cloud Servers**: Any ARM64 Linux server with sufficient resources

**Important notes:**
- First startup takes ~15-20 minutes (Box64 setup + compilation)
- Performance is ~80-90% of equivalent x86_64 hardware
- The image automatically detects ARM64 and configures Box64

### **Q: How do I completely reset my server?**

**A:** ⚠️ **This deletes everything!**

```bash
docker stop asa-server-1
docker rm asa-server-1
docker volume rm asa-server_server-files-1 asa-server_steam-1 asa-server_steamcmd-1 asa-server_cluster-shared
docker compose up -d
```

## 🎮 Gameplay Questions

### **Q: How do I add mods?**

**A:** Super easy with the dynamic method:

```bash
# Enable any mod by ID
docker exec asa-server-1 asa-ctrl mods enable 12345

# Restart to download
docker restart asa-server-1
```

Find mod IDs on the mod's CurseForge page!

### **Q: How do I change the map?**

**A:** Edit `ASA_START_PARAMS` in your `docker-compose.yml`:

- **The Island**: `TheIsland_WP`
- **Scorched Earth**: `ScorchedEarth_WP` 
- **The Center**: `TheCenter_WP`
- **Aberration**: `Aberration_WP`
- **Extinction**: `Extinction_WP`

Then restart: `docker compose up -d`

### **Q: How do I increase player limit?**

**A:** Change `-WinLiveMaxPlayers=50` to your desired number in `ASA_START_PARAMS`, then restart.

### **Q: How do I use admin commands?**

**A:** Use RCON instead of in-game admin:

```bash
# Save world
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'

# Send message
docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Hello everyone!'

# Kick player
docker exec asa-server-1 asa-ctrl rcon --exec 'kickplayer PlayerName'
```

## 🛠️ Troubleshooting Steps

### **Q: My server was working, now it's broken**

**A:** Follow this diagnosis flow:

1. **Check logs**: `docker logs asa-server-1`
2. **Try restart**: `docker restart asa-server-1`
3. **Check updates**: ARK might have updated - restart to download
4. **Check disk space**: `df -h` - servers need lots of space
5. **Check ports**: Something else might be using your ports

### **Q: I can't use RCON commands**

**A:** Make sure RCON is properly configured:

1. **Check your start params** include `?RCONEnabled=True` and `?RCONPort=27020`
2. **Set admin password** in `GameUserSettings.ini`:
   ```ini
   [ServerSettings]
   RCONEnabled=True
   ServerAdminPassword=your_secret_password
   RCONPort=27020
   ```
3. **Restart server** after changes

### **Q: How do I enable debug mode?**

**A:** For advanced troubleshooting:

1. Change `ENABLE_DEBUG=1` in `docker-compose.yml`
2. Run `docker compose up -d`
3. Access container: `docker exec -ti asa-server-1 bash`

## 📖 Still Need Help?

### **Q: None of these solutions worked!**

**A:** We're here to help:

1. **🔍 Search existing issues**: [GitHub Issues](https://github.com/JustAmply/ark-survival-ascended-server/issues)
2. **📝 Create new issue** with these details:
   - Your OS and version
   - Docker version (`docker --version`)
   - Container logs (`docker logs asa-server-1`)
   - Your `docker-compose.yml` (remove passwords!)
   - What you were trying to do when it broke

3. **💬 Join discussions**: [GitHub Discussions](https://github.com/JustAmply/ark-survival-ascended-server/discussions)

### **Q: Is there a Discord/forum?**

**A:** We use GitHub for all support to keep everything searchable and helpful for future users. Please use the links above!

## 🎯 Quick Reference

**Most common fixes:**
- Server not visible → Wait longer, check "Unofficial" browser
- Can't connect → Try direct connect with `open IP:7777`  
- High CPU → Don't use Ubuntu 22.04
- Admin commands → Use RCON, not in-game admin
- Add mods → `docker exec asa-server-1 asa-ctrl mods enable MOD_ID`
- Updates → `docker restart asa-server-1`

**Essential commands:**
```bash
# View logs
docker logs -f asa-server-1

# Restart server
docker restart asa-server-1

# Find server name
docker exec asa-server-1 cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName

# Enable mod
docker exec asa-server-1 asa-ctrl mods enable 12345
```

Happy gaming! 🦕

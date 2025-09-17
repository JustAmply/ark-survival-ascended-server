# 🏢 Enterprise Deployment Guide

This guide covers deploying and configuring the ASA Enterprise server for production environments.

## 📋 Table of Contents

1. [Enterprise Features Overview](#enterprise-features-overview)
2. [System Requirements](#system-requirements)
3. [Production Deployment](#production-deployment)
4. [Security Configuration](#security-configuration)
5. [Monitoring & Alerting](#monitoring--alerting)
6. [Backup & Recovery](#backup--recovery)
7. [API & Web Dashboard](#api--web-dashboard)
8. [High Availability Setup](#high-availability-setup)
9. [Troubleshooting](#troubleshooting)

## 🚀 Enterprise Features Overview

The ASA Enterprise edition provides additional capabilities for production environments:

### 🔧 **Configuration Management**
- Environment-based configuration with validation
- Centralized configuration updates via API
- Configuration versioning and rollback capability
- Runtime configuration changes without restarts

### 🛡️ **Security & Access Control**
- IP-based RCON access control
- Rate limiting for API and RCON requests
- Input validation and command sanitization
- Comprehensive audit logging with security events
- Token-based API authentication

### 📊 **Monitoring & Observability**
- Real-time health checks (disk, memory, processes, config)
- System metrics collection (CPU, memory, load average)
- Application metrics (mod count, server status)
- Structured logging with correlation IDs
- Performance monitoring and alerting

### 🔄 **Backup & Recovery**
- Automated scheduled backups (config, saves, mods, logs)
- Configurable retention policies
- Point-in-time recovery capabilities
- Backup compression and metadata tracking
- Background backup processes

### 🌐 **API & Integration**
- RESTful API with 10+ management endpoints
- Web-based management dashboard
- CORS support for web integrations
- Webhook capabilities for external systems
- Real-time status and metrics access

### 📈 **Enterprise Operations**
- CLI management tools for all enterprise features
- Infrastructure as code templates
- Container orchestration support
- Automated deployment pipelines

## 💻 System Requirements

### **Minimum Requirements (Single Server)**
- **CPU**: 4 cores (Intel/AMD x64)
- **RAM**: 16 GB (13 GB for game server + 3 GB for enterprise features)
- **Storage**: 50 GB SSD (31 GB game files + enterprise data)
- **Network**: 1 Gbps connection
- **OS**: Ubuntu 24.04 LTS or Debian 12

### **Recommended Requirements (Production)**
- **CPU**: 8+ cores (Intel/AMD x64)
- **RAM**: 32 GB (better performance and caching)
- **Storage**: 100+ GB NVMe SSD (game files, backups, logs)
- **Network**: 10 Gbps connection with redundancy
- **OS**: Ubuntu 24.04 LTS with security updates

### **Enterprise Cluster Setup**
- **Load Balancer**: HAProxy or NGINX with SSL termination
- **Database**: PostgreSQL or MySQL for enterprise data
- **Storage**: Shared NFS/GlusterFS for game saves and backups
- **Monitoring**: Prometheus + Grafana stack
- **Logging**: ELK Stack (Elasticsearch, Logstash, Kibana)

## 🚀 Production Deployment

### **1. Docker Compose for Production**

Create a production-ready `docker-compose.yml`:

```yaml
version: '3.8'

services:
  asa-server:
    image: ghcr.io/justamply/asa-linux-server:latest
    container_name: asa-enterprise-server
    restart: unless-stopped
    
    environment:
      # Server Configuration
      - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=100 -clusterid=production
      
      # Enterprise Configuration
      - ASA_LOG_LEVEL=INFO
      - ASA_CONFIG_DIR=/home/gameserver/enterprise-config
      - ASA_AUDIT_LOG_PATH=/home/gameserver/logs/audit.log
      - ASA_METRICS_PATH=/home/gameserver/metrics
      - ASA_BACKUP_DIR=/home/gameserver/backups
      
      # Security Settings
      - ENABLE_DEBUG=0
      - SERVER_RESTART_CRON=0 4 * * *
    
    ports:
      # Game Ports
      - "7777:7777/udp"    # Game traffic
      - "27020:27020/tcp"  # RCON
      
      # Enterprise API (behind reverse proxy in production)
      - "127.0.0.1:8080:8080/tcp"  # API server (local only)
    
    volumes:
      # Game Data
      - steam-data:/home/gameserver/Steam:rw
      - steamcmd-data:/home/gameserver/steamcmd:rw
      - server-files:/home/gameserver/server-files:rw
      
      # Enterprise Data
      - enterprise-config:/home/gameserver/enterprise-config:rw
      - enterprise-logs:/home/gameserver/logs:rw
      - enterprise-metrics:/home/gameserver/metrics:rw
      - enterprise-backups:/home/gameserver/backups:rw
      
      # System
      - /etc/localtime:/etc/localtime:ro
    
    networks:
      - asa-network
    
    healthcheck:
      test: ["CMD", "asa-ctrl", "enterprise", "health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  # Reverse Proxy for API (Production)
  nginx:
    image: nginx:alpine
    container_name: asa-nginx
    restart: unless-stopped
    
    ports:
      - "80:80"
      - "443:443"
    
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    
    networks:
      - asa-network
    
    depends_on:
      - asa-server

volumes:
  steam-data:
  steamcmd-data:
  server-files:
  enterprise-config:
  enterprise-logs:
  enterprise-metrics:
  enterprise-backups:

networks:
  asa-network:
    driver: bridge
```

### **2. NGINX Configuration**

Create `nginx.conf` for production API access:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream asa_api {
        server asa-server:8080;
    }
    
    server {
        listen 80;
        server_name your-server.example.com;
        
        # Redirect HTTP to HTTPS
        return 301 https://$server_name$request_uri;
    }
    
    server {
        listen 443 ssl http2;
        server_name your-server.example.com;
        
        # SSL Configuration
        ssl_certificate /etc/nginx/ssl/server.crt;
        ssl_certificate_key /etc/nginx/ssl/server.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        
        # Security Headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";
        add_header Strict-Transport-Security "max-age=31536000" always;
        
        # API Proxy
        location /api/ {
            proxy_pass http://asa_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Rate Limiting
            limit_req zone=api burst=20 nodelay;
        }
        
        # Dashboard
        location / {
            proxy_pass http://asa_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
    
    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
}
```

## 🔒 Security Configuration

### **1. Enable Enterprise Security**

```bash
# Configure security settings
asa-ctrl enterprise config update --field enable_rcon_rate_limiting --value true
asa-ctrl enterprise config update --field max_rcon_requests_per_minute --value 30
asa-ctrl enterprise config update --field allowed_rcon_ips --value '["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]'

# Enable audit logging
asa-ctrl enterprise config update --field enable_audit_logging --value true

# Set API authentication
asa-ctrl enterprise config update --field api_auth_token --value "$(openssl rand -hex 32)"
```

### **2. Firewall Configuration**

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 7777/udp      # Game port
sudo ufw allow 27020/tcp     # RCON (restrict to admin IPs)
sudo ufw allow 80/tcp        # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp       # HTTPS API access
sudo ufw enable

# Restrict RCON to specific IPs
sudo ufw delete allow 27020/tcp
sudo ufw allow from 192.168.1.0/24 to any port 27020
```

### **3. SSL/TLS Setup**

```bash
# Generate self-signed certificate (development)
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout ssl/server.key \
    -out ssl/server.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=your-server.example.com"

# For production, use Let's Encrypt
sudo certbot --nginx -d your-server.example.com
```

## 📊 Monitoring & Alerting

### **1. Health Check Monitoring**

```bash
# Manual health check
asa-ctrl enterprise health

# Automated monitoring script
#!/bin/bash
HEALTH_OUTPUT=$(asa-ctrl enterprise health 2>&1)
if [ $? -ne 0 ]; then
    echo "ALERT: ASA Server health check failed"
    echo "$HEALTH_OUTPUT"
    # Send to monitoring system (Slack, PagerDuty, etc.)
fi
```

### **2. Prometheus Integration**

Add to `docker-compose.yml`:

```yaml
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana
```

### **3. Log Aggregation**

```bash
# Ship logs to external system
docker run -d --name=log-shipper \
  -v enterprise-logs:/logs:ro \
  fluent/fluent-bit \
  /fluent-bit/bin/fluent-bit \
  -i tail -p path=/logs/audit.log \
  -o es -p host=elasticsearch.example.com
```

## 🔄 Backup & Recovery

### **1. Configure Automated Backups**

```bash
# Enable automatic backups
asa-ctrl enterprise config update --field auto_backup_enabled --value true
asa-ctrl enterprise config update --field backup_interval_hours --value 6
asa-ctrl enterprise config update --field backup_retention_days --value 30

# Manual backup creation
asa-ctrl enterprise backup create --type full --description "Before server update"
asa-ctrl enterprise backup list
```

### **2. Backup to External Storage**

```bash
#!/bin/bash
# sync-backups.sh - Sync backups to external storage

BACKUP_DIR="/home/gameserver/backups"
REMOTE_BACKUP="s3://your-backup-bucket/asa-backups/"

# Sync to AWS S3
aws s3 sync "$BACKUP_DIR" "$REMOTE_BACKUP" --delete

# Or sync to remote server
rsync -av --delete "$BACKUP_DIR/" backup-server:/backups/asa/
```

### **3. Disaster Recovery Process**

```bash
# 1. Stop the server
docker compose down

# 2. Restore from backup
asa-ctrl enterprise backup restore --name backup_20241201_120000 --type all

# 3. Verify restoration
asa-ctrl enterprise health

# 4. Start the server
docker compose up -d
```

## 🌐 API & Web Dashboard

### **1. Enable API Server**

```bash
# Enable API
asa-ctrl enterprise config update --field api_enabled --value true
asa-ctrl enterprise config update --field api_port --value 8080

# Start API server (development)
asa-ctrl enterprise api start

# Check API status
asa-ctrl enterprise api status
```

### **2. API Authentication**

```bash
# Set authentication token
TOKEN=$(openssl rand -hex 32)
asa-ctrl enterprise config update --field api_auth_token --value "$TOKEN"

# Use with curl
curl -H "Authorization: Bearer $TOKEN" \
     https://your-server.example.com/api/v1/status
```

### **3. Web Dashboard Access**

Access the web dashboard at:
- Development: `http://localhost:8080/dashboard`
- Production: `https://your-server.example.com/dashboard`

Features:
- Real-time server status monitoring
- Interactive RCON console
- System health and metrics visualization
- Quick action buttons for common tasks
- Auto-refresh every 30 seconds

## 🏗️ High Availability Setup

### **1. Multi-Server Cluster**

```yaml
# docker-compose.cluster.yml
version: '3.8'

services:
  asa-island:
    image: ghcr.io/justamply/asa-linux-server:latest
    environment:
      - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -clusterid=production
    ports:
      - "7777:7777/udp"
      - "27020:27020/tcp"
    volumes:
      - cluster-shared:/home/gameserver/cluster-shared:rw

  asa-scorched:
    image: ghcr.io/justamply/asa-linux-server:latest
    environment:
      - ASA_START_PARAMS=ScorchedEarth_WP?listen?Port=7778?RCONPort=27021?RCONEnabled=True -clusterid=production
    ports:
      - "7778:7778/udp"
      - "27021:27021/tcp"
    volumes:
      - cluster-shared:/home/gameserver/cluster-shared:rw

  load-balancer:
    image: haproxy:alpine
    ports:
      - "7780:7780/udp"  # Load-balanced game port
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
```

### **2. Database Backend (Optional)**

For enterprise data persistence:

```yaml
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=asa_enterprise
      - POSTGRES_USER=asa
      - POSTGRES_PASSWORD=secure_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

## 🔧 Troubleshooting

### **Common Issues**

**1. API Server Won't Start**
```bash
# Check configuration
asa-ctrl enterprise config show

# Check port availability
netstat -tlnp | grep 8080

# Check logs
docker logs asa-enterprise-server
```

**2. Health Checks Failing**
```bash
# Run detailed health check
asa-ctrl enterprise health

# Check system resources
df -h  # Disk space
free -h  # Memory usage
top  # CPU usage
```

**3. Backup Failures**
```bash
# Check backup directory permissions
ls -la /home/gameserver/backups

# Test backup manually
asa-ctrl enterprise backup create --type config --description "Test backup"

# Check available space
df -h /home/gameserver/backups
```

**4. RCON Connection Issues**
```bash
# Test RCON connectivity
asa-ctrl rcon --exec "listplayers"

# Check security settings
asa-ctrl enterprise security check-access --ip YOUR_IP

# Verify firewall rules
sudo ufw status
```

### **Performance Optimization**

**1. Memory Optimization**
```bash
# Increase memory limits
echo 'vm.swappiness=1' >> /etc/sysctl.conf
echo 'vm.dirty_ratio=5' >> /etc/sysctl.conf
sysctl -p
```

**2. Network Optimization**
```bash
# Increase network buffers
echo 'net.core.rmem_max = 16777216' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 16777216' >> /etc/sysctl.conf
sysctl -p
```

**3. Storage Optimization**
```bash
# Use faster I/O scheduler for SSDs
echo noop > /sys/block/sda/queue/scheduler

# Mount with optimized options
# Add to /etc/fstab: noatime,discard for SSD volumes
```

## 📞 Support & Maintenance

### **Regular Maintenance Tasks**

**Daily:**
- Monitor health check status
- Review audit logs for security events
- Check backup completion

**Weekly:**
- Update server software
- Review and cleanup old backups
- Performance analysis

**Monthly:**
- Security patch updates
- Configuration review
- Disaster recovery testing

### **Monitoring Dashboards**

Create monitoring dashboards with:
- Server uptime and performance metrics
- Player count and activity graphs
- Resource utilization (CPU, memory, disk)
- API request rates and errors
- Backup success/failure rates

### **Alert Thresholds**

Recommended alert thresholds:
- Memory usage > 90%
- Disk space < 10% free
- Health check failures
- RCON authentication failures
- API error rate > 5%
- Backup failures

---

**Need Help?** Check the [FAQ](FAQ.md) or open an issue on GitHub for support.
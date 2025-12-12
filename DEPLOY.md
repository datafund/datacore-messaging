# Deploying Datacore Messaging Relay

The relay server is a simple Python WebSocket server. Deploy it anywhere.

**Recommended: Use the Docker setup in `relay/` folder.**

## Docker Deploy (Recommended)

```bash
cd relay/
echo "RELAY_SECRET=your-team-secret" > .env
docker-compose up -d --build
```

See `relay/README.md` for full instructions including nginx/SSL setup.

---

## Manual Deploy (Alternative)

Only one file needed: `lib/datacore-msg-relay.py`

Requirements:
- Python 3.8+
- aiohttp

## Quick Deploy (Any Linux Server)

### 1. Copy relay to server

```bash
# On your local machine
scp lib/datacore-msg-relay.py user@datacore-relay.datafund.io:~/

# Or clone the whole repo
ssh user@datacore-relay.datafund.io
git clone https://github.com/datafund/datacore-messaging.git
cd datacore-messaging
```

### 2. Install dependencies

```bash
pip3 install aiohttp
```

### 3. Set secret and run

```bash
# Generate a secret (share with team)
export RELAY_SECRET=$(openssl rand -hex 16)
echo "Share this secret with your team: $RELAY_SECRET"

# Run relay
python3 lib/datacore-msg-relay.py
```

### 4. Run as systemd service (recommended)

Create `/etc/systemd/system/datacore-relay.service`:

```ini
[Unit]
Description=Datacore Messaging Relay
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/datacore-messaging
Environment=RELAY_SECRET=your-secret-here
Environment=PORT=8080
ExecStart=/usr/bin/python3 lib/datacore-msg-relay.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable datacore-relay
sudo systemctl start datacore-relay
sudo systemctl status datacore-relay
```

### 5. Set up nginx reverse proxy (for wss://)

Create `/etc/nginx/sites-available/datacore-relay`:

```nginx
server {
    listen 80;
    server_name datacore-relay.datafund.io;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name datacore-relay.datafund.io;

    ssl_certificate /etc/letsencrypt/live/datacore-relay.datafund.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/datacore-relay.datafund.io/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;  # WebSocket timeout (24h)
    }

    location /status {
        proxy_pass http://127.0.0.1:8080/status;
    }
}
```

Enable and get SSL:
```bash
sudo ln -s /etc/nginx/sites-available/datacore-relay /etc/nginx/sites-enabled/
sudo certbot --nginx -d datacore-relay.datafund.io
sudo systemctl reload nginx
```

### 6. Test

```bash
# Check status
curl https://datacore-relay.datafund.io/status

# Should return:
# {"status": "ok", "users_online": 0, "users": []}
```

## Client Configuration

Once deployed, team members configure `settings.local.yaml`:

```yaml
messaging:
  relay:
    secret: "your-shared-secret"
    url: "wss://datacore-relay.datafund.io/ws"
```

## Docker Deploy (Alternative)

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install aiohttp
COPY lib/datacore-msg-relay.py .
ENV PORT=8080
EXPOSE 8080
CMD ["python", "datacore-msg-relay.py"]
```

Run:
```bash
docker build -t datacore-relay .
docker run -d -p 8080:8080 -e RELAY_SECRET=your-secret datacore-relay
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_SECRET` | (required) | Shared secret for authentication |
| `PORT` | 8080 | Server port |

## Security Notes

- All team members use the same `RELAY_SECRET`
- Use HTTPS/WSS in production (nginx + Let's Encrypt)
- The relay only routes messages, doesn't store them
- Messages are also stored locally in org files

## Monitoring

Check relay status:
```bash
curl https://datacore-relay.datafund.io/status
```

View logs (systemd):
```bash
sudo journalctl -u datacore-relay -f
```

## Firewall

Open port 8080 (or 443 if using nginx):
```bash
sudo ufw allow 8080/tcp
# Or for nginx:
sudo ufw allow 'Nginx Full'
```

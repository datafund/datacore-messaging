# Deploying Datacore Messaging Relay

The relay server is a simple Python WebSocket server. Deploy it anywhere.

## Protocol Options

| Protocol | Use Case | SSL Required |
|----------|----------|--------------|
| `ws://` | LAN, internal servers, testing | No |
| `wss://` | Public internet, production | Yes (nginx + certbot) |

**Recommended: Use the Docker setup in `relay/` folder.**

## Docker Deploy (Recommended)

```bash
cd relay/
echo "RELAY_SECRET=your-team-secret" > .env
docker-compose up -d --build
```

This runs the relay on port 8080. Clients connect with `ws://your-server:8080/ws`.

For `wss://` (SSL), see `relay/README.md` for nginx reverse proxy setup.

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

### 5. Test (ws:// - no SSL)

At this point the relay is running. Test it:

```bash
# Check status
curl http://your-server:8080/status

# Should return:
# {"status": "ok", "users_online": 0, "users": []}
```

Clients connect with `ws://your-server:8080/ws`.

### 6. (Optional) Add SSL for wss://

If you need `wss://` for public internet access, set up nginx reverse proxy:

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

Test with SSL:
```bash
curl https://datacore-relay.datafund.io/status
```

Clients now connect with `wss://datacore-relay.datafund.io/ws`.

## Client Configuration

Once deployed, team members configure `settings.local.yaml`:

```yaml
messaging:
  relay:
    secret: "your-shared-secret"
    # Use ws:// for LAN/internal, wss:// for public with SSL
    url: "ws://your-server:8080/ws"            # No SSL
    # url: "wss://relay.example.com/ws"        # With SSL
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

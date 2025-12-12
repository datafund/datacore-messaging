# Datacore Messaging Relay - Docker

WebSocket relay server for real-time team messaging.

## Quick Start

```bash
# 1. Generate a secret (share with your team)
export RELAY_SECRET=$(openssl rand -hex 16)
echo "Team secret: $RELAY_SECRET"

# 2. Run with docker-compose
docker-compose up -d

# 3. Check status
curl http://localhost:8080/status
```

## Deploy to Server

### On datacore-messaging-relay.datafund.io:

```bash
# Clone or copy relay folder
git clone https://github.com/datafund/datacore-messaging.git
cd datacore-messaging/relay

# Create .env file with secret
echo "RELAY_SECRET=your-team-secret-here" > .env

# Build and run
docker-compose up -d --build

# Check logs
docker-compose logs -f
```

### Set up nginx reverse proxy (for wss://):

```nginx
server {
    listen 80;
    server_name datacore-messaging-relay.datafund.io;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name datacore-messaging-relay.datafund.io;

    ssl_certificate /etc/letsencrypt/live/datacore-messaging-relay.datafund.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/datacore-messaging-relay.datafund.io/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }
}
```

Get SSL certificate:
```bash
sudo certbot --nginx -d datacore-messaging-relay.datafund.io
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `RELAY_SECRET` | Yes | Shared secret for team authentication |
| `PORT` | No | Server port (default: 8080) |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Status (JSON) |
| `GET /status` | Status (JSON) |
| `GET /ws` | WebSocket connection |

## Test Connection

```bash
# HTTP status
curl https://datacore-messaging-relay.datafund.io/status

# WebSocket test (requires wscat)
npm install -g wscat
wscat -c wss://datacore-messaging-relay.datafund.io/ws
> {"type":"auth","secret":"your-secret","username":"test"}
```

## Client Configuration

Team members add to their `settings.local.yaml`:

```yaml
messaging:
  relay:
    secret: "your-team-secret"
    url: "wss://datacore-messaging-relay.datafund.io/ws"
```

## Monitoring

```bash
# View logs
docker-compose logs -f

# Check container status
docker-compose ps

# Restart
docker-compose restart

# Stop
docker-compose down
```

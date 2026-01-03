# JIRA Demo Deployment Guide

This guide walks through deploying the JIRA Assistant Skills demo to DigitalOcean.

## Prerequisites

- DigitalOcean account
- Domain name (optional, for SSL)
- JIRA Cloud credentials
- Claude OAuth credentials

## Step 1: Create DigitalOcean Droplet

1. Log into [DigitalOcean Console](https://cloud.digitalocean.com)
2. Click **Create** → **Droplets**
3. Configure:
   - **Region**: NYC1 or nearest to your users
   - **Image**: Ubuntu 24.04 (LTS) x64
   - **Size**: Basic, Regular Intel, $24/mo (2 vCPU, 4GB RAM, 80GB SSD)
   - **Authentication**: SSH Key (recommended) or password
   - **Hostname**: jira-demo

4. Click **Create Droplet**
5. Note the IP address

## Step 2: Initial Server Setup

SSH into your droplet:

```bash
ssh root@YOUR_DROPLET_IP
```

Run the setup script:

```bash
# Clone the repo
git clone https://github.com/grandcamel/jira-demo.git /opt/jira-demo
cd /opt/jira-demo

# Run initial setup
./scripts/deploy.sh --setup
```

This installs Docker, Docker Compose, and certbot.

## Step 3: Configure Secrets

### JIRA Credentials

```bash
cd /opt/jira-demo
cp secrets/example.env secrets/.env
nano secrets/.env
```

Fill in:
- `JIRA_API_TOKEN`: Get from https://id.atlassian.com/manage-profile/security/api-tokens
- `JIRA_EMAIL`: Your Atlassian email
- `JIRA_SITE_URL`: e.g., https://yoursite.atlassian.net

### Claude OAuth Credentials

```bash
cp secrets/example.claude.json secrets/.claude.json
nano secrets/.claude.json
```

Get OAuth tokens by running `claude login` on your local machine, then copy from `~/.claude/.credentials.json`.

## Step 4: Deploy

```bash
./scripts/deploy.sh
```

This will:
1. Pull Docker images
2. Build custom containers
3. Start all services
4. Run health checks

## Step 5: SSL Setup (Optional but Recommended)

If you have a domain:

1. Point your domain's A record to the droplet IP
2. Wait for DNS propagation (check with `dig yourdomain.com`)
3. Run SSL setup:

```bash
# Add domain to secrets/.env
echo "DOMAIN=demo.yourdomain.com" >> secrets/.env

# Get SSL certificate
./scripts/deploy.sh --ssl
```

4. Uncomment the HTTPS server block in `nginx/demo.conf`
5. Restart nginx: `docker-compose restart nginx`

## Verification

### Health Check

```bash
./scripts/healthcheck.sh --verbose
```

### Access the Demo

- Landing page: http://YOUR_DROPLET_IP (or https://yourdomain.com)
- API status: http://YOUR_DROPLET_IP/api/status

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f queue-manager
```

## Maintenance

### Update to Latest Version

```bash
./scripts/deploy.sh --update
```

### View Running Containers

```bash
docker ps
```

### Restart Services

```bash
docker-compose restart
```

### Stop Services

```bash
docker-compose down
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker-compose logs queue-manager
```

### JIRA connection fails

Verify credentials:
```bash
source secrets/.env
curl -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" "${JIRA_SITE_URL}/rest/api/3/myself"
```

### Port 80/443 in use

Check what's using the port:
```bash
lsof -i :80
```

### Redis connection issues

Verify Redis is running:
```bash
docker-compose exec redis redis-cli ping
```

## Cost Breakdown

| Item | Monthly Cost |
|------|--------------|
| Droplet (4GB) | $24 |
| Reserved IP (optional) | $4 |
| Backups (optional) | $4.80 |
| **Total** | $24-33 |

## Security Notes

1. **Firewall**: Only ports 80 and 443 should be open
2. **SSH**: Use key-based authentication, disable password auth
3. **Secrets**: Never commit `.env` or `.claude.json` to git
4. **Updates**: Run `apt update && apt upgrade` regularly

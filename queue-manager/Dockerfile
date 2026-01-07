# Queue Manager Dockerfile
FROM node:20-slim

# Install Docker CLI and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd from GitHub releases (not available in Debian bookworm repos)
RUN curl -fsSL -o /usr/local/bin/ttyd \
    https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    && chmod +x /usr/local/bin/ttyd

# Install Python dependencies for cleanup script
RUN pip3 install --break-system-packages --no-cache-dir \
    jira-assistant-skills-lib>=0.2.3 \
    requests

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy application
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:3000/api/health || exit 1

EXPOSE 3000

CMD ["node", "server.js"]

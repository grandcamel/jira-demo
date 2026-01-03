# Queue Manager Dockerfile
FROM node:20-slim

# Install ttyd and Docker CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    ttyd \
    docker.io \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for cleanup script
RUN pip3 install --break-system-packages \
    jira-assistant-skills-lib>=0.1.5 \
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

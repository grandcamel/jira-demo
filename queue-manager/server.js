/**
 * JIRA Demo Queue Manager
 *
 * Manages single-user demo sessions with queue/waitlist functionality.
 *
 * WebSocket Protocol:
 *   Client -> Server:
 *     { type: "join_queue" }
 *     { type: "leave_queue" }
 *     { type: "heartbeat" }
 *
 *   Server -> Client:
 *     { type: "queue_position", position: N, estimated_wait: "X minutes", queue_size: N }
 *     { type: "session_starting", terminal_url: "/terminal" }
 *     { type: "session_active", expires_at: "ISO timestamp" }
 *     { type: "session_warning", minutes_remaining: 5 }
 *     { type: "session_ended", reason: "timeout" | "disconnected" | "error" }
 *     { type: "error", message: "..." }
 */

const express = require('express');
const { WebSocketServer } = require('ws');
const http = require('http');
const Redis = require('ioredis');
const Docker = require('dockerode');
const { v4: uuidv4 } = require('uuid');
const { spawn } = require('child_process');

// Configuration
const PORT = process.env.PORT || 3000;
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const SESSION_TIMEOUT_MINUTES = parseInt(process.env.SESSION_TIMEOUT_MINUTES) || 60;
const MAX_QUEUE_SIZE = parseInt(process.env.MAX_QUEUE_SIZE) || 10;
const AVERAGE_SESSION_MINUTES = 45;
const TTYD_PORT = 7681;

// Initialize services
const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/api/ws' });
const redis = new Redis(REDIS_URL);
const docker = new Docker({ socketPath: '/var/run/docker.sock' });

// State
const clients = new Map(); // ws -> { id, state, joinedAt }
const queue = [];          // Array of client IDs waiting
let activeSession = null;  // { clientId, containerId, startedAt, expiresAt, ttydProcess }

// =============================================================================
// Express Routes
// =============================================================================

app.use(express.json());

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Queue status (public)
app.get('/api/status', (req, res) => {
  res.json({
    queue_size: queue.length,
    session_active: activeSession !== null,
    estimated_wait: queue.length * AVERAGE_SESSION_MINUTES + ' minutes',
    max_queue_size: MAX_QUEUE_SIZE
  });
});

// =============================================================================
// WebSocket Handlers
// =============================================================================

wss.on('connection', (ws) => {
  const clientId = uuidv4();
  clients.set(ws, { id: clientId, state: 'connected', joinedAt: null });

  console.log(`Client connected: ${clientId}`);

  ws.on('message', (data) => {
    try {
      const message = JSON.parse(data);
      console.log("Received message:", message); handleMessage(ws, message);
    } catch (err) {
      sendError(ws, 'Invalid message format');
    }
  });

  ws.on('close', () => {
    handleDisconnect(ws);
  });

  ws.on('error', (err) => {
    console.error(`WebSocket error for ${clientId}:`, err.message);
  });

  // Send initial status
  sendStatus(ws);
});

function handleMessage(ws, message) {
  const client = clients.get(ws);
  if (!client) return;

  switch (message.type) {
    case 'join_queue':
      joinQueue(ws, client);
      break;

    case 'leave_queue':
      leaveQueue(ws, client);
      break;

    case 'heartbeat':
      ws.send(JSON.stringify({ type: 'heartbeat_ack' }));
      break;

    default:
      sendError(ws, `Unknown message type: ${message.type}`);
  }
}

function handleDisconnect(ws) {
  const client = clients.get(ws);
  if (!client) return;

  console.log(`Client disconnected: ${client.id}`);

  // Remove from queue if waiting
  const queueIndex = queue.indexOf(client.id);
  if (queueIndex !== -1) {
    queue.splice(queueIndex, 1);
    broadcastQueueUpdate();
  }

  // End session if active
  if (activeSession && activeSession.clientId === client.id) {
    endSession('disconnected');
  }

  clients.delete(ws);
}

// =============================================================================
// Queue Management
// =============================================================================

function joinQueue(ws, client) {
  // Check if already in queue
  if (queue.includes(client.id)) {
    sendError(ws, 'Already in queue');
    return;
  }

  // Check queue size limit
  if (queue.length >= MAX_QUEUE_SIZE) {
    ws.send(JSON.stringify({
      type: 'queue_full',
      message: 'Queue is full. Please try again later.'
    }));
    return;
  }

  // Add to queue
  queue.push(client.id);
  client.state = 'queued';
  client.joinedAt = new Date();

  console.log(`Client ${client.id} joined queue (position ${queue.length})`);

  // If no active session and first in queue, start immediately
  if (!activeSession && queue[0] === client.id) {
    startSession(ws, client);
  } else {
    sendQueuePosition(ws, client);
  }

  broadcastQueueUpdate();
}

function leaveQueue(ws, client) {
  const queueIndex = queue.indexOf(client.id);
  if (queueIndex !== -1) {
    queue.splice(queueIndex, 1);
    client.state = 'connected';
    console.log(`Client ${client.id} left queue`);

    ws.send(JSON.stringify({ type: 'left_queue' }));
    broadcastQueueUpdate();
  }
}

function sendQueuePosition(ws, client) {
  const position = queue.indexOf(client.id) + 1;
  const estimatedWait = position * AVERAGE_SESSION_MINUTES;

  ws.send(JSON.stringify({
    type: 'queue_position',
    position: position,
    estimated_wait: `${estimatedWait} minutes`,
    queue_size: queue.length
  }));
}

function broadcastQueueUpdate() {
  clients.forEach((client, ws) => {
    if (client.state === 'queued') {
      sendQueuePosition(ws, client);
    }
  });
}

// =============================================================================
// Session Management
// =============================================================================

async function startSession(ws, client) {
  console.log(`Starting session for client ${client.id}`);

  try {
    // Remove from queue
    const queueIndex = queue.indexOf(client.id);
    if (queueIndex !== -1) {
      queue.splice(queueIndex, 1);
    }

    client.state = 'active';

    // Start ttyd with demo container
    const ttydProcess = spawn('ttyd', [
      '--port', String(TTYD_PORT),
      '--interface', '0.0.0.0',
      '--max-clients', '1',
      '--once',
      '--writable',
      'docker', 'run', '--rm', '-it',
      '-e', 'TERM=xterm',
      '-e', `JIRA_API_TOKEN=${process.env.JIRA_API_TOKEN}`,
      '-e', `JIRA_EMAIL=${process.env.JIRA_EMAIL}`,
      '-e', `JIRA_SITE_URL=${process.env.JIRA_SITE_URL}`,
      '-e', `SESSION_TIMEOUT_MINUTES=${SESSION_TIMEOUT_MINUTES}`,
      '-v', '/opt/jira-demo/secrets/.claude.json:/home/devuser/.claude/.credentials.json:ro',
      'jira-demo-container:latest'
    ], {
      stdio: ['pipe', 'pipe', 'pipe']
    });

    const startedAt = new Date();
    const expiresAt = new Date(startedAt.getTime() + SESSION_TIMEOUT_MINUTES * 60 * 1000);

    activeSession = {
      clientId: client.id,
      ttydProcess: ttydProcess,
      startedAt: startedAt,
      expiresAt: expiresAt
    };

    // Handle ttyd exit
    ttydProcess.on('exit', (code) => {
      console.log(`ttyd exited with code ${code}`);
      if (activeSession && activeSession.clientId === client.id) {
        endSession('container_exit');
      }
    });

    // Notify client
    ws.send(JSON.stringify({
      type: 'session_starting',
      terminal_url: '/terminal',
      expires_at: expiresAt.toISOString()
    }));

    // Schedule warning and timeout
    scheduleSessionWarning(ws, client);
    scheduleSessionTimeout(ws, client);

    // Save to Redis for persistence
    await redis.set(`session:${client.id}`, JSON.stringify({
      startedAt: startedAt.toISOString(),
      expiresAt: expiresAt.toISOString()
    }), 'EX', SESSION_TIMEOUT_MINUTES * 60);

    console.log(`Session started for ${client.id}, expires at ${expiresAt.toISOString()}`);

  } catch (err) {
    console.error('Failed to start session:', err);
    sendError(ws, 'Failed to start demo session');
    client.state = 'connected';

    // Try next in queue
    processQueue();
  }
}

function scheduleSessionWarning(ws, client) {
  const warningTime = (SESSION_TIMEOUT_MINUTES - 5) * 60 * 1000;

  setTimeout(() => {
    if (activeSession && activeSession.clientId === client.id) {
      ws.send(JSON.stringify({
        type: 'session_warning',
        minutes_remaining: 5
      }));
    }
  }, warningTime);
}

function scheduleSessionTimeout(ws, client) {
  const timeoutMs = SESSION_TIMEOUT_MINUTES * 60 * 1000;

  setTimeout(() => {
    if (activeSession && activeSession.clientId === client.id) {
      endSession('timeout');
    }
  }, timeoutMs);
}

async function endSession(reason) {
  if (!activeSession) return;

  const clientId = activeSession.clientId;
  console.log(`Ending session for ${clientId}, reason: ${reason}`);

  // Kill ttyd process
  if (activeSession.ttydProcess) {
    try {
      activeSession.ttydProcess.kill('SIGTERM');
    } catch (err) {
      console.error('Error killing ttyd:', err.message);
    }
  }

  // Notify client
  const clientWs = findClientWs(clientId);
  if (clientWs) {
    clientWs.send(JSON.stringify({
      type: 'session_ended',
      reason: reason
    }));

    const client = clients.get(clientWs);
    if (client) {
      client.state = 'connected';
    }
  }

  // Clean up Redis
  await redis.del(`session:${clientId}`);

  // Run JIRA sandbox cleanup
  runSandboxCleanup();

  activeSession = null;

  // Process next in queue
  processQueue();
}

function runSandboxCleanup() {
  console.log('Running JIRA sandbox cleanup...');

  const cleanup = spawn('python', ['/opt/scripts/cleanup_demo_sandbox.py'], {
    env: {
      ...process.env,
      JIRA_API_TOKEN: process.env.JIRA_API_TOKEN,
      JIRA_EMAIL: process.env.JIRA_EMAIL,
      JIRA_SITE_URL: process.env.JIRA_SITE_URL
    }
  });

  cleanup.on('exit', (code) => {
    if (code === 0) {
      console.log('Sandbox cleanup completed successfully');
    } else {
      console.error(`Sandbox cleanup failed with code ${code}`);
    }
  });
}

function processQueue() {
  if (activeSession || queue.length === 0) return;

  const nextClientId = queue[0];
  const nextClientWs = findClientWs(nextClientId);

  if (nextClientWs) {
    const client = clients.get(nextClientWs);
    startSession(nextClientWs, client);
  } else {
    // Client disconnected, remove and try next
    queue.shift();
    processQueue();
  }
}

// =============================================================================
// Helpers
// =============================================================================

function findClientWs(clientId) {
  for (const [ws, client] of clients.entries()) {
    if (client.id === clientId) {
      return ws;
    }
  }
  return null;
}

function sendStatus(ws) {
  ws.send(JSON.stringify({
    type: 'status',
    queue_size: queue.length,
    session_active: activeSession !== null
  }));
}

function sendError(ws, message) {
  ws.send(JSON.stringify({ type: 'error', message }));
}

// =============================================================================
// Startup
// =============================================================================

server.listen(PORT, () => {
  console.log(`Queue manager listening on port ${PORT}`);
  console.log(`Session timeout: ${SESSION_TIMEOUT_MINUTES} minutes`);
  console.log(`Max queue size: ${MAX_QUEUE_SIZE}`);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('Shutting down...');

  if (activeSession) {
    await endSession('shutdown');
  }

  wss.close();
  server.close();
  redis.quit();

  process.exit(0);
});

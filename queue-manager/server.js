/**
 * JIRA Demo Queue Manager
 *
 * Manages single-user demo sessions with queue/waitlist functionality.
 * Supports invite-based access control with detailed session tracking.
 *
 * WebSocket Protocol:
 *   Client -> Server:
 *     { type: "join_queue", inviteToken?: "token" }
 *     { type: "leave_queue" }
 *     { type: "heartbeat" }
 *
 *   Server -> Client:
 *     { type: "queue_position", position: N, estimated_wait: "X minutes", queue_size: N }
 *     { type: "session_starting", terminal_url: "/terminal" }
 *     { type: "session_active", expires_at: "ISO timestamp" }
 *     { type: "session_warning", minutes_remaining: 5 }
 *     { type: "session_ended", reason: "timeout" | "disconnected" | "error" }
 *     { type: "invite_invalid", reason: "not_found" | "expired" | "used" | "revoked", message: "..." }
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
const CLAUDE_CREDENTIALS_PATH = process.env.CLAUDE_CREDENTIALS_PATH || '/opt/jira-demo/secrets/.credentials.json';
const CLAUDE_CONFIG_PATH = process.env.CLAUDE_CONFIG_PATH || '/opt/jira-demo/secrets/.claude.json';

// Initialize services
const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/api/ws' });
const redis = new Redis(REDIS_URL);
const docker = new Docker({ socketPath: '/var/run/docker.sock' });

// State
const clients = new Map(); // ws -> { id, state, joinedAt, ip, userAgent, inviteToken }
const queue = [];          // Array of client IDs waiting
let activeSession = null;  // { clientId, sessionId, startedAt, expiresAt, ttydProcess, inviteToken, ip, userAgent, queueWaitMs, errors }

// Invite audit retention (30 days after expiration)
const AUDIT_RETENTION_DAYS = 30;

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

// Invite validation endpoint (used by nginx auth_request)
app.get('/api/invite/validate', async (req, res) => {
  // Token can come from query param, header, or extracted from X-Original-URI
  let token = req.query.token || req.query.invite || req.headers['x-invite-token'];

  // If no token yet, try to extract from X-Original-URI (used by nginx auth_request)
  if (!token && req.headers['x-original-uri']) {
    const originalUri = req.headers['x-original-uri'];
    const match = originalUri.match(/[?&]invite=([^&]+)/);
    if (match) {
      token = decodeURIComponent(match[1]);
    }
  }

  if (!token) {
    return res.status(401).json({ valid: false, reason: 'missing', message: 'Invite token required' });
  }

  const validation = await validateInvite(token);

  if (validation.valid) {
    res.status(200).json({ valid: true });
  } else {
    res.status(401).json({ valid: false, reason: validation.reason, message: validation.message });
  }
});

// =============================================================================
// WebSocket Handlers
// =============================================================================

wss.on('connection', (ws, req) => {
  const clientId = uuidv4();
  const clientIp = req.headers['x-forwarded-for']?.split(',')[0]?.trim() || req.socket.remoteAddress;
  const userAgent = req.headers['user-agent'] || 'unknown';

  clients.set(ws, {
    id: clientId,
    state: 'connected',
    joinedAt: null,
    ip: clientIp,
    userAgent: userAgent,
    inviteToken: null
  });

  console.log(`Client connected: ${clientId} from ${clientIp}`);

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
      joinQueue(ws, client, message.inviteToken);
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

async function joinQueue(ws, client, inviteToken) {
  // Check if already in queue
  if (queue.includes(client.id)) {
    sendError(ws, 'Already in queue');
    return;
  }

  // Validate invite token if provided
  if (inviteToken) {
    const validation = await validateInvite(inviteToken);
    if (!validation.valid) {
      ws.send(JSON.stringify({
        type: 'invite_invalid',
        reason: validation.reason,
        message: validation.message
      }));
      return;
    }
    client.inviteToken = inviteToken;
    client.inviteData = validation.data;
    console.log(`Client ${client.id} has valid invite: ${inviteToken.slice(0, 8)}...`);
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

// =============================================================================
// Invite Validation
// =============================================================================

async function validateInvite(token) {
  if (!token || token.length < 10) {
    return {
      valid: false,
      reason: 'invalid',
      message: 'This invite link is malformed or invalid.'
    };
  }

  const inviteKey = `invite:${token}`;
  const inviteJson = await redis.get(inviteKey);

  if (!inviteJson) {
    return {
      valid: false,
      reason: 'not_found',
      message: 'This invite link does not exist. Please check the URL or request a new invite.'
    };
  }

  const invite = JSON.parse(inviteJson);

  // Check if revoked
  if (invite.status === 'revoked') {
    return {
      valid: false,
      reason: 'revoked',
      message: 'This invite link has been revoked by an administrator.'
    };
  }

  // Check if already used
  if (invite.status === 'used' || (invite.useCount >= invite.maxUses)) {
    return {
      valid: false,
      reason: 'used',
      message: 'This invite link has already been used. Each invite can only be used once.'
    };
  }

  // Check expiration
  if (new Date(invite.expiresAt) < new Date()) {
    // Update status in Redis
    invite.status = 'expired';
    const ttl = await redis.ttl(inviteKey);
    await redis.set(inviteKey, JSON.stringify(invite), 'EX', ttl > 0 ? ttl : 86400);
    return {
      valid: false,
      reason: 'expired',
      message: 'This invite link has expired. Please request a new invite.'
    };
  }

  return { valid: true, data: invite };
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
      '-v', `${CLAUDE_CREDENTIALS_PATH}:/home/devuser/.claude/.credentials.json:ro`,
      '-v', `${CLAUDE_CONFIG_PATH}:/home/devuser/.claude/.claude.json:ro`,
      'jira-demo-container:latest'
    ], {
      stdio: ['pipe', 'pipe', 'pipe']
    });

    const startedAt = new Date();
    const expiresAt = new Date(startedAt.getTime() + SESSION_TIMEOUT_MINUTES * 60 * 1000);
    const queueWaitMs = client.joinedAt ? (startedAt - client.joinedAt) : 0;

    activeSession = {
      clientId: client.id,
      sessionId: uuidv4(),
      ttydProcess: ttydProcess,
      startedAt: startedAt,
      expiresAt: expiresAt,
      inviteToken: client.inviteToken || null,
      ip: client.ip,
      userAgent: client.userAgent,
      queueWaitMs: queueWaitMs,
      errors: []
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
      sessionId: activeSession.sessionId,
      startedAt: startedAt.toISOString(),
      expiresAt: expiresAt.toISOString(),
      inviteToken: client.inviteToken || null,
      ip: client.ip,
      userAgent: client.userAgent,
      queueWaitMs: queueWaitMs
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
  const endedAt = new Date();
  console.log(`Ending session for ${clientId}, reason: ${reason}`);

  // Kill ttyd process
  if (activeSession.ttydProcess) {
    try {
      activeSession.ttydProcess.kill('SIGTERM');
    } catch (err) {
      console.error('Error killing ttyd:', err.message);
    }
  }

  // Record invite usage if applicable
  if (activeSession.inviteToken) {
    await recordInviteUsage(activeSession, endedAt, reason);
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

async function recordInviteUsage(session, endedAt, endReason) {
  const inviteKey = `invite:${session.inviteToken}`;

  try {
    const inviteJson = await redis.get(inviteKey);
    if (!inviteJson) {
      console.log(`Invite ${session.inviteToken} not found for usage recording`);
      return;
    }

    const invite = JSON.parse(inviteJson);

    // Add session record
    if (!invite.sessions) invite.sessions = [];
    invite.sessions.push({
      sessionId: session.sessionId,
      clientId: session.clientId,
      startedAt: session.startedAt.toISOString(),
      endedAt: endedAt.toISOString(),
      endReason: endReason,
      queueWaitMs: session.queueWaitMs,
      ip: session.ip,
      userAgent: session.userAgent,
      errors: session.errors || []
    });

    // Update usage tracking
    invite.useCount = (invite.useCount || 0) + 1;
    if (invite.useCount >= invite.maxUses) {
      invite.status = 'used';
    }

    // Save with extended TTL (audit retention after expiration)
    const expiresAtMs = new Date(invite.expiresAt).getTime();
    const auditRetentionMs = AUDIT_RETENTION_DAYS * 24 * 60 * 60 * 1000;
    const ttlSeconds = Math.max(
      Math.floor((expiresAtMs - Date.now() + auditRetentionMs) / 1000),
      86400  // At least 1 day
    );

    await redis.set(inviteKey, JSON.stringify(invite), 'EX', ttlSeconds);
    console.log(`Recorded usage for invite ${session.inviteToken.slice(0, 8)}..., status: ${invite.status}`);

  } catch (err) {
    console.error('Error recording invite usage:', err.message);
  }
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

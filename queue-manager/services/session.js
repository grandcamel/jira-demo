/**
 * Session management service.
 *
 * Uses @demo-platform/queue-manager-core for session tokens and env files.
 */

const { spawn } = require('child_process');
const { v4: uuidv4 } = require('uuid');

const {
  generateSessionToken: coreGenerateToken,
  createSessionEnvFile: coreCreateEnvFile
} = require('@demo-platform/queue-manager-core');

const config = require('../config');
const {
  getTracer,
  sessionsStartedCounter,
  sessionsEndedCounter,
  sessionDurationHistogram,
  queueWaitHistogram,
  ttydSpawnHistogram,
  sandboxCleanupHistogram
} = require('../config/metrics');
const state = require('./state');
const { recordInviteUsage } = require('./invite');

/**
 * Generate a session token.
 * @param {string} sessionId - Session ID
 * @returns {string} Session token
 */
function generateSessionToken(sessionId) {
  return coreGenerateToken(sessionId, config.SESSION_SECRET);
}

/**
 * Clear a session token.
 * @param {string} sessionToken - Token to clear
 */
function clearSessionToken(sessionToken) {
  if (sessionToken) {
    state.sessionTokens.delete(sessionToken);
  }
}

/**
 * Find WebSocket for a client ID.
 * @param {string} clientId - Client ID to find
 * @returns {WebSocket|null} WebSocket or null
 */
function findClientWs(clientId) {
  for (const [ws, client] of state.clients.entries()) {
    if (client.id === clientId) {
      return ws;
    }
  }
  return null;
}

/**
 * Create a session environment file with credentials.
 * Uses secure permissions (0600) so only root can read.
 * @param {string} sessionId - Session ID
 * @returns {Object} { containerPath, hostPath, cleanup }
 */
function createSessionEnvFile(sessionId) {
  return coreCreateEnvFile({
    sessionId,
    containerPath: config.SESSION_ENV_CONTAINER_PATH,
    hostPath: config.SESSION_ENV_HOST_PATH,
    credentials: {
      JIRA_API_TOKEN: config.JIRA_API_TOKEN,
      JIRA_EMAIL: config.JIRA_EMAIL,
      JIRA_SITE_URL: config.JIRA_SITE_URL,
      CLAUDE_CODE_OAUTH_TOKEN: config.CLAUDE_CODE_OAUTH_TOKEN,
      ANTHROPIC_API_KEY: config.ANTHROPIC_API_KEY
    }
  });
}

/**
 * Run JIRA sandbox cleanup script.
 */
function runSandboxCleanup() {
  const tracer = getTracer();
  const span = tracer?.startSpan('sandbox.cleanup');
  const startTime = Date.now();

  console.log('Running JIRA sandbox cleanup...');

  // Only pass required environment variables (principle of least privilege)
  const cleanup = spawn('python3', ['/opt/scripts/cleanup_demo_sandbox.py'], {
    env: {
      PATH: process.env.PATH,
      JIRA_API_TOKEN: config.JIRA_API_TOKEN,
      JIRA_EMAIL: config.JIRA_EMAIL,
      JIRA_SITE_URL: config.JIRA_SITE_URL,
      OTEL_EXPORTER_OTLP_ENDPOINT: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || ''
    }
  });

  cleanup.on('exit', (code) => {
    const durationSeconds = (Date.now() - startTime) / 1000;
    sandboxCleanupHistogram?.record(durationSeconds, { success: code === 0 ? 'true' : 'false' });
    span?.setAttribute('sandbox.cleanup_duration_seconds', durationSeconds);
    span?.setAttribute('sandbox.cleanup_success', code === 0);

    if (code === 0) {
      console.log('Sandbox cleanup completed successfully');
    } else {
      console.error(`Sandbox cleanup failed with code ${code}`);
      span?.recordException(new Error(`Cleanup failed with code ${code}`));
    }
    span?.end();
  });
}

/**
 * Start a new session.
 * @param {Object} redis - Redis client
 * @param {WebSocket} ws - WebSocket connection
 * @param {Object} client - Client object
 * @param {Function} processQueue - Queue processing callback
 */
async function startSession(redis, ws, client, processQueue) {
  const tracer = getTracer();
  const span = tracer?.startSpan('session.start', {
    attributes: {
      'session.client_id': client.id,
      'session.invite_token': client.inviteToken ? client.inviteToken.slice(0, 8) : 'none',
    }
  });

  console.log(`Starting session for client ${client.id}`);
  const spawnStartTime = Date.now();
  const sessionId = uuidv4();
  let envFileCleanup = null;

  try {
    // Remove from queue
    const queueIndex = state.queue.indexOf(client.id);
    if (queueIndex !== -1) {
      state.queue.splice(queueIndex, 1);
    }

    client.state = 'active';

    // Create session env file with sensitive credentials
    const envFile = createSessionEnvFile(sessionId);
    envFileCleanup = envFile.cleanup;

    // Start ttyd with demo container
    // Sensitive env vars are passed via --env-file (not visible in ps aux)
    const ttydProcess = spawn('ttyd', [
      '--port', String(config.TTYD_PORT),
      '--interface', '0.0.0.0',
      '--max-clients', '1',
      '--once',
      '--writable',
      '--client-option', 'reconnect=0',
      'docker', 'run', '--rm', '-it',
      '--network', 'demo-telemetry-network',
      // Security constraints for spawned containers
      '--memory', '2g',
      '--memory-swap', '2g',
      '--cpus', '2',
      '--pids-limit', '256',
      '--security-opt', 'no-new-privileges:true',
      '--cap-drop', 'ALL',
      '--cap-add', 'CHOWN',
      '--cap-add', 'SETUID',
      '--cap-add', 'SETGID',
      '--cap-add', 'DAC_OVERRIDE',
      '--read-only',
      '--tmpfs', '/tmp:rw,noexec,nosuid,size=512m',
      '--tmpfs', '/home/demo:rw,noexec,nosuid,size=256m',
      // Environment configuration
      '--env-file', envFile.hostPath,
      '-e', 'TERM=xterm',
      '-e', `SESSION_TIMEOUT_MINUTES=${config.SESSION_TIMEOUT_MINUTES}`,
      '-e', `ENABLE_AUTOPLAY=${process.env.ENABLE_AUTOPLAY || 'false'}`,
      '-e', `AUTOPLAY_DEBUG=${process.env.AUTOPLAY_DEBUG || 'false'}`,
      '-e', `AUTOPLAY_SHOW_TOOLS=${process.env.AUTOPLAY_SHOW_TOOLS || 'false'}`,
      '-e', `OTEL_ENDPOINT=${process.env.OTEL_ENDPOINT || ''}`,
      'jira-demo-container:latest'
    ], {
      stdio: ['pipe', 'pipe', 'pipe']
    });

    // Record spawn time
    const spawnDuration = (Date.now() - spawnStartTime) / 1000;
    ttydSpawnHistogram?.record(spawnDuration);
    span?.setAttribute('ttyd.spawn_seconds', spawnDuration);

    const startedAt = new Date();
    const expiresAt = new Date(startedAt.getTime() + config.SESSION_TIMEOUT_MINUTES * 60 * 1000);
    const queueWaitMs = client.joinedAt ? (startedAt - client.joinedAt) : 0;

    // Record queue wait time
    if (queueWaitMs > 0) {
      queueWaitHistogram?.record(queueWaitMs / 1000);
      span?.setAttribute('session.queue_wait_seconds', queueWaitMs / 1000);
    }

    // Promote pending session token to active session token
    const sessionToken = client.pendingSessionToken;
    if (sessionToken) {
      state.pendingSessionTokens.delete(sessionToken);
      state.sessionTokens.set(sessionToken, sessionId);
    }

    const activeSession = {
      clientId: client.id,
      sessionId: sessionId,
      sessionToken: sessionToken,
      ttydProcess: ttydProcess,
      startedAt: startedAt,
      expiresAt: expiresAt,
      inviteToken: client.inviteToken || null,
      ip: client.ip,
      userAgent: client.userAgent,
      queueWaitMs: queueWaitMs,
      errors: [],
      envFileCleanup: envFileCleanup
    };

    state.setActiveSession(activeSession);

    // Handle ttyd exit
    ttydProcess.on('exit', (code) => {
      console.log(`ttyd exited with code ${code}`);
      const currentSession = state.getActiveSession();
      // Clear hard timeout since process exited normally
      if (currentSession && currentSession.hardTimeout) {
        clearTimeout(currentSession.hardTimeout);
        currentSession.hardTimeout = null;
      }
      if (currentSession && currentSession.clientId === client.id) {
        endSession(redis, 'container_exit', processQueue);
      }
    });

    // Hard timeout: force-kill ttyd if still running after session timeout + 5 min grace
    const hardTimeoutMs = (config.SESSION_TIMEOUT_MINUTES + 5) * 60 * 1000;
    const hardTimeout = setTimeout(() => {
      const currentSession = state.getActiveSession();
      if (currentSession && currentSession.ttydProcess && currentSession.clientId === client.id) {
        console.log(`Hard timeout reached for session ${sessionId}, force-killing ttyd`);
        try {
          currentSession.ttydProcess.kill('SIGKILL');
        } catch (err) {
          console.error('Error force-killing ttyd:', err.message);
        }
      }
    }, hardTimeoutMs);

    activeSession.hardTimeout = hardTimeout;

    // Notify client
    ws.send(JSON.stringify({
      type: 'session_starting',
      terminal_url: '/terminal',
      expires_at: expiresAt.toISOString(),
      session_token: sessionToken
    }));

    // Schedule warning and timeout
    scheduleSessionWarning(ws, client);
    scheduleSessionTimeout(redis, client, processQueue);

    // Save to Redis for persistence
    await redis.set(`session:${client.id}`, JSON.stringify({
      sessionId: sessionId,
      startedAt: startedAt.toISOString(),
      expiresAt: expiresAt.toISOString(),
      inviteToken: client.inviteToken || null,
      ip: client.ip,
      userAgent: client.userAgent,
      queueWaitMs: queueWaitMs
    }), 'EX', config.SESSION_TIMEOUT_MINUTES * 60);

    // Record metrics
    sessionsStartedCounter?.add(1);
    span?.setAttribute('session.id', sessionId);

    console.log(`Session started for ${client.id}, expires at ${expiresAt.toISOString()}`);

    span?.end();
  } catch (err) {
    console.error('Failed to start session:', err);
    span?.recordException(err);
    span?.end();
    ws.send(JSON.stringify({ type: 'error', message: 'Failed to start demo session' }));
    client.state = 'connected';

    // Clean up env file if it was created
    if (envFileCleanup) {
      envFileCleanup();
    }

    // Try next in queue
    processQueue();
  }
}

function scheduleSessionWarning(ws, client) {
  const warningTime = (config.SESSION_TIMEOUT_MINUTES - 5) * 60 * 1000;

  setTimeout(() => {
    const activeSession = state.getActiveSession();
    if (activeSession && activeSession.clientId === client.id) {
      ws.send(JSON.stringify({
        type: 'session_warning',
        minutes_remaining: 5
      }));
    }
  }, warningTime);
}

function scheduleSessionTimeout(redis, client, processQueue) {
  const timeoutMs = config.SESSION_TIMEOUT_MINUTES * 60 * 1000;

  setTimeout(() => {
    const activeSession = state.getActiveSession();
    if (activeSession && activeSession.clientId === client.id) {
      endSession(redis, 'timeout', processQueue);
    }
  }, timeoutMs);
}

/**
 * End the current session.
 * @param {Object} redis - Redis client
 * @param {string} reason - End reason
 * @param {Function} processQueue - Queue processing callback
 */
async function endSession(redis, reason, processQueue) {
  const activeSession = state.getActiveSession();
  if (!activeSession) return;

  const tracer = getTracer();
  const span = tracer?.startSpan('session.end', {
    attributes: {
      'session.id': activeSession.sessionId,
      'session.client_id': activeSession.clientId,
      'session.end_reason': reason,
    }
  });

  const clientId = activeSession.clientId;
  const endedAt = new Date();
  const durationMs = endedAt - activeSession.startedAt;
  console.log(`Ending session for ${clientId}, reason: ${reason}`);

  // Record session duration
  sessionDurationHistogram?.record(durationMs / 1000, { reason });
  sessionsEndedCounter?.add(1, { reason });
  span?.setAttribute('session.duration_seconds', durationMs / 1000);

  // Kill ttyd process
  if (activeSession.ttydProcess) {
    try {
      activeSession.ttydProcess.kill('SIGTERM');
    } catch (err) {
      console.error('Error killing ttyd:', err.message);
    }
  }

  // Clear hard timeout
  if (activeSession.hardTimeout) {
    clearTimeout(activeSession.hardTimeout);
    activeSession.hardTimeout = null;
  }

  // Clean up session env file (contains sensitive credentials)
  if (activeSession.envFileCleanup) {
    activeSession.envFileCleanup();
  }

  // Clear session token
  clearSessionToken(activeSession.sessionToken);

  // Record invite usage if applicable
  if (activeSession.inviteToken) {
    await recordInviteUsage(redis, activeSession, endedAt, reason, config.AUDIT_RETENTION_DAYS);
  }

  // Notify client to clear cookie
  const clientWs = findClientWs(clientId);
  if (clientWs) {
    clientWs.send(JSON.stringify({
      type: 'session_ended',
      reason: reason,
      clear_session_cookie: true
    }));

    const client = state.clients.get(clientWs);
    if (client) {
      client.state = 'connected';
      client.sessionToken = null;
    }
  }

  // Clean up Redis
  await redis.del(`session:${clientId}`);

  // Run JIRA sandbox cleanup
  runSandboxCleanup();

  state.setActiveSession(null);
  span?.end();

  // Process next in queue
  processQueue();
}

module.exports = {
  generateSessionToken,
  clearSessionToken,
  findClientWs,
  createSessionEnvFile,
  startSession,
  endSession
};

/**
 * Session management routes.
 */

const config = require('../config');
const state = require('../services/state');
const { checkInviteRateLimit, recordFailedInviteAttempt, validateInvite } = require('../services/invite');
const { createRateLimiter } = require('@demo-platform/queue-manager-core');

// Rate limiter for session cookie endpoint (20 requests per minute per IP)
const cookieRateLimiter = createRateLimiter({
  windowMs: 60 * 1000,
  maxAttempts: 20
});

/**
 * Register session routes.
 * @param {Express} app - Express application
 * @param {Object} redis - Redis client
 */
function register(app, redis) {
  // Session validation endpoint (used by nginx auth_request for Grafana)
  app.get('/api/session/validate', (req, res) => {
    const sessionCookie = req.cookies.demo_session;

    if (!sessionCookie) {
      return res.status(401).send('No session cookie');
    }

    const activeSession = state.getActiveSession();

    // Check active session token first
    const sessionId = state.sessionTokens.get(sessionCookie);
    if (sessionId && activeSession && activeSession.sessionId === sessionId) {
      res.set('X-Grafana-User', `demo-${sessionId.slice(0, 8)}`);
      return res.status(200).send('OK');
    }

    // Check pending session token (user in queue or session starting)
    const pending = state.pendingSessionTokens.get(sessionCookie);
    if (pending) {
      res.set('X-Grafana-User', `demo-${pending.clientId.slice(0, 8)}`);
      return res.status(200).send('OK');
    }

    // Clean up stale token if it was in sessionTokens
    if (state.sessionTokens.has(sessionCookie)) {
      state.sessionTokens.delete(sessionCookie);
    }

    return res.status(401).send('Session not active');
  });

  // Set session cookie with secure attributes
  app.post('/api/session/cookie', (req, res) => {
    const { token } = req.body;
    const clientIp = req.headers['x-forwarded-for']?.split(',')[0]?.trim() || req.socket.remoteAddress;

    // Rate limit check
    const rateLimit = cookieRateLimiter.check(clientIp);
    if (!rateLimit.allowed) {
      return res.status(429).json({ error: 'Too many requests', retryAfter: rateLimit.retryAfter });
    }

    if (!token || typeof token !== 'string') {
      return res.status(400).json({ error: 'Token required' });
    }

    // Verify token is valid (either active or pending)
    const isActiveToken = state.sessionTokens.has(token);
    const isPendingToken = state.pendingSessionTokens.has(token);

    if (!isActiveToken && !isPendingToken) {
      return res.status(401).json({ error: 'Invalid token' });
    }

    // For pending tokens, verify IP matches the original requestor
    if (isPendingToken) {
      const pendingData = state.pendingSessionTokens.get(token);
      if (pendingData && pendingData.ip !== clientIp) {
        console.log(`Session cookie IP mismatch: expected ${pendingData.ip}, got ${clientIp}`);
        return res.status(403).json({ error: 'Token IP mismatch' });
      }
    }

    // For active session tokens, verify IP matches the session owner
    if (isActiveToken) {
      const activeSession = state.getActiveSession();
      if (activeSession && activeSession.ip !== clientIp) {
        console.log(`Session cookie IP mismatch: expected ${activeSession.ip}, got ${clientIp}`);
        return res.status(403).json({ error: 'Token IP mismatch' });
      }
    }

    // Set secure cookie
    res.cookie('demo_session', token, {
      httpOnly: true,
      secure: config.COOKIE_SECURE,
      sameSite: 'strict',
      maxAge: config.SESSION_TIMEOUT_MINUTES * 60 * 1000,
      path: '/'
    });

    res.json({ success: true });
  });

  // Clear session cookie endpoint
  app.post('/api/session/logout', (req, res) => {
    res.clearCookie('demo_session', {
      httpOnly: true,
      secure: config.COOKIE_SECURE,
      sameSite: 'strict',
      path: '/'
    });
    res.json({ success: true });
  });

  // Invite validation endpoint (used by nginx auth_request)
  app.get('/api/invite/validate', async (req, res) => {
    // Token comes from X-Invite-Token header (set by nginx from path) or query param
    const token = req.headers['x-invite-token'] || req.query.token;
    const clientIp = req.headers['x-forwarded-for']?.split(',')[0]?.trim() || req.socket.remoteAddress;

    // Check rate limit before validating (brute-force protection)
    const rateLimit = checkInviteRateLimit(clientIp);
    if (!rateLimit.allowed) {
      console.log(`Invite validation rate limit exceeded for ${clientIp}`);
      return res.status(429).json({
        valid: false,
        reason: 'rate_limited',
        message: `Too many attempts. Please try again in ${Math.ceil(rateLimit.retryAfter / 60)} minutes.`
      });
    }

    if (!token) {
      recordFailedInviteAttempt(clientIp);
      return res.status(401).json({ valid: false, reason: 'missing', message: 'Invite token required' });
    }

    const validation = await validateInvite(redis, token, clientIp);

    if (validation.valid) {
      res.status(200).json({ valid: true });
    } else {
      // Record failed attempt for rate limiting
      recordFailedInviteAttempt(clientIp);
      res.status(401).json({ valid: false, reason: validation.reason, message: validation.message });
    }
  });
}

module.exports = { register };

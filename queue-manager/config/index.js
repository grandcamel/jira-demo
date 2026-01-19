/**
 * Configuration constants for the queue manager.
 */

// Known weak secrets that should not be used in production
const WEAK_SECRETS = [
  'change-me-in-production',
  'secret',
  'password',
  'demo',
  'test',
  'changeme',
  'admin',
  '123456'
];

/**
 * Validates the session secret strength.
 * In production, weak secrets or short secrets cause a fatal exit.
 * In development, warnings are logged but execution continues.
 * @param {string} secret - The session secret to validate
 * @param {boolean} isProduction - Whether running in production mode
 */
function validateSessionSecret(secret, isProduction) {
  const isWeak = WEAK_SECRETS.some(weak =>
    secret.toLowerCase() === weak.toLowerCase()
  );

  if (isWeak) {
    if (isProduction) {
      console.error('FATAL: SESSION_SECRET is a known weak value. Use a strong random secret.');
      process.exit(1);
    }
    console.warn('WARNING: Using weak SESSION_SECRET - not suitable for production');
  }

  if (secret.length < 32) {
    if (isProduction) {
      console.error('FATAL: SESSION_SECRET must be at least 32 characters');
      process.exit(1);
    }
    console.warn('WARNING: SESSION_SECRET should be at least 32 characters');
  }
}

const config = {
  // Server
  PORT: process.env.PORT || 3000,
  REDIS_URL: process.env.REDIS_URL || 'redis://localhost:6379',

  // Session
  SESSION_TIMEOUT_MINUTES: parseInt(process.env.SESSION_TIMEOUT_MINUTES, 10) || 60,
  MAX_QUEUE_SIZE: parseInt(process.env.MAX_QUEUE_SIZE, 10) || 10,
  AVERAGE_SESSION_MINUTES: 45,
  TTYD_PORT: 7681,
  DISCONNECT_GRACE_MS: 10000,
  AUDIT_RETENTION_DAYS: 30,
  SESSION_SECRET: process.env.SESSION_SECRET || 'change-me-in-production',

  // Session environment files (for secure credential passing)
  SESSION_ENV_HOST_PATH: process.env.SESSION_ENV_HOST_PATH || '/tmp/session-env',
  SESSION_ENV_CONTAINER_PATH: '/run/session-env',

  // Rate limiting
  RATE_LIMIT_WINDOW_MS: 60 * 1000,  // 1 minute window
  RATE_LIMIT_MAX_CONNECTIONS: 10,    // Max connections per IP per window

  // Invite brute-force protection
  INVITE_RATE_LIMIT_WINDOW_MS: 60 * 60 * 1000,  // 1 hour window
  INVITE_RATE_LIMIT_MAX_ATTEMPTS: 10,            // Max failed attempts per IP per hour

  // Claude authentication
  CLAUDE_CODE_OAUTH_TOKEN: process.env.CLAUDE_CODE_OAUTH_TOKEN || '',
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY || '',

  // Base URL and allowed origins
  BASE_URL: process.env.BASE_URL || 'http://localhost:8080',
  ALLOWED_ORIGINS: (process.env.ALLOWED_ORIGINS || process.env.BASE_URL || 'http://localhost:8080').split(',').map(o => o.trim()),
  COOKIE_SECURE: process.env.NODE_ENV === 'production' || process.env.COOKIE_SECURE === 'true',

  // JIRA
  JIRA_API_TOKEN: process.env.JIRA_API_TOKEN || '',
  JIRA_EMAIL: process.env.JIRA_EMAIL || '',
  JIRA_SITE_URL: process.env.JIRA_SITE_URL || '',

  // Scenarios
  SCENARIOS_PATH: '/opt/demo-container/scenarios',
  SCENARIO_NAMES: {
    'issue': { file: 'issue.md', title: 'Issue Management', icon: '📝' },
    'search': { file: 'search.md', title: 'JQL Search', icon: '🔍' },
    'agile': { file: 'agile.md', title: 'Agile & Sprints', icon: '🏃' },
    'jsm': { file: 'jsm.md', title: 'Service Desk', icon: '🎫' },
    'observability': { file: 'observability.md', title: 'Observability', icon: '📊' }
  }
};

// Validate session secret on module load
validateSessionSecret(config.SESSION_SECRET, process.env.NODE_ENV === 'production');

module.exports = config;

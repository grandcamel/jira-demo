/**
 * OpenTelemetry metrics configuration.
 *
 * Uses @demo-platform/queue-manager-core for standardized metrics.
 */

const { createMetrics } = require('@demo-platform/queue-manager-core');

let metricsManager = null;

/**
 * Initialize metrics with observable callbacks.
 * @param {Function} getQueueLength - Function to get current queue length
 * @param {Function} getActiveSessionCount - Function to get active session count (0 or 1)
 */
function initMetrics(getQueueLength, getActiveSessionCount) {
  metricsManager = createMetrics({
    serviceName: 'jira-demo-queue-manager',
    getQueueLength,
    getActiveSessionCount
  });
}

/**
 * Get the OpenTelemetry tracer.
 * @returns {Tracer|null} Tracer instance or null if OTel not available
 */
function getTracer() {
  return metricsManager ? metricsManager.getTracer() : null;
}

module.exports = {
  initMetrics,
  getTracer,
  get sessionsStartedCounter() { return metricsManager?.sessionsStarted; },
  get sessionsEndedCounter() { return metricsManager?.sessionsEnded; },
  get sessionDurationHistogram() { return metricsManager?.sessionDuration; },
  get queueWaitHistogram() { return metricsManager?.queueWait; },
  get ttydSpawnHistogram() { return metricsManager?.ttydSpawn; },
  get invitesValidatedCounter() { return metricsManager?.invitesValidated; },
  get sandboxCleanupHistogram() { return metricsManager?.sandboxCleanup; }
};

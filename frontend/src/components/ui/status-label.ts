export type HealthStatus = 'healthy' | 'degraded' | 'down' | 'disabled' | 'not_configured' | 'unknown'

export const STATUS_LABEL: Record<HealthStatus, string> = {
  healthy: 'healthy',
  degraded: 'degraded',
  down: 'down',
  disabled: 'disabled',
  not_configured: 'not configured',
  unknown: 'not checked',
}

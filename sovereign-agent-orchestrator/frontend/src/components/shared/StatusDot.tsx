import type { JobStatus } from '../../types/api'

// Real backend statuses collapse into 4 visual states: pending (queued), running
// (every in-flight stage, including awaiting_approval -- it's paused, not idle),
// done, failed/cancelled.
function bucket(status: JobStatus): 'pending' | 'running' | 'done' | 'failed' {
  if (status === 'queued') return 'pending'
  if (status === 'done') return 'done'
  if (status === 'failed' || status === 'cancelled') return 'failed'
  return 'running'
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Queued',
  planning: 'Planning',
  acting: 'Running',
  observing: 'Running',
  verifying: 'Verifying',
  awaiting_approval: 'Awaiting Approval',
  delivering: 'Delivering',
  done: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function StatusDot({ status, className = '' }: { status: JobStatus; className?: string }) {
  const state = bucket(status)
  if (state === 'pending') return <span className={`inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50 ${className}`} />
  if (state === 'running') return <span className={`inline-block h-1.5 w-1.5 animate-status-pulse rounded-full ${status === 'awaiting_approval' ? 'bg-warning' : 'bg-info'} ${className}`} />
  if (state === 'failed') return <span className={`inline-block h-1.5 w-1.5 rounded-full bg-danger ${className}`} />
  return <span className={`inline-block h-1.5 w-1.5 rounded-full bg-success ${className}`} />
}

export default StatusDot

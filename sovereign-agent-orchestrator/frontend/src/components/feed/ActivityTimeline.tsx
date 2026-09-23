import type { JobEvent } from '../../types/api'

const EVENT_LABELS: Record<string, string> = {
  job_created: 'Task created',
  status_changed: 'Status changed',
  model_selected: 'Selected model',
  model_fallback: 'Model unavailable, falling back',
  model_error: 'Model call failed',
  model_response: 'Generated response',
  plan_created: 'Created execution plan',
  replanning: 'Revising plan',
  step_started: 'Started execution step',
  step_completed: 'Finished execution step',
  tool_started: 'Started tool',
  tool_completed: 'Completed tool',
  observation: 'Collected tool output',
  approval_required: 'Waiting for human approval',
  approval_approved: 'Approval granted',
  approval_rejected: 'Approval rejected',
  verification_passed: 'Verification passed',
  verification_failed: 'Verification failed',
  artifact_created: 'Saved artifact',
  job_completed: 'Task completed',
  job_cancelled: 'Task cancelled',
}

function describeEvent(event: JobEvent) {
  const label = EVENT_LABELS[event.type] ?? event.type.replace(/_/g, ' ')
  const detail =
    (event.data.status as string) ||
    (event.data.model_name as string) ||
    (event.data.model_id as string) ||
    (event.data.tool as string) ||
    (event.data.name as string) ||
    ''
  return detail ? `${label} · ${detail}` : label
}

function ActivityTimeline({ events }: { events: JobEvent[] }) {
  const visible = events.filter((event) => event.type !== 'status_changed')
  if (!visible.length) return null
  return (
    <div className="border-hairline mt-3 bg-surface px-4 py-3">
      <p className="label-micro">Agent Activity</p>
      <div className="mt-2 flex flex-col gap-2">
        {visible.map((event) => (
          <div key={event.event_id} className="flex items-center gap-2.5 text-sm text-muted-foreground">
            <span className="h-1 w-1 shrink-0 rounded-full bg-accent" />
            <span className="flex-1 font-mono text-xs">{describeEvent(event)}</span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground/70">{new Date(event.timestamp).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ActivityTimeline

import { useState } from 'react'
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

// A disclosure rather than an always-open log. A long run emits dozens of events, and
// unrolled they pushed the answer -- the thing people actually came for -- off screen.
// Collapsed, the row still carries the step count and the most recent line, so the run
// is legible without opening it.
function ActivityTimeline({ events }: { events: JobEvent[] }) {
  const [open, setOpen] = useState(false)
  const visible = events.filter((event) => event.type !== 'status_changed')
  if (!visible.length) return null
  const latest = visible[visible.length - 1]

  return (
    <div className="border-hairline mt-3 overflow-hidden rounded-2xl bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition-colors hover:bg-fill"
      >
        <svg
          aria-hidden="true"
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`shrink-0 text-accent transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        >
          <path d="m6 3 5 5-5 5" />
        </svg>
        <span className="label-micro shrink-0">Agent activity</span>
        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{visible.length} step{visible.length === 1 ? '' : 's'}</span>
        {!open ? (
          <span className="min-w-0 flex-1 truncate text-right font-mono text-[11px] text-muted-foreground/75">{describeEvent(latest)}</span>
        ) : null}
      </button>

      {open ? (
        <div className="flex flex-col gap-2 border-t border-rule px-4 py-3">
          {visible.map((event) => (
            <div key={event.event_id} className="flex items-center gap-2.5 text-sm text-muted-foreground">
              <span className="h-1 w-1 shrink-0 rounded-full bg-accent" />
              <span className="flex-1 font-mono text-xs">{describeEvent(event)}</span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground/70">{new Date(event.timestamp).toLocaleTimeString()}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default ActivityTimeline

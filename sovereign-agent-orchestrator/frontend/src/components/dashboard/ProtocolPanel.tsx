import type { Job, JobSummary, JobStatus } from '../../types/api'
import { STATUS_LABEL } from '../shared/StatusDot'

const STEPS = [
  { title: 'Task Received', detail: (job: Job) => <><span className="text-muted-foreground">Prompt</span><span className="break-words">{job.task}</span></> },
  { title: 'Model Selection', detail: (job: Job) => <div className="space-y-1"><p><span className="text-muted-foreground">Model</span><span className="ml-3">{job.routing?.model_name ?? job.routing?.model_id ?? 'Not selected yet'}</span></p>{job.routing?.task_type ? <p><span className="text-muted-foreground">Task type</span><span className="ml-3">{job.routing.task_type}</span></p> : null}{job.routing?.reason ? <p><span className="text-muted-foreground">Reason</span><span className="ml-3">{job.routing.reason}</span></p> : null}</div> },
  { title: 'Execution Plan', detail: (job: Job) => <><span className="text-muted-foreground">Plan</span><span>{job.plan?.length ? `${job.plan.length} planned step${job.plan.length === 1 ? '' : 's'}` : 'No tool steps recorded'}</span></> },
  { title: 'Tool Execution', detail: (job: Job) => <><span className="text-muted-foreground">Tools</span><span>{job.plan?.filter((step) => step.tool).map((step) => step.tool).join(', ') || 'None recorded for this task'}</span></> },
  { title: 'Verification', detail: (job: Job) => <><span className="text-muted-foreground">Checks</span><span>{job.verification ? `${Object.values(job.verification.checks).filter(Boolean).length}/${Object.keys(job.verification.checks).length} checks passed` : 'No verification result yet'}</span></> },
  { title: 'Delivery', detail: (job: Job) => <><span className="text-muted-foreground">Status</span><span>{job.status === 'done' ? 'Answer delivered' : job.status === 'failed' ? 'Task failed' : job.status === 'cancelled' ? 'Task cancelled' : 'Awaiting delivery'}</span></> },
]

const PROGRESS: Record<JobStatus, number> = { queued: 0, planning: 1, acting: 2, observing: 3, verifying: 4, awaiting_approval: 4, delivering: 5, done: 6, failed: 0, cancelled: 0 }

export function ProtocolPanel({ job, summary, loading }: { job?: Job; summary?: JobSummary; loading: boolean }) {
  const finished = summary?.status === 'done'
  const stopped = summary?.status === 'failed' || summary?.status === 'cancelled'
  const progress = summary ? PROGRESS[summary.status] : 0

  return (
    <section aria-labelledby="last-run-title" className="min-w-0">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span aria-hidden="true" className="font-mono text-xs text-accent">02 /</span>
        <h2 id="last-run-title" className="text-base font-medium tracking-tight text-foreground">Latest execution</h2>
        {summary ? <span className={`rounded-full border px-3 py-1 font-mono text-[9px] uppercase tracking-widest ${stopped ? 'border-danger/30 bg-danger/5 text-danger' : finished ? 'border-success/30 bg-success/10 text-success' : summary.status === 'awaiting_approval' ? 'border-warning/30 bg-warning/10 text-warning' : 'border-info/30 bg-info/10 text-info'}`}>{STATUS_LABEL[summary.status]}</span> : null}
      </div>

      <div className="protocol-surface p-5 sm:p-6">
        <div className="mb-5 flex items-center justify-between gap-3"><p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Execution sequence</p><span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{summary ? STATUS_LABEL[summary.status] : 'No run'}</span></div>
        {!job ? <p className="mb-5 rounded-lg border border-dashed border-white/10 px-3 py-2 text-xs text-muted-foreground">{loading ? 'Loading protocol details…' : summary ? 'Protocol details are unavailable right now.' : 'No runs yet. Start a task to populate this pipeline.'}</p> : null}
        <ol className="space-y-0">
          {STEPS.map((step, index) => {
            const complete = Boolean(summary && (finished || index < progress))
            const current = Boolean(summary && !finished && index === progress && summary.status !== 'failed' && summary.status !== 'cancelled')
            return <li key={step.title} className="flex gap-3.5">
              <div className="flex w-5 shrink-0 flex-col items-center"><span className={`flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] ${complete ? 'border-success/40 bg-success/10 text-success' : current ? 'border-info/70 bg-info/10 text-info' : 'border-white/15 text-muted-foreground'}`} aria-label={complete ? 'Complete' : current ? 'In progress' : 'Pending'}>{complete ? '✓' : current ? '•' : ''}</span>{index < STEPS.length - 1 ? <span className="my-1 min-h-6 w-px flex-1 bg-white/12" /> : null}</div>
              <div className="min-w-0 pb-5 last:pb-0"><h3 className="text-xs font-semibold text-foreground">{step.title}</h3>{job ? <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] leading-relaxed text-foreground/80">{step.detail(job)}</div> : <p className="mt-1 text-[11px] text-muted-foreground">Awaiting run</p>}</div>
            </li>
          })}
        </ol>
      </div>

      <div className="work-panel mt-3 px-5 py-4 sm:px-6">
        <h3 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Run details</h3>
        {summary && job ? <dl className="divide-y divide-white/7 text-xs"><div className="flex justify-between gap-4 py-2.5"><dt className="text-muted-foreground">Routed Model</dt><dd className="text-right text-foreground">{job.routing?.model_name ?? job.routing?.model_id ?? 'Not available'}</dd></div><div className="flex justify-between gap-4 py-2.5"><dt className="text-muted-foreground">Routing Confidence</dt><dd className="text-foreground">{typeof job.routing?.confidence === 'number' ? `${Math.round(job.routing.confidence * 100)}%` : 'Not available'}</dd></div><div className="flex justify-between gap-4 py-2.5"><dt className="text-muted-foreground">Verification</dt><dd className="text-foreground">{job.verification ? `${Object.values(job.verification.checks).filter(Boolean).length}/${Object.keys(job.verification.checks).length} checks passed` : 'Not available'}</dd></div><div className="flex justify-between gap-4 py-2.5"><dt className="text-muted-foreground">Evidence Retrieved</dt><dd className="text-foreground">{job.retrieval?.length ?? 0} sources</dd></div></dl> : <p className="py-4 text-xs text-muted-foreground">Synthesis details appear after a run is available.</p>}
      </div>
    </section>
  )
}

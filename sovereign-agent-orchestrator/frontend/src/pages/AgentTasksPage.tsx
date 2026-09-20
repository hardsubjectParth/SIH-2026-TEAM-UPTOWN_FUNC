import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import * as Tabs from '@radix-ui/react-tabs'
import { useJobs } from '../hooks/useJob'
import StatCard from '../components/shared/StatCard'
import StatusPill from '../components/shared/StatusPill'
import IconTile from '../components/shared/IconTile'
import type { Tone } from '../components/shared/IconTile'
import { STATUS_TONE } from '../components/shared/StatusPill'
import { TasksIcon, ChipIcon, ShieldIcon, DatabaseIcon, AlertIcon, ChevronRightIcon } from '../components/shell/icons'
import type { JobStatus, JobSummary } from '../types/api'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'review', label: 'Review' },
] as const

const IN_PROGRESS: JobStatus[] = ['queued', 'planning', 'acting', 'observing', 'verifying', 'delivering']

function relativeTime(iso?: string) {
  if (!iso) return '—'
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

// The glyph follows the job's phase, not its task type: in-flight work gets the
// processor, verified-and-delivered work the shield, queued work the ingest stack.
function tileFor(status: JobStatus) {
  if (status === 'done') return ShieldIcon
  if (status === 'failed' || status === 'cancelled') return AlertIcon
  if (status === 'queued' || status === 'awaiting_approval') return DatabaseIcon
  return ChipIcon
}

// The mockup's right-hand column shows DUE / DURATION / PRIORITY. This backend
// tracks none of those (no deadlines, no duration field), so the column reports
// what the job record actually knows rather than inventing a due date.
function meta(job: JobSummary): { label: string; value: string; tone?: Tone } {
  if (job.status === 'awaiting_approval') return { label: 'Priority', value: 'Review', tone: 'warning' }
  if (job.status === 'failed') return { label: 'Outcome', value: 'Failed', tone: 'danger' }
  if (job.status === 'cancelled') return { label: 'Outcome', value: 'Cancelled' }
  if (job.status === 'done') {
    return job.verification_passed
      ? { label: 'Completed', value: relativeTime(job.created_at), tone: 'success' }
      : { label: 'Completed', value: relativeTime(job.created_at) }
  }
  return { label: 'Started', value: relativeTime(job.created_at) }
}

const META_TONE: Record<string, string> = {
  warning: 'text-warning',
  danger: 'text-danger',
  success: 'text-success',
}

function AgentTasksPage() {
  const navigate = useNavigate()
  const { jobs } = useJobs(100)
  const [filter, setFilter] = useState<string>('all')

  const active = jobs.filter((job) => IN_PROGRESS.includes(job.status)).length
  const completed = jobs.filter((job) => job.status === 'done').length
  const pending = jobs.filter((job) => job.status === 'queued').length
  const finished = jobs.filter((job) => job.status === 'done' || job.status === 'failed')
  const successRate = finished.length ? Math.round((completed / finished.length) * 1000) / 10 : 100

  const filtered = jobs.filter((job) => {
    if (filter === 'in_progress') return IN_PROGRESS.includes(job.status)
    if (filter === 'review') return job.status === 'awaiting_approval'
    return true
  })

  return (
    <div className="flex h-screen min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-white/7 px-8 py-5">
        <div className="flex items-center gap-3.5">
          <TasksIcon size={20} className="text-accent" />
          <h1 className="font-display text-[22px] leading-none font-medium text-foreground">Agent Task Oversight</h1>
        </div>
        <button
          type="button"
          onClick={() => navigate('/app/feed')}
          className="rounded-xl bg-primary px-6 py-3 text-[11px] font-semibold tracking-[0.12em] text-primary-foreground uppercase transition hover:bg-primary-hover"
        >
          Delegate New Task
        </button>
      </header>

      <main className="scroll-slim min-h-0 flex-1 overflow-y-auto px-8 py-8">
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
          <StatCard label="Active Protocols" value={active} />
          <StatCard label="Completed" value={completed} />
          <StatCard label="Pending Ingest" value={pending} />
          <StatCard label="Success Rate" value={successRate} suffix="%" accent />
        </div>

        <div className="mt-10">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-[19px] font-medium text-foreground">Current Assignments</h2>
            <Tabs.Root value={filter} onValueChange={setFilter}>
              <Tabs.List className="flex gap-5">
                {FILTERS.map((item) => (
                  <Tabs.Trigger
                    key={item.value}
                    value={item.value}
                    className="text-[13px] text-muted-foreground transition hover:text-foreground data-[state=active]:font-semibold data-[state=active]:text-foreground"
                  >
                    {item.label}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
            </Tabs.Root>
          </div>

          <div className="mt-5 flex flex-col gap-3">
            {filtered.length === 0 ? (
              <div className="border-hairline rounded-2xl bg-surface px-6 py-12 text-center">
                <p className="text-sm text-muted-foreground">
                  {jobs.length === 0 ? 'No tasks delegated yet.' : 'No tasks match this filter.'}
                </p>
              </div>
            ) : null}

            {filtered.map((job, index) => {
              const Tile = tileFor(job.status)
              const detail = meta(job)
              return (
                <motion.button
                  key={job.job_id}
                  type="button"
                  onClick={() => navigate(`/app/artifacts?job=${job.job_id}`)}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index, 8) * 0.03, duration: 0.25 }}
                  className="border-hairline group flex w-full items-center gap-5 rounded-2xl bg-surface px-5 py-4 text-left transition-colors hover:border-white/14 hover:bg-surface-raised"
                >
                  <IconTile tone={STATUS_TONE[job.status]} size={46}>
                    <Tile size={20} />
                  </IconTile>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-3">
                      <p className="truncate text-[15px] font-semibold text-foreground">{job.task}</p>
                      <StatusPill status={job.status} />
                    </div>
                    <p className="mt-1.5 truncate text-[13px] text-muted-foreground">
                      {job.model_name ? `Routed to ${job.model_name}` : 'Awaiting routing'}
                      {job.task_type ? ` · ${job.task_type.replace(/_/g, ' ')}` : ''}
                      {job.artifacts.length ? ` · ${job.artifacts.length} artifact${job.artifacts.length === 1 ? '' : 's'}` : ''}
                    </p>
                  </div>

                  <div className="shrink-0 text-right">
                    <p className="label-micro">{detail.label}</p>
                    <p className={`mt-1 text-[13px] font-semibold ${detail.tone ? META_TONE[detail.tone] : 'text-foreground'}`}>
                      {detail.value}
                    </p>
                  </div>

                  <ChevronRightIcon size={18} className="shrink-0 text-muted-foreground transition group-hover:text-foreground" />
                </motion.button>
              )
            })}
          </div>
        </div>
      </main>
    </div>
  )
}

export default AgentTasksPage

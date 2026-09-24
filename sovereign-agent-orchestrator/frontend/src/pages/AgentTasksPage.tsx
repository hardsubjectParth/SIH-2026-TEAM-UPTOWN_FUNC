import { useNavigate, useSearchParams } from 'react-router-dom'
import * as Tabs from '@radix-ui/react-tabs'
import { useJobs } from '../hooks/useJob'
import { useAuth } from '../context/AuthContext'
import StatCard from '../components/shared/StatCard'
import StatusDot, { STATUS_LABEL } from '../components/shared/StatusDot'
import type { JobStatus } from '../types/api'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'review', label: 'Awaiting approval' },
] as const

type Filter = (typeof FILTERS)[number]['value']

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

function AgentTasksPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const { jobs, error, isLoading } = useJobs(100)
  // Derived from the URL so sidebar links like ?filter=review work while already on this page.
  const requested = searchParams.get('filter')
  const filter: Filter = FILTERS.some((item) => item.value === requested) ? requested as Filter : 'all'

  const active = jobs.filter((job) => IN_PROGRESS.includes(job.status)).length
  const completed = jobs.filter((job) => job.status === 'done').length
  const awaiting = jobs.filter((job) => job.status === 'awaiting_approval').length
  const finished = jobs.filter((job) => job.status === 'done' || job.status === 'failed')
  const successRate = finished.length ? Math.round((completed / finished.length) * 100) : null

  const filtered = jobs.filter((job) => {
    if (filter === 'in_progress') return IN_PROGRESS.includes(job.status)
    if (filter === 'review') return job.status === 'awaiting_approval'
    return true
  })

  function changeFilter(next: string) {
    setSearchParams(next === 'all' ? {} : { filter: next }, { replace: true })
  }

  return (
    <main className="app-page flex-1 overflow-y-auto px-4 py-7 sm:px-8 sm:py-9 xl:px-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="label-micro mb-3 text-accent">03 / Execution register</p><h1 className="text-3xl font-medium tracking-[-0.04em] text-foreground">{user?.role === 'lower' ? 'My Tasks' : 'Agent Tasks'}<span className="text-accent">.</span></h1>
          <p className="mt-1 text-xs text-muted-foreground">Showing up to 100 recent tasks visible to your account.</p>
        </div>
        <button type="button" onClick={() => navigate('/app/feed')} className="action-primary px-4 py-2 text-xs">
          New task
        </button>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="In progress" value={active} note="Running now" accent={active > 0} />
        <StatCard label="Completed" value={completed} note="Finished successfully" />
        <StatCard label="Awaiting approval" value={awaiting} note="Need a reviewer decision" />
        <StatCard label="Success rate" value={successRate ?? '—'} suffix={successRate === null ? '' : '%'} note="Of completed or failed runs" accent />
      </div>

      <div className="mt-8">
        <Tabs.Root value={filter} onValueChange={changeFilter}>
          <Tabs.List aria-label="Filter tasks" className="flex gap-2 overflow-x-auto pb-2">
            {FILTERS.map((item) => (
              <Tabs.Trigger
                key={item.value}
                value={item.value}
                className="shrink-0 rounded-full border border-accent/15 bg-fill px-4 py-2 text-xs text-muted-foreground transition-colors hover:bg-fill data-[state=active]:border-accent/50 data-[state=active]:bg-accent/15 data-[state=active]:text-foreground"
              >
                {item.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
        </Tabs.Root>

        <div className="mt-3 flex flex-col gap-2">
          {error ? <p role="alert" className="text-sm text-danger">Tasks could not be loaded. Check your API connection.</p> : null}
          {isLoading ? <p className="text-sm text-muted-foreground">Loading tasks…</p> : null}
          {!isLoading && !error && filtered.length === 0 ? <p className="text-sm text-muted-foreground">No tasks match this filter.</p> : null}
          {filtered.map((job) => (
            <div key={job.job_id} className="work-panel flex items-center justify-between gap-4 px-4 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-foreground">{job.task}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <StatusDot status={job.status} />
                  <span className="label-micro">{STATUS_LABEL[job.status]}</span>
                  {job.model_name ? <span className="text-xs text-muted-foreground">· Routed to {job.model_name}</span> : null}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <p className="label-micro">{relativeTime(job.created_at)}</p>
                {job.verification_passed ? <p className="mt-0.5 text-xs text-accent">Verified ✓</p> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </main>
  )
}

export default AgentTasksPage

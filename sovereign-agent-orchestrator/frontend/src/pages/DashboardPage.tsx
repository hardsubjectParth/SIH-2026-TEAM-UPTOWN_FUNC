import { Link } from 'react-router-dom'
import useSWR from 'swr'
import { useAuth } from '../context/AuthContext'
import { ActivityCard, MetricTile, ScopeCard } from '../components/dashboard/DashboardCards'
import type { MetricTone } from '../components/dashboard/DashboardCards'
import { ProtocolPanel } from '../components/dashboard/ProtocolPanel'
import { getJob, listConversations, listFiles, listJobs } from '../services/api'
import type { JobStatus, Role } from '../types/api'

const ACTIVE: JobStatus[] = ['queued', 'planning', 'acting', 'observing', 'verifying', 'delivering']
const HEADINGS: Record<Role, { eyebrow: string; title: string; subtitle: string }> = {
  admin: { eyebrow: 'Workspace administration', title: 'Operations overview', subtitle: 'Monitor accessible operations, outcomes and knowledge sources.' },
  higher: { eyebrow: 'Operations review', title: 'Review workspace', subtitle: 'Track accessible runs and their verification status.' },
  lower: { eyebrow: 'Operations analysis', title: 'Your workspace', subtitle: 'Your recent runs, shared knowledge and next steps in one place.' },
}

function DashboardPage() {
  const { user, token } = useAuth()
  const role = user?.role ?? 'lower'
  const { data: jobsData, error: jobsError, isLoading: jobsLoading } = useSWR(token ? ['dashboard-jobs', token] : null, ([, key]) => listJobs(key, 100), { refreshInterval: 10000 })
  const { data: filesData, error: filesError } = useSWR(token ? ['dashboard-files', token] : null, ([, key]) => listFiles(key))
  const { data: conversationsData, error: conversationsError } = useSWR(token ? ['dashboard-conversations', token] : null, ([, key]) => listConversations(key))
  const jobs = jobsData?.data ?? []
  const files = filesData?.data ?? []
  const conversations = conversationsData?.data ?? []
  const latest = [...jobs].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0]
  const { data: detail, isLoading: detailLoading } = useSWR(token && latest ? ['dashboard-job', latest.job_id, token] : null, ([, id, key]) => getJob(id, key), { refreshInterval: latest && ACTIVE.includes(latest.status) ? 2000 : 0 })
  const active = jobs.filter((job) => ACTIVE.includes(job.status)).length
  const done = jobs.filter((job) => job.status === 'done').length
  const finished = jobs.filter((job) => job.status === 'done' || job.status === 'failed').length
  const review = jobs.filter((job) => job.status === 'awaiting_approval').length
  const verified = jobs.filter((job) => job.verification_passed).length
  const outputCount = jobs.reduce((count, job) => count + (job.artifacts?.length ?? 0), 0)
  // Tone is earned, not assigned per position: the lead figure carries the accent, a
  // pass rate reads as success, and a queue only lights up while it actually holds
  // something. Everything else stays neutral -- see MetricTile.
  const queueTone = (count: number, tone: MetricTone) => (count > 0 ? tone : 'neutral')
  const metrics: Array<{ label: string; value: string | number; note: string; tone: MetricTone }> = role === 'admin' ? [
    { label: 'Recent jobs', value: jobs.length, note: 'Latest 100 accessible runs', tone: 'accent' },
    { label: 'Success rate', value: finished ? `${Math.round(done / finished * 100)}%` : '—', note: 'Of completed or failed runs', tone: finished ? 'success' : 'neutral' },
    { label: 'Active / queued', value: active, note: `${review} awaiting approval`, tone: queueTone(active, 'info') },
    { label: 'Knowledge sources', value: files.length, note: `${outputCount} artifacts from recent runs`, tone: 'neutral' },
  ] : role === 'higher' ? [
    { label: 'Pending approvals', value: review, note: 'Among your accessible runs', tone: queueTone(review, 'warning') },
    { label: 'Active jobs', value: active, note: 'In progress now', tone: queueTone(active, 'info') },
    { label: 'Verified', value: verified, note: 'Recent verification passes', tone: verified > 0 ? 'success' : 'neutral' },
    { label: 'Your uploads', value: files.length, note: 'Documents you added', tone: 'neutral' },
  ] : [
    { label: 'Your sessions', value: conversations.length, note: 'Accessible conversations', tone: 'accent' },
    { label: 'Active jobs', value: active, note: 'Currently in progress', tone: queueTone(active, 'info') },
    { label: 'Recent outputs', value: outputCount, note: 'Artifacts in recent runs', tone: 'neutral' },
    { label: 'Your uploads', value: files.length, note: 'Documents you added', tone: 'neutral' },
  ]
  const heading = HEADINGS[role]
  const hasError = jobsError || filesError || conversationsError

  return <main className="app-page min-h-0 flex-1 overflow-y-auto px-4 py-7 sm:px-8 sm:py-9 xl:px-12">
    <div className="mx-auto max-w-[1400px] pb-12">
      <header className="flex flex-wrap items-end justify-between gap-6 border-b border-rule pb-8 sm:flex-nowrap"><div className="min-w-0"><p className="label-micro text-accent">{heading.eyebrow}</p><h1 className="mt-5 text-[28px] font-medium leading-tight tracking-[-0.035em] text-foreground sm:text-[40px]">{heading.title}<span className="text-accent">.</span></h1><p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">{heading.subtitle}</p></div></header>
      {hasError ? <div role="alert" className="mt-5 rounded-xl border border-danger/25 bg-danger/5 px-4 py-3 text-xs text-danger">Some live workspace data could not be loaded. Check your API connection and refresh the page.</div> : null}
      <section aria-label="Workspace metrics" className="mt-8 grid grid-cols-2 gap-3 xl:grid-cols-4">{metrics.map((metric) => <MetricTile key={metric.label} {...metric} value={jobsLoading && metric.label !== 'Your sessions' ? '—' : metric.value} />)}</section>
      {/* "Next step" sits at the foot of the left column rather than the right. The
          left column (one execution panel) is much shorter than the right stack, so
          with all three cards on the right the page ended in a tall band of empty
          space under the pipeline. Moving the shortest card across evens the two
          columns out and closes the gap. */}
      <div className="mt-10 grid items-start gap-8 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.8fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <ProtocolPanel job={detail} summary={latest} loading={jobsLoading || detailLoading} />
          <div className="work-panel border-l-2 border-l-accent/65 p-5"><p className="label-micro text-accent">Next step</p><p className="mt-2 text-sm font-medium text-foreground">{role === 'admin' ? 'Keep operations in view.' : role === 'higher' ? 'Inspect pending approvals.' : 'Continue your work.'}</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{role === 'admin' ? 'Inspect recent tasks or add new knowledge to the workspace.' : role === 'higher' ? 'Check approval requests visible to your account and inspect their verification details.' : 'Start a new session or return to your latest conversation.'}</p><Link to={role === 'higher' ? '/app/tasks?filter=review' : role === 'admin' ? '/app/knowledge/ingest' : conversations[0] ? `/app/feed/${conversations[0].id}` : '/app/feed'} className="mt-4 inline-block text-xs font-medium text-accent hover:underline">{role === 'admin' ? 'Manage knowledge' : role === 'higher' ? 'View pending tasks' : 'Continue to feed'} →</Link></div>
        </div>
        <div className="flex min-w-0 flex-col gap-4"><ScopeCard role={role} files={files} conversations={conversations} jobs={jobs} /><ActivityCard role={role} jobs={jobs} loading={jobsLoading} /></div>
      </div>
    </div>
  </main>
}

export default DashboardPage

import { Link } from 'react-router-dom'
import type { Conversation, FileRecord, JobSummary, Role } from '../../types/api'
import { KNOWLEDGE_CLASSIFICATION } from '../shell/rank'

type MetricTone = 'accent' | 'success' | 'info' | 'warning'

const metricToneClasses: Record<MetricTone, string> = {
  accent: 'text-accent',
  success: 'text-success',
  info: 'text-info',
  warning: 'text-warning',
}

export function MetricTile({ label, value, note, tone = 'accent' }: { label: string; value: string | number; note: string; tone?: MetricTone }) {
  return <div className="work-panel min-w-0 px-4 py-5 sm:px-6 sm:py-6"><p className="font-mono text-[10px] uppercase tracking-[0.13em] text-muted-foreground">{label}</p><p className={`stat-number mt-6 text-[30px] leading-none tracking-[-0.06em] sm:text-[36px] ${metricToneClasses[tone]}`}>{value}</p><p className="mt-2 text-[11px] text-muted-foreground">{note}</p></div>
}

export function ActivityCard({ jobs, role, loading }: { jobs: JobSummary[]; role: Role; loading: boolean }) {
  return <section id="activity" className="work-panel p-5 sm:p-6"><div className="flex items-center justify-between gap-3"><div><p className="label-micro">{role === 'admin' ? 'Recent activity' : role === 'higher' ? 'Review & activity' : 'Your activity'}</p><h2 className="mt-2 text-base font-medium text-foreground">Recent operations</h2></div><Link to="/app/tasks" className="text-xs text-accent hover:underline">View tasks →</Link></div><div className="mt-5 divide-y divide-white/7">{jobs.length ? jobs.slice(0, 5).map((job) => <div key={job.job_id} className="flex items-start gap-3 py-3"><span className={`mt-1 size-2 shrink-0 rounded-full ${job.status === 'done' ? 'bg-success' : job.status === 'failed' ? 'bg-danger' : job.status === 'awaiting_approval' ? 'bg-warning' : 'bg-info'}`} /><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-foreground">{job.task}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{job.status.replaceAll('_', ' ')}{job.model_name ? ` · ${job.model_name}` : ''}</p></div><time dateTime={job.created_at} className="shrink-0 text-[10px] text-muted-foreground">{job.created_at ? new Date(job.created_at).toLocaleDateString() : '—'}</time></div>) : <p className="py-7 text-center text-xs text-muted-foreground">{loading ? 'Loading recent activity…' : 'No recent activity to display.'}</p>}</div><p className="mt-3 text-[10px] text-muted-foreground">Showing recent accessible jobs, not a system-wide audit log.</p></section>
}

export function ScopeCard({ role, files, conversations, jobs }: { role: Role; files: FileRecord[]; conversations: Conversation[]; jobs: JobSummary[] }) {
  const tierCounts = { admin: 0, higher: 0, lower: 0 }
  files.forEach((file) => { const tier = file.metadata.visibility_tier; if (tier && tier in tierCounts) tierCounts[tier as Role] += 1 })
  const verified = jobs.filter((job) => job.verification_passed).length
  const review = jobs.filter((job) => job.status === 'awaiting_approval').length
  return <section className="work-panel p-5 sm:p-6"><p className="label-micro">{role === 'admin' ? 'Workspace intelligence' : role === 'higher' ? 'Review scope' : 'Your workspace'}</p><h2 className="mt-2 text-base font-medium text-foreground">{role === 'admin' ? 'Operational snapshot' : role === 'higher' ? 'Accessible operations' : 'Pick up where you left off'}</h2><div className="mt-5 divide-y divide-white/7 text-xs"><div className="flex justify-between gap-4 py-3"><span className="text-muted-foreground">{role === 'lower' ? 'Available sessions' : 'Accessible sessions'}</span><span className="stat-number text-foreground">{conversations.length}</span></div><div className="flex justify-between gap-4 py-3"><span className="text-muted-foreground">{role === 'admin' ? 'Verified jobs' : 'Verified outcomes'}</span><span className="stat-number text-foreground">{verified}</span></div><div className="flex justify-between gap-4 py-3"><span className="text-muted-foreground">Awaiting approval in accessible runs</span><span className="stat-number text-foreground">{review}</span></div>{role === 'admin' ? <div className="flex justify-between gap-4 py-3"><span className="text-muted-foreground">Sources by classification</span><span className="stat-number text-right text-foreground">{KNOWLEDGE_CLASSIFICATION.admin}: {tierCounts.admin} · {KNOWLEDGE_CLASSIFICATION.higher}: {tierCounts.higher} · {KNOWLEDGE_CLASSIFICATION.lower}: {tierCounts.lower}</span></div> : <div className="flex justify-between gap-4 py-3"><span className="text-muted-foreground">Accessible sources</span><span className="stat-number text-foreground">{files.length}</span></div>}</div><div className="mt-5 flex flex-wrap gap-2"><Link to="/app/feed" className="action-primary px-3 py-2 text-[11px]">Start a session →</Link><Link to={role === 'higher' ? '/app/tasks?filter=review' : '/app/knowledge'} className="rounded-full border border-accent/25 bg-white/5 px-3 py-2 text-[11px] font-medium text-foreground transition-colors hover:bg-white/10">{role === 'higher' ? 'Open review queue' : 'Browse knowledge'}</Link></div></section>
}

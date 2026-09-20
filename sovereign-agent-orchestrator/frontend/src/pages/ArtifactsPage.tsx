import { useState } from 'react'
import type { FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useJob, useJobs } from '../hooks/useJob'
import ArtifactCard from '../components/shared/ArtifactCard'
import StatusPill from '../components/shared/StatusPill'
import IconTile from '../components/shared/IconTile'
import { fileVisual, relativeTime } from '../components/shared/fileVisual'
import { ArtifactsIcon, SearchIcon } from '../components/shell/icons'

function ArtifactsPage() {
  // Agent Tasks rows link here as /app/artifacts?job=<id>, so the page opens on the
  // job that was clicked instead of making the operator paste an id back in.
  const [searchParams, setSearchParams] = useSearchParams()
  const jobParam = searchParams.get('job') ?? ''
  const [jobId, setJobId] = useState(jobParam)
  const { job, error } = useJob(jobParam || undefined)
  const { jobs } = useJobs(100)
  const [layout, setLayout] = useState<'grid' | 'list'>('grid')

  // Re-sync the box when the URL changes under us (a row click elsewhere on the
  // page, or back/forward). Adjusted during render rather than in an effect --
  // the input is editable state, so it can't simply be derived, and an effect
  // would render the stale value once before correcting it.
  const [syncedParam, setSyncedParam] = useState(jobParam)
  if (jobParam !== syncedParam) {
    setSyncedParam(jobParam)
    setJobId(jobParam)
  }

  const withArtifacts = jobs.filter((summary) => (summary.artifacts ?? []).length > 0)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = jobId.trim()
    setSearchParams(trimmed ? { job: trimmed } : {}, { replace: true })
  }

  return (
    <div className="flex h-screen min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-5 border-b border-white/7 px-8 py-4">
        <div className="flex shrink-0 items-center gap-3.5">
          <ArtifactsIcon size={20} className="text-accent" />
          <h1 className="font-display text-[21px] leading-none font-medium text-foreground">Generated Artifacts</h1>
        </div>

        <form onSubmit={submit} className="flex min-w-0 flex-1 items-center justify-end gap-3">
          <label className="border-hairline flex min-w-0 max-w-md flex-1 items-center gap-2.5 rounded-xl bg-surface px-4 py-2.5 focus-within:border-accent/40">
            <SearchIcon size={15} className="shrink-0 text-muted-foreground" />
            <input
              value={jobId}
              onChange={(event) => setJobId(event.target.value)}
              placeholder="Look up by job ID"
              aria-label="Job ID"
              className="min-w-0 flex-1 bg-transparent font-mono text-[13px] text-foreground outline-none placeholder:font-sans placeholder:text-muted-foreground"
            />
          </label>
          <div className="flex shrink-0 gap-1 rounded-lg bg-surface p-1">
            {(['grid', 'list'] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setLayout(option)}
                className={`label-micro rounded-md px-3 py-1.5 transition ${
                  layout === option ? 'bg-surface-raised text-foreground' : 'hover:text-foreground'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </form>
      </header>

      <main className="scroll-slim min-h-0 flex-1 overflow-y-auto px-8 py-8">
        {error ? <p className="text-xs text-danger">{error.message}</p> : null}

        {job ? (
          <section>
            <div className="border-hairline flex items-center gap-4 rounded-2xl bg-surface px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <p className="truncate text-[15px] font-semibold text-foreground">{job.task}</p>
                  <StatusPill status={job.status} />
                </div>
                <p className="mt-1 font-mono text-[12px] text-muted-foreground">{job.job_id}</p>
              </div>
            </div>

            {job.artifacts.length === 0 ? (
              <p className="mt-5 text-sm text-muted-foreground">This job produced no artifacts.</p>
            ) : (
              <div className={`mt-6 ${layout === 'grid' ? 'grid grid-cols-1 gap-7 sm:grid-cols-2 2xl:grid-cols-3' : 'flex max-w-3xl flex-col gap-2.5'}`}>
                {job.artifacts.map((artifact) => (
                  <ArtifactCard
                    key={artifact.artifact_id}
                    jobId={job.job_id}
                    artifact={artifact}
                    layout={layout === 'grid' ? 'preview' : 'list'}
                  />
                ))}
              </div>
            )}
          </section>
        ) : null}

        <section className={job ? 'mt-12' : ''}>
          <h2 className="font-display text-[19px] font-medium text-foreground">
            {job ? 'Other Sessions' : 'Recent Deliverables'}
          </h2>
          <p className="mt-2 text-[13px] text-muted-foreground">
            Every job that produced a downloadable file. Artifacts also appear inline on the Intelligence Feed as each job finishes.
          </p>

          <div className="mt-5 flex flex-col gap-3">
            {withArtifacts.length === 0 ? (
              <div className="border-hairline rounded-2xl bg-surface px-6 py-12 text-center">
                <p className="text-sm text-muted-foreground">No artifacts generated yet.</p>
              </div>
            ) : null}

            {withArtifacts
              .filter((summary) => summary.job_id !== job?.job_id)
              .map((summary) => {
                const visual = fileVisual(summary.artifacts[0]?.name ?? '')
                return (
                  <button
                    key={summary.job_id}
                    type="button"
                    onClick={() => setSearchParams({ job: summary.job_id }, { replace: true })}
                    className="border-hairline flex w-full items-center gap-4 rounded-2xl bg-surface px-5 py-4 text-left transition-colors hover:border-white/14 hover:bg-surface-raised"
                  >
                    <IconTile tone={visual.tone} size={42}>
                      <visual.Icon size={19} />
                    </IconTile>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[15px] font-semibold text-foreground">{summary.task}</p>
                      <p className="mt-1 truncate text-[13px] text-muted-foreground">
                        {summary.artifacts.map((artifact) => artifact.name).join(' · ')}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="label-micro">Generated</p>
                      <p className="mt-1 text-[13px] font-semibold text-foreground">{relativeTime(summary.created_at)}</p>
                    </div>
                  </button>
                )
              })}
          </div>
        </section>
      </main>
    </div>
  )
}

export default ArtifactsPage

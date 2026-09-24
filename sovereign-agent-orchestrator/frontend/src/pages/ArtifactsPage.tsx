import { useState } from 'react'
import { useJob, useJobs } from '../hooks/useJob'
import ArtifactCard from '../components/shared/ArtifactCard'

function ArtifactsPage() {
  const { jobs, error: jobsError, isLoading } = useJobs(100)
  const withArtifacts = jobs.filter((job) => job.artifacts?.length)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const activeJobId = selectedId ?? withArtifacts[0]?.job_id ?? null
  const { job, error } = useJob(activeJobId)
  const [layout, setLayout] = useState<'grid' | 'list'>('list')

  return (
    <main className="app-page flex-1 overflow-y-auto px-4 py-7 sm:px-8 sm:py-9 xl:px-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="label-micro mb-3 text-accent">05 / Deliverables</p><h1 className="text-3xl font-medium tracking-[-0.04em] text-foreground">Generated Artifacts<span className="text-accent">.</span></h1>
          <p className="mt-1 text-xs text-muted-foreground">Outputs from your recent tasks. Select a task to see its files.</p>
        </div>
        <div className="flex gap-1 rounded-full border border-accent/20 bg-fill p-1" role="group" aria-label="Layout">
          <button type="button" aria-pressed={layout === 'list'} onClick={() => setLayout('list')} className={`label-micro rounded-full px-3 py-1.5 ${layout === 'list' ? 'bg-accent/20 text-foreground' : 'text-muted-foreground'}`}>List</button>
          <button type="button" aria-pressed={layout === 'grid'} onClick={() => setLayout('grid')} className={`label-micro rounded-full px-3 py-1.5 ${layout === 'grid' ? 'bg-accent/20 text-foreground' : 'text-muted-foreground'}`}>Grid</button>
        </div>
      </div>

      {jobsError ? <p role="alert" className="mt-5 text-sm text-danger">Recent tasks could not be loaded.</p> : null}
      {isLoading ? <p className="mt-5 text-sm text-muted-foreground">Loading recent tasks…</p> : null}
      {!isLoading && !jobsError && withArtifacts.length === 0 ? <p className="mt-5 text-sm text-muted-foreground">No recent tasks have produced artifacts yet.</p> : null}

      {withArtifacts.length ? (
        <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
          <nav aria-label="Tasks with artifacts" className="flex flex-col gap-1.5">
            {withArtifacts.map((item) => (
              <button
                key={item.job_id}
                type="button"
                aria-current={item.job_id === activeJobId ? 'true' : undefined}
                onClick={() => setSelectedId(item.job_id)}
                className={`work-panel px-3 py-2.5 text-left transition-colors ${item.job_id === activeJobId ? 'border-accent/50 !bg-accent/15' : 'hover:border-accent/30'}`}
              >
                <span className="block truncate text-sm text-foreground">{item.task}</span>
                <span className="label-micro mt-1 block">{item.artifacts.length} file{item.artifacts.length === 1 ? '' : 's'}{item.created_at ? ` · ${new Date(item.created_at).toLocaleDateString()}` : ''}</span>
              </button>
            ))}
          </nav>

          <section aria-label="Artifacts" className="min-w-0">
            {error ? <p role="alert" className="text-xs text-danger">{error.message}</p> : null}
            {!job && !error ? <p className="text-sm text-muted-foreground">Loading artifacts…</p> : null}
            {job?.artifacts?.length ? (
              <div className={layout === 'grid' ? 'grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3' : 'flex flex-col gap-2'}>
                {job.artifacts.map((artifact) => (
                  <ArtifactCard key={artifact.artifact_id} jobId={job.job_id} artifact={artifact} layout={layout} />
                ))}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </main>
  )
}

export default ArtifactsPage

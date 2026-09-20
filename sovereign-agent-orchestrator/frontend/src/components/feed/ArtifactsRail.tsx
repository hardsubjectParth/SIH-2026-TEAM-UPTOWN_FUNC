import { useState } from 'react'
import ArtifactCard from '../shared/ArtifactCard'
import { useAuth } from '../../context/AuthContext'
import { downloadArtifact } from '../../services/api'
import { formatSize } from '../shared/fileVisual'
import { ArtifactsIcon } from '../shell/icons'
import type { JobArtifact } from '../../types/api'

export type RailArtifact = { jobId: string; artifact: JobArtifact; generatedAt?: string }

// Everything this session has produced, newest job first.

function ArtifactsRail({ artifacts, busy }: { artifacts: RailArtifact[]; busy?: boolean }) {
  const { token } = useAuth()
  const [downloading, setDownloading] = useState(false)
  const totalBytes = artifacts.reduce((sum, item) => sum + (item.artifact.size_bytes ?? 0), 0)

  // Sequential, not parallel: each download is an authenticated fetch of a whole
  // file out of the job workspace, and a burst of them trips the API rate limiter.
  async function downloadAll() {
    if (!token || downloading) return
    setDownloading(true)
    try {
      for (const { jobId, artifact } of artifacts) {
        const blob = await downloadArtifact(jobId, artifact.name, token)
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = artifact.name
        anchor.click()
        URL.revokeObjectURL(url)
      }
    } finally {
      setDownloading(false)
    }
  }

  return (
    <aside className="hidden h-screen w-[360px] shrink-0 flex-col border-l border-white/7 bg-black/20 xl:flex">
      <header className="flex shrink-0 items-center justify-between border-b border-white/7 px-6 py-[18px]">
        <div className="flex items-center gap-3">
          <ArtifactsIcon size={18} className="text-accent" />
          <h2 className="font-display text-[17px] leading-none font-medium text-foreground">Generated Artifacts</h2>
        </div>
        <button
          type="button"
          onClick={downloadAll}
          disabled={artifacts.length === 0 || downloading}
          className="label-micro text-accent transition hover:text-foreground disabled:opacity-35"
        >
          {downloading ? 'Downloading…' : 'Download All'}
        </button>
      </header>

      <div className="scroll-slim min-h-0 flex-1 overflow-y-auto px-6 py-6">
        {artifacts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center px-4 text-center">
            <ArtifactsIcon size={30} className="text-white/12" />
            <p className="mt-4 text-[13px] text-muted-foreground">
              {busy ? 'The agent is still working — artifacts appear here as they are produced.' : 'No artifacts in this session yet.'}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-7">
            {artifacts.map((item) => (
              <ArtifactCard
                key={`${item.jobId}-${item.artifact.artifact_id ?? item.artifact.name}`}
                jobId={item.jobId}
                artifact={item.artifact}
                generatedAt={item.generatedAt}
                layout="preview"
              />
            ))}
          </div>
        )}
      </div>

      {/* The mockup's "1/5 export slots" has no counterpart in this backend -- there is
          no export quota -- so the footer reports what the session actually holds. */}
      <div className="shrink-0 border-t border-white/7 px-6 py-5">
        <div className="flex items-baseline justify-between">
          <span className="label-micro">Session Artifacts</span>
          <span className="label-micro text-foreground">
            {artifacts.length} {artifacts.length === 1 ? 'file' : 'files'}
            {totalBytes > 0 ? ` · ${formatSize(totalBytes)}` : ''}
          </span>
        </div>
        <p className="mt-3 text-center text-[12px] text-muted-foreground italic">
          Artifacts are served from the job workspace, never a host path.
        </p>
      </div>
    </aside>
  )
}

export default ArtifactsRail

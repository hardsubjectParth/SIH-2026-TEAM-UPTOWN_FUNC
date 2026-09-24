import { useState } from 'react'
import { downloadArtifact } from '../../services/api'
import type { JobArtifact } from '../../types/api'
import { useAuth } from '../../context/AuthContext'

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function relativeTime(iso?: string) {
  if (!iso) return null
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

type ArtifactCardProps = {
  jobId: string
  artifact: JobArtifact
  generatedAt?: string
  layout?: 'list' | 'grid'
}

function ArtifactCard({ jobId, artifact, generatedAt, layout = 'list' }: ArtifactCardProps) {
  const { token } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const typeTag = (artifact.name.split('.').pop() || '').toUpperCase()
  const generated = relativeTime(generatedAt)

  async function download() {
    if (!token) return
    setError(null)
    try {
      const blob = await downloadArtifact(jobId, artifact.name, token)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = artifact.name
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Download failed')
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={download}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); download() } }}
      className={`border-hairline group cursor-pointer rounded-2xl bg-surface px-3.5 py-3 transition-colors hover:border-accent/60 ${layout === 'grid' ? '' : 'flex items-center justify-between gap-4'}`}
    >
      <div className="min-w-0">
        <p className="truncate font-mono text-sm text-foreground">{artifact.name}</p>
        <div className="mt-1 flex items-center gap-2">
          <span className="label-micro">{typeTag}</span>
          <span className="text-xs text-muted-foreground">{formatSize(artifact.size_bytes)}</span>
          {generated ? <span className="text-xs text-muted-foreground">· Generated {generated}</span> : null}
        </div>
        {error ? <p className="mt-1 text-xs text-danger">{error}</p> : null}
      </div>
      {/* Always visible. This was `opacity-0 group-hover:opacity-100`, which left the
          card looking like inert text until you happened to hover it -- nothing said
          the row was the download control. */}
      <span aria-hidden="true" className={`flex shrink-0 items-center gap-1.5 rounded-full border border-rule px-3 py-1.5 text-xs text-muted-foreground transition-colors group-hover:border-accent/50 group-hover:text-accent ${layout === 'grid' ? 'mt-3 w-fit' : ''}`}>
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2.5v8" /><path d="M4.5 7.5 8 11l3.5-3.5" /><path d="M2.75 13.25h10.5" /></svg>
        Download
      </span>
    </div>
  )
}

export default ArtifactCard

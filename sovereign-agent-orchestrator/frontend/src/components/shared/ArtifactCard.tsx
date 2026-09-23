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
      onKeyDown={(event) => { if (event.key === 'Enter') download() }}
      className={`border-hairline group cursor-pointer bg-surface px-3.5 py-3 transition-colors hover:border-accent/60 ${layout === 'grid' ? '' : 'flex items-center justify-between gap-4'}`}
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
      <span className="label-micro shrink-0 text-accent opacity-0 transition-opacity group-hover:opacity-100">Download</span>
    </div>
  )
}

export default ArtifactCard

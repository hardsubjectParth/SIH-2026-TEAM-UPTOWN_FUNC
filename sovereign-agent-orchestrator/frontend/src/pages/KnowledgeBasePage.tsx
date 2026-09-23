import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useFiles, useDeleteFile } from '../hooks/useFiles'
import { useKnowledgeSearch } from '../hooks/useKnowledgeSearch'
import TierLabel from '../components/shared/TierLabel'
import { useAuth } from '../context/AuthContext'

function formatSize(bytes?: number) {
  if (!bytes || bytes <= 0) return 'Unknown size'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function relativeTime(iso?: string) {
  if (!iso) return 'unknown'
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function KnowledgeBasePage() {
  const { user } = useAuth()
  const { files, mutate } = useFiles()
  const deleteFile = useDeleteFile()
  const { results, search, searching } = useKnowledgeSearch()
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sorted = [...files].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))

  async function remove(fileId: string, name: string) {
    if (!window.confirm(`Delete "${name}"? It will be removed from search for everyone who can access it.`)) return
    setBusyId(fileId)
    setError(null)
    try {
      await deleteFile(fileId)
      mutate()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to delete document')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="app-page flex-1 overflow-y-auto px-4 py-7 sm:px-8 sm:py-9 xl:px-12">
      <div className="flex items-center justify-between">
        <div><p className="label-micro mb-3 text-accent">04 / Knowledge register</p><h1 className="text-3xl font-medium tracking-[-0.04em] text-foreground">Organizational Knowledge<span className="text-accent">.</span></h1></div>
        <Link to="/app/knowledge/ingest" className="action-primary px-4 py-2 text-xs">Add document</Link>
      </div>

      <form
        onSubmit={(event) => { event.preventDefault(); if (query.trim()) search(query.trim()) }}
        className="work-panel mt-7 flex max-w-xl items-center gap-2 px-3 py-2"
      >
        <input
          aria-label="Search knowledge"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search knowledge..."
          className="flex-1 bg-transparent py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
        <button type="submit" disabled={searching} className="action-primary px-3 py-1.5 text-xs">
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>

      {results.length > 0 ? (
        <div className="mt-4 flex max-w-xl flex-col gap-2">
          {results.map((hit, index) => (
            <div key={index} className="work-panel px-4 py-3">
              <div className="flex items-center justify-between">
                <p className="text-sm text-foreground">{hit.metadata.name ?? 'Knowledge result'}</p>
                <span className="stat-number text-xs text-accent">{hit.score.toFixed(2)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{hit.content}</p>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-8">
        <div className="flex items-center justify-between">
          <p className="label-micro">{user?.role === 'admin' ? 'All workspace documents' : 'Documents you uploaded'}</p>
          <p className="label-micro">Sort by: Recent</p>
        </div>

        {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

        <div className="mt-3 flex flex-col gap-2">
          {sorted.length === 0 ? <p className="text-sm text-muted-foreground">No documents uploaded yet.</p> : null}
          {sorted.map((file) => (
            <div key={file.id} className="work-panel px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1 basis-48">
                  <p className="truncate text-sm text-foreground">{file.name}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Modified {relativeTime(file.created_at)} · {formatSize(file.metadata.size_bytes)}
                  </p>
                </div>
                <TierLabel tier={file.metadata.visibility_tier ?? 'unknown'} />
                <div className="flex shrink-0 items-center gap-3">
                  <button type="button" aria-expanded={expanded === file.id} onClick={() => setExpanded(expanded === file.id ? null : file.id)} className="label-micro text-accent hover:underline">
                    Details
                  </button>
                  <button type="button" disabled={busyId === file.id} onClick={() => remove(file.id, file.name)} className="label-micro text-danger hover:underline disabled:opacity-50">
                    {busyId === file.id ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              </div>

              {expanded === file.id ? (
                <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/8 pt-3 text-xs">
                  <div><span className="text-muted-foreground">File ID</span><p className="font-mono text-foreground">{file.id}</p></div>
                  <div><span className="text-muted-foreground">Type</span><p className="text-foreground">{file.metadata.mime_type ?? 'Unknown'}</p></div>
                  <div><span className="text-muted-foreground">Size</span><p className="text-foreground">{formatSize(file.metadata.size_bytes)}</p></div>
                  <div><span className="text-muted-foreground">Uploaded</span><p className="text-foreground">{file.created_at ? new Date(file.created_at).toLocaleString() : 'Unknown'}</p></div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </main>
  )
}

export default KnowledgeBasePage

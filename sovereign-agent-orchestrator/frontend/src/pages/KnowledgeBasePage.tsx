import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useFiles, useDeleteFile } from '../hooks/useFiles'
import { useKnowledgeSearch } from '../hooks/useKnowledgeSearch'
import TierLabel from '../components/shared/TierLabel'
import IconTile from '../components/shared/IconTile'
import { fileVisual, formatSize, relativeTime } from '../components/shared/fileVisual'
import IngestPanel from '../components/knowledge/IngestPanel'
import { KnowledgeIcon, SearchIcon, ChevronDownIcon } from '../components/shell/icons'

type SortKey = 'recent' | 'name' | 'size'

function KnowledgeBasePage() {
  const { files, mutate } = useFiles()
  const deleteFile = useDeleteFile()
  const { results, search, searching } = useKnowledgeSearch()
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('recent')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sorted = [...files].sort((a, b) => {
    if (sort === 'name') return a.name.localeCompare(b.name)
    if (sort === 'size') return (b.metadata.size_bytes ?? 0) - (a.metadata.size_bytes ?? 0)
    return (b.created_at ?? '').localeCompare(a.created_at ?? '')
  })

  async function revoke(fileId: string) {
    setBusyId(fileId)
    setError(null)
    try {
      await deleteFile(fileId)
      mutate()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to revoke access')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex h-screen min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-5 border-b border-white/7 px-8 py-4">
          <div className="flex shrink-0 items-center gap-3.5">
            <KnowledgeIcon size={20} className="text-accent" />
            <h1 className="font-display text-[21px] leading-none font-medium whitespace-nowrap text-foreground">
              Organizational Knowledge
            </h1>
          </div>

          <form
            onSubmit={(event) => { event.preventDefault(); search(query) }}
            className="flex min-w-0 flex-1 items-center gap-3"
          >
            <label className="border-hairline flex min-w-0 flex-1 items-center gap-2.5 rounded-xl bg-surface px-4 py-2.5 focus-within:border-accent/40">
              <SearchIcon size={15} className="shrink-0 text-muted-foreground" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search knowledge..."
                aria-label="Search knowledge"
                className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
            </label>
            <button
              type="submit"
              disabled={searching}
              className="shrink-0 rounded-xl bg-primary px-5 py-2.5 text-[11px] font-semibold tracking-[0.12em] text-primary-foreground uppercase transition hover:bg-primary-hover disabled:opacity-60"
            >
              {searching ? 'Searching…' : 'Search All'}
            </button>
          </form>

          {/* Below xl the ingest rail is hidden, so this is the only route to it. */}
          <Link
            to="/app/knowledge/ingest"
            className="label-micro shrink-0 text-accent transition hover:text-foreground xl:hidden"
          >
            Ingest →
          </Link>
        </header>

        <main className="scroll-slim min-h-0 flex-1 overflow-y-auto px-8 py-8">
          {results.length > 0 ? (
            <section className="mb-10">
              <h2 className="font-display text-[17px] font-medium text-foreground">Retrieved Evidence</h2>
              <div className="mt-4 flex flex-col gap-2.5">
                {results.map((hit, index) => (
                  <div key={index} className="border-hairline rounded-2xl bg-surface px-5 py-4">
                    <div className="flex items-center justify-between gap-4">
                      <p className="truncate text-sm font-semibold text-foreground">
                        {hit.metadata.source_name ?? hit.metadata.name ?? 'Knowledge result'}
                      </p>
                      <span className="stat-number shrink-0 text-xs text-accent">{hit.score.toFixed(2)}</span>
                    </div>
                    <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-muted-foreground">{hit.content}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-[19px] font-medium text-foreground">Accessible Documents</h2>
            <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
              Sort by:
              <span className="relative flex items-center">
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as SortKey)}
                  className="appearance-none bg-transparent py-1 pr-6 pl-1 text-[13px] font-medium text-foreground outline-none"
                >
                  <option value="recent">Recent</option>
                  <option value="name">Name</option>
                  <option value="size">Size</option>
                </select>
                <ChevronDownIcon size={14} className="pointer-events-none absolute right-0 text-muted-foreground" />
              </span>
            </label>
          </div>

          {error ? <p className="mt-3 text-xs text-danger">{error}</p> : null}

          {sorted.length === 0 ? (
            <div className="border-hairline mt-5 rounded-2xl bg-surface px-6 py-14 text-center">
              <p className="text-sm text-muted-foreground">
                No documents ingested yet. Drop a file into the ingest panel to index it.
              </p>
            </div>
          ) : null}

          <div className="mt-5 grid grid-cols-1 gap-4 2xl:grid-cols-2">
            {sorted.map((file, index) => {
              const visual = fileVisual(file.name)
              const isOpen = expanded === file.id
              return (
                <motion.div
                  key={file.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index, 8) * 0.03, duration: 0.25 }}
                  className="border-hairline rounded-2xl bg-surface px-5 py-4 transition-colors hover:border-white/14"
                >
                  <div className="flex items-start gap-4">
                    <IconTile tone={visual.tone} size={44}>
                      <visual.Icon size={20} />
                    </IconTile>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2.5">
                        <p className="min-w-0 flex-1 truncate text-[15px] font-semibold text-foreground" title={file.name}>
                          {file.name}
                        </p>
                        <TierLabel tier={file.metadata.visibility_tier ?? 'unknown'} />
                      </div>
                      <p className="mt-1 text-[13px] text-muted-foreground">
                        Modified {relativeTime(file.created_at)} · {formatSize(file.metadata.size_bytes)}
                      </p>

                      <div className="mt-3.5 flex items-center gap-5">
                        <button
                          type="button"
                          onClick={() => setExpanded(isOpen ? null : file.id)}
                          aria-expanded={isOpen}
                          className="label-micro text-foreground transition hover:text-accent"
                        >
                          View
                        </button>
                        <button
                          type="button"
                          onClick={() => setExpanded(isOpen ? null : file.id)}
                          className="label-micro transition hover:text-foreground"
                        >
                          Details
                        </button>
                        <button
                          type="button"
                          disabled={busyId === file.id}
                          onClick={() => revoke(file.id)}
                          className="label-micro ml-auto text-danger transition hover:brightness-125 disabled:opacity-50"
                        >
                          {busyId === file.id ? 'Revoking…' : 'Revoke'}
                        </button>
                      </div>
                    </div>
                  </div>

                  {isOpen ? (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      className="mt-4 grid grid-cols-2 gap-3 overflow-hidden border-t border-white/7 pt-4 text-xs"
                    >
                      <div><span className="text-muted-foreground">File ID</span><p className="mt-0.5 font-mono break-all text-foreground">{file.id}</p></div>
                      <div><span className="text-muted-foreground">Type</span><p className="mt-0.5 text-foreground">{file.metadata.mime_type ?? 'Unknown'}</p></div>
                      <div><span className="text-muted-foreground">Size</span><p className="mt-0.5 text-foreground">{formatSize(file.metadata.size_bytes)}</p></div>
                      <div><span className="text-muted-foreground">Uploaded</span><p className="mt-0.5 text-foreground">{file.created_at ? new Date(file.created_at).toLocaleString() : 'Unknown'}</p></div>
                    </motion.div>
                  ) : null}
                </motion.div>
              )
            })}
          </div>
        </main>
      </div>

      <aside className="hidden h-screen w-[380px] shrink-0 flex-col border-l border-white/7 bg-black/20 xl:flex">
        <header className="shrink-0 border-b border-white/7 px-6 py-[18px]">
          <h2 className="font-display text-[19px] leading-none font-medium text-foreground">Ingest Knowledge</h2>
        </header>
        <IngestPanel onIngested={() => mutate()} />
      </aside>
    </div>
  )
}

export default KnowledgeBasePage

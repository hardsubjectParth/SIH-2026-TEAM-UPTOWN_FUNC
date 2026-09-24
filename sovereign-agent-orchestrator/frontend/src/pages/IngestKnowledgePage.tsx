import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useFileScopes, useUploadFile } from '../hooks/useFiles'
import { useAuth } from '../context/AuthContext'
import { SUPPORTED_UPLOAD_TYPES } from '../components/feed/Composer'
import type { Role } from '../types/api'

// Display copy only. The server resolves scope -> classification from the caller's
// verified role (app/access.py::UPLOAD_SCOPES) and rejects scopes the role doesn't have.
const SCOPE_COPY: Record<Role, Record<string, { label: string; description: string }>> = {
  admin: {
    private: { label: 'Confidential', description: 'Readable by Workspace Administrators only.' },
    everyone: { label: 'Shared', description: 'Readable by every role in the workspace.' },
  },
  higher: {
    restricted: { label: 'Restricted', description: 'Readable by Operations Reviewers and Workspace Administrators.' },
    everyone: { label: 'Shared', description: 'Readable by every role in the workspace.' },
  },
  lower: {
    private: { label: 'Shared', description: 'Readable by every role in the workspace. Operations Analysts can only upload shared knowledge.' },
  },
}

const SUPPORTED_LABEL = 'PDF, DOCX, PPTX, XLSX, CSV, TXT, MD and images (PNG, JPG, TIFF, BMP)'

function IngestKnowledgePage() {
  const { user } = useAuth()
  const role = user?.role ?? 'lower'
  const { scopes, error: scopesError, isLoading: scopesLoading } = useFileScopes()
  const upload = useUploadFile()
  const [file, setFile] = useState<File | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const [scope, setScope] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  useEffect(() => {
    if (!scope && scopes.length) setScope(scopes[0])
  }, [scopes, scope])

  function selectFile(next: File | null) {
    setFile(next)
    setError(null)
    setSuccess(null)
  }

  async function beginIngestion() {
    if (!file || !scope) return
    setUploading(true)
    setError(null)
    setSuccess(null)
    try {
      await upload(file, scope)
      setSuccess(`${file.name} was added to the knowledge base.`)
      setFile(null)
      setInputKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <main className="app-page flex-1 overflow-y-auto px-4 py-7 sm:px-8 sm:py-9 xl:px-12">
      <p className="label-micro mb-3 text-accent">04 / Knowledge register</p>
      <h1 className="text-3xl font-medium tracking-[-0.04em] text-foreground">Add Knowledge<span className="text-accent">.</span></h1>
      <p className="mt-2 text-sm text-muted-foreground">Upload a document and choose who can access it.</p>

      <div className="mt-6 flex max-w-2xl flex-col gap-6">
        <label
          onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            const dropped = event.dataTransfer.files?.[0]
            if (dropped) selectFile(dropped)
          }}
          className={`flex h-48 cursor-pointer flex-col items-center justify-center rounded-[20px] border border-dashed px-6 text-center transition-colors focus-within:border-accent ${dragOver ? 'border-accent bg-accent/5' : 'border-rule-strong hover:border-accent/50 hover:bg-fill'}`}
        >
          <input key={inputKey} type="file" accept={SUPPORTED_UPLOAD_TYPES} className="sr-only" onChange={(event) => selectFile(event.target.files?.[0] ?? null)} />
          <svg aria-hidden="true" viewBox="0 0 24 24" width="26" height="26" className={dragOver ? 'text-accent' : 'text-muted-foreground'} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4" /><path d="m7.5 8.5 4.5-4.5 4.5 4.5" /><path d="M3.5 15v3.5a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2V15" /></svg>
          <span className="mt-3 text-sm text-foreground">{file ? file.name : 'Drop a file here or click to browse'}</span>
          <span className="mt-2 max-w-sm text-xs leading-relaxed text-muted-foreground">{SUPPORTED_LABEL}</span>
        </label>

        <fieldset>
          <legend className="label-micro mb-2">Classification</legend>
          <p className="mb-3 text-xs text-muted-foreground">Available options depend on your role. The server enforces them.</p>
          {scopesLoading ? <p className="text-xs text-muted-foreground">Loading options…</p> : null}
          {scopesError ? <p role="alert" className="text-xs text-danger">Classification options could not be loaded.</p> : null}
          <div className="flex flex-col gap-2">
            {scopes.map((scopeOption) => {
              const copy = SCOPE_COPY[role][scopeOption]
              return (
                <label key={scopeOption} className="work-panel flex cursor-pointer items-start gap-3 px-3.5 py-3 has-[:checked]:border-accent/50 has-[:checked]:bg-[#4b3034]/40">
                  <input type="radio" name="scope" checked={scope === scopeOption} onChange={() => setScope(scopeOption)} className="mt-0.5 accent-[var(--color-accent)]" />
                  <span>
                    <span className="block text-sm text-foreground">{copy?.label ?? scopeOption}</span>
                    <span className="block text-xs text-muted-foreground">{copy?.description ?? 'Classification is determined by the server.'}</span>
                  </span>
                </label>
              )
            })}
          </div>
        </fieldset>

        {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
        {success ? <p role="status" className="text-xs text-accent">{success}</p> : null}

        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={beginIngestion}
            disabled={!file || !scope || uploading}
            className="action-primary px-4 py-2.5 text-sm"
          >
            {uploading ? 'Uploading…' : 'Upload document'}
          </button>
          <Link to="/app/knowledge" className="text-xs text-accent hover:underline">View knowledge base →</Link>
        </div>
      </div>
    </main>
  )
}

export default IngestKnowledgePage

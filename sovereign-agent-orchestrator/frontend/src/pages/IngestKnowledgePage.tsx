import { useNavigate } from 'react-router-dom'
import { mutate as globalMutate } from 'swr'
import IngestPanel from '../components/knowledge/IngestPanel'
import { useAuth } from '../context/AuthContext'
import { KnowledgeIcon } from '../components/shell/icons'

// On wide viewports ingest lives in the Knowledge Base's right rail. This route is
// the same panel standing alone -- the narrow-viewport path (where that rail is
// hidden) and a direct deep link both land here.
function IngestKnowledgePage() {
  const navigate = useNavigate()
  const { token } = useAuth()

  return (
    <div className="flex h-screen min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-white/7 px-8 py-[18px]">
        <div className="flex items-center gap-3.5">
          <KnowledgeIcon size={20} className="text-accent" />
          <h1 className="font-display text-[21px] leading-none font-medium text-foreground">Ingest Knowledge</h1>
        </div>
        <button
          type="button"
          onClick={() => navigate('/app/knowledge')}
          className="label-micro text-accent transition hover:text-foreground"
        >
          View Knowledge Base →
        </button>
      </header>

      <div className="mx-auto min-h-0 w-full max-w-[520px] flex-1">
        <IngestPanel onIngested={() => globalMutate(['files', token])} />
      </div>
    </div>
  )
}

export default IngestKnowledgePage

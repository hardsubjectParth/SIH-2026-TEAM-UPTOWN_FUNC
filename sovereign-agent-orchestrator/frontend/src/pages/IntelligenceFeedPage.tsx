import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { mutate as globalMutate } from 'swr'
import { useAuth } from '../context/AuthContext'
import { useConversation } from '../hooks/useConversations'
import { useJob, useJobEvents, useJobs } from '../hooks/useJob'
import { sendChatMessage, uploadFile } from '../services/api'
import Composer from '../components/feed/Composer'
import ActivityTimeline from '../components/feed/ActivityTimeline'
import MetricsCard from '../components/feed/MetricsCard'
import ApprovalGate from '../components/feed/ApprovalGate'
import ArtifactCard from '../components/shared/ArtifactCard'
import { STATUS_LABEL } from '../components/shared/StatusDot'
import StatusDot from '../components/shared/StatusDot'
import BrandLogo from '../components/shell/BrandLogo'

const TERMINAL_STATUSES = ['done', 'failed', 'cancelled']

function IntelligenceFeedPage() {
  const { id: routeId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { token } = useAuth()
  const { conversation, messages, mutate: mutateConversation } = useConversation(routeId)

  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pendingTask, setPendingTask] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Perf guardrail: a long-running session shouldn't keep every turn mounted forever.
  // Not full virtualization (no windowing library added for this) -- just a hard cap
  // with a manual "show earlier" expansion, which is enough to keep the DOM bounded.
  const [visibleCount, setVisibleCount] = useState(50)

  const { jobs } = useJobs(100)

  // Restores fc84ea4, which the console redesign (281df2d) dropped when it rewrote
  // this file. pendingTask lives in component state, so a reload -- or simply
  // reopening an older conversation -- left the turn with no pipeline at all, which
  // from the outside is indistinguishable from the run having vanished. There is no
  // server-side pointer from a conversation to its current job, but GET /agent carries
  // conversation_id on every job, so the conversation's most recent job is recoverable.
  const resumableJobId = useMemo(() => {
    if (!routeId) return null
    const mine = jobs.filter((summary) => summary.conversation_id === routeId)
    if (mine.length === 0) return null
    return [...mine].sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))[0].job_id
  }, [jobs, routeId])

  const trackedJobId = activeJobId ?? resumableJobId
  const { job } = useJob(trackedJobId)
  const { events } = useJobEvents(trackedJobId)
  const scrollRef = useRef<HTMLDivElement>(null)

  // App.tsx keys <Routes> by location.pathname, so sending from /app/feed
  // remounts this page when it navigates to the new conversation -- component state and
  // refs are both discarded. Nothing in here can carry a turn across that, which is why
  // liveness below is derived from the job's own status rather than from pendingTask.
  useEffect(() => {
    setActiveJobId(null)
    setPendingTask(null)
    setVisibleCount(50)
  }, [routeId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, job?.status, job?.final_answer, events.length])

  useEffect(() => {
    if (job && (job.status === 'done' || job.status === 'failed' || job.status === 'cancelled')) {
      mutateConversation()
    }
  }, [job?.status])

  async function handleSend(task: string, files: File[]) {
    if (!token) return false
    setSubmitting(true)
    setError(null)
    try {
      const uploadedFileIds: string[] = []
      for (const file of files) {
        const uploaded = await uploadFile(file, undefined, token)
        uploadedFileIds.push(uploaded.file_id)
      }
      const isNewConversation = !routeId
      const response = await sendChatMessage(task, token, routeId, uploadedFileIds)
      setActiveJobId(response.data.job_id)
      setPendingTask(task)
      if (isNewConversation) {
        globalMutate(['conversations', token])
        navigate(`/app/feed/${response.data.conversation_id}`, { replace: true })
      } else {
        mutateConversation()
      }
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to submit task')
      return false
    } finally {
      setSubmitting(false)
    }
  }

  // Persisted messages already include the turn we just sent once the GET catches up
  // (the backend writes the user message synchronously before /chat returns). Hide the
  // trailing user message here only while it still exactly matches our own pending
  // turn, so it renders exactly once -- via the live panel below, not duplicated.
  const hideTrailingUser = pendingTask && messages.length > 0 && messages[messages.length - 1].role === 'user' && messages[messages.length - 1].content === pendingTask
  const allHistoryMessages = hideTrailingUser ? messages.slice(0, -1) : messages
  const hiddenCount = Math.max(0, allHistoryMessages.length - visibleCount)
  const historyMessages = hiddenCount > 0 ? allHistoryMessages.slice(-visibleCount) : allHistoryMessages

  // A run still moving through the pipeline is the current turn, whether or not this
  // page instance was the one that submitted it.
  const isLive = Boolean(pendingTask) || Boolean(job && !TERMINAL_STATUSES.includes(job.status))

  return (
    <div className="app-page flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-4 border-b border-rule px-4 py-4 sm:px-8">
        <span className="font-mono text-[10px] text-accent">02 /</span><h1 className="truncate text-sm font-medium text-foreground">{conversation?.title ?? 'New Session'}</h1>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 pb-10 sm:px-6">
        {historyMessages.length === 0 && !pendingTask ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <BrandLogo variant="mark" className="w-9" />
            <h3 className="mt-5 text-lg font-medium text-foreground">What can I help you with?</h3>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">Instruct Sovereign Intelligence to analyze documents, search authorized knowledge, or synthesize a deliverable.</p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-5">
            {hiddenCount > 0 ? (
              <button
                type="button"
                onClick={() => setVisibleCount((count) => count + 50)}
                className="label-micro mx-auto text-accent hover:underline"
              >
                Show {hiddenCount} earlier message{hiddenCount === 1 ? '' : 's'}
              </button>
            ) : null}

            {historyMessages.map((message) => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                className={message.role === 'user' ? 'ml-auto max-w-[85%] rounded-[22px] rounded-br-md border-hairline bg-accent/12 px-4 py-2.5 backdrop-blur-sm' : 'w-full'}
              >
                {message.role === 'assistant' ? (
                  <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>
                ) : (
                  <p className="text-sm text-foreground">{message.content}</p>
                )}
              </motion.div>
            ))}

            {/* The prompt bubble stays keyed to an in-page submission -- history already
                renders the prompt and the answer for anything resumed, so repeating them
                would double the turn on screen. The pipeline itself renders whenever
                there is a job to show, resumed or live. */}
            {pendingTask ? (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }} className="ml-auto max-w-[85%] rounded-[22px] rounded-br-md border-hairline bg-accent/12 px-4 py-2.5 backdrop-blur-sm">
                <p className="text-sm text-foreground">{pendingTask}</p>
              </motion.div>
            ) : null}

            {pendingTask || job ? (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30, delay: 0.08 }} className="w-full">
                <div className="flex items-center gap-2">
                  <StatusDot status={job?.status ?? 'queued'} />
                  <span className="label-micro">{job ? STATUS_LABEL[job.status] : STATUS_LABEL.queued}</span>
                  {job && !isLive ? <span className="label-micro text-muted-foreground/70">· Last run</span> : null}
                </div>

                {/* Only for a turn submitted in this visit: a resumed job's answer is
                    already above, rendered from conversation history. */}
                {isLive && job?.final_answer ? (
                  <div className="markdown mt-2"><ReactMarkdown remarkPlugins={[remarkGfm]}>{job.final_answer}</ReactMarkdown></div>
                ) : job?.error ? (
                  <p className="mt-2 text-sm text-danger">{job.error}</p>
                ) : null}

                {job ? <MetricsCard job={job} /> : null}
                {events.length > 0 ? <ActivityTimeline events={events} /> : null}
                {job?.status === 'awaiting_approval' ? <ApprovalGate job={job} onResolved={() => {}} /> : null}

                {job?.artifacts?.length ? (
                  <div className="mt-3 flex flex-col gap-1.5">
                    {job.artifacts.map((artifact) => <ArtifactCard key={artifact.artifact_id} jobId={job.job_id} artifact={artifact} />)}
                  </div>
                ) : null}
              </motion.div>
            ) : null}
          </div>
        )}
      </div>

      {error ? <p className="px-6 text-xs text-danger">{error}</p> : null}
      <Composer onSubmit={handleSend} submitting={submitting} />
    </div>
  )
}

export default IntelligenceFeedPage

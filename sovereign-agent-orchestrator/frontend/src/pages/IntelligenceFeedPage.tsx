import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { mutate as globalMutate } from 'swr'
import { useAuth } from '../context/AuthContext'
import { useConversation } from '../hooks/useConversations'
import { useJob, useJobEvents } from '../hooks/useJob'
import { sendChatMessage, uploadFile } from '../services/api'
import Composer from '../components/feed/Composer'
import ActivityTimeline from '../components/feed/ActivityTimeline'
import MetricsCard from '../components/feed/MetricsCard'
import ApprovalGate from '../components/feed/ApprovalGate'
import ArtifactCard from '../components/shared/ArtifactCard'
import { STATUS_LABEL } from '../components/shared/StatusDot'
import StatusDot from '../components/shared/StatusDot'

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

  const { job } = useJob(activeJobId)
  const { events } = useJobEvents(activeJobId)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Switching to a different (or no) conversation clears any in-flight turn from the
  // previous one -- there's no server-side pointer from a conversation to its "current"
  // job, so a live panel only ever represents a turn started in this page visit.
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

  return (
    <div className="app-page flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-4 border-b border-rule px-4 py-4 sm:px-8">
        <span className="font-mono text-[10px] text-accent">02 /</span><h1 className="truncate text-sm font-medium text-foreground">{conversation?.title ?? 'New Session'}</h1>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 pb-10 sm:px-6">
        {historyMessages.length === 0 && !pendingTask ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span aria-hidden="true" className="brand-mark flex size-11 items-center justify-center border border-accent/40 bg-[#36242a] font-mono text-lg font-semibold text-accent">S<span className="mb-3 text-[10px]">/</span></span>
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

            {pendingTask ? (
              <>
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }} className="ml-auto max-w-[85%] rounded-[22px] rounded-br-md border-hairline bg-accent/12 px-4 py-2.5 backdrop-blur-sm">
                  <p className="text-sm text-foreground">{pendingTask}</p>
                </motion.div>

                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 30, delay: 0.08 }} className="w-full">
                  <div className="flex items-center gap-2">
                    <StatusDot status={job?.status ?? 'queued'} />
                    <span className="label-micro">{job ? STATUS_LABEL[job.status] : STATUS_LABEL.queued}</span>
                  </div>

                  {job?.final_answer ? (
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
              </>
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

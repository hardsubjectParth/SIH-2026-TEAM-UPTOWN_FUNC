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
import ProtocolPipeline from '../components/feed/ProtocolPipeline'
import type { Submission } from '../components/feed/ProtocolPipeline'
import MetricsCard from '../components/feed/MetricsCard'
import ApprovalGate from '../components/feed/ApprovalGate'
import ArtifactsRail from '../components/feed/ArtifactsRail'
import type { RailArtifact } from '../components/feed/ArtifactsRail'
import StatusPill from '../components/shared/StatusPill'
import Avatar from '../components/shared/Avatar'
import { RANK } from '../components/shell/rank'
import { ShareIcon, StarIcon } from '../components/shell/icons'

const TERMINAL = new Set(['done', 'failed', 'cancelled'])

// The assistant's serif turn header. The mockup shows "Protocol Initialized." on the
// opening turn and "Synthesis Complete." once a deliverable lands; anything still
// running announces the phase it is in rather than claiming completion.
function turnHeader(index: number, isLive: boolean, status?: string) {
  if (isLive && status && !TERMINAL.has(status)) return 'Synthesis In Progress.'
  if (status === 'failed') return 'Synthesis Halted.'
  if (status === 'cancelled') return 'Protocol Cancelled.'
  if (index === 0) return 'Protocol Initialized.'
  return 'Synthesis Complete.'
}

function AssistantOrb() {
  return (
    <div className="border-hairline mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface">
      <span className="h-2 w-2 rounded-full bg-accent" style={{ boxShadow: '0 0 8px var(--color-accent)' }} />
    </div>
  )
}

function IntelligenceFeedPage() {
  const { id: routeId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { token, user } = useAuth()
  const { conversation, messages, mutate: mutateConversation } = useConversation(routeId)

  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pendingTask, setPendingTask] = useState<string | null>(null)
  const [submission, setSubmission] = useState<Submission | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Perf guardrail: a long-running session shouldn't keep every turn mounted forever.
  // Not full virtualization (no windowing library added for this) -- just a hard cap
  // with a manual "show earlier" expansion, which is enough to keep the DOM bounded.
  const [visibleCount, setVisibleCount] = useState(50)

  const { job } = useJob(activeJobId)
  const { events } = useJobEvents(activeJobId)
  const { jobs } = useJobs(100)
  const scrollRef = useRef<HTMLDivElement>(null)
  const rank = user ? RANK[user.role] : RANK.lower

  // Every artifact this conversation has produced, newest job first -- so the rail
  // survives a reload instead of only showing the turn submitted in this page visit.
  const railArtifacts = useMemo<RailArtifact[]>(() => {
    if (!routeId) return []
    return jobs
      .filter((summary) => summary.conversation_id === routeId)
      .flatMap((summary) =>
        (summary.artifacts ?? []).map((artifact) => ({
          jobId: summary.job_id,
          artifact,
          generatedAt: summary.created_at,
        })),
      )
  }, [jobs, routeId])

  // Switching to a different (or no) conversation clears any in-flight turn from the
  // previous one -- there's no server-side pointer from a conversation to its "current"
  // job, so a live panel only ever represents a turn started in this page visit.
  //
  // The exception is our OWN redirect: submitting from a brand-new session creates the
  // conversation server-side, and we then navigate /app/feed -> /app/feed/<new-id>. That
  // is a route change but not the user switching sessions -- resetting there tore down
  // the live panel microseconds after it mounted, which is what made a new session show
  // no progress at all until the finished answer appeared.
  //
  // Two things make this effect delicate. The guard must not consume itself: it used
  // to null the ref on the first run, and React's development StrictMode invokes
  // effects twice, so the replay found the ref already cleared, fell through, and
  // wiped the in-flight turn -- the pane vanished the instant a brand-new session
  // redirected. Comparing against the previous route id makes the replay a no-op on
  // its own, and the ref is left intact so it stays true for as long as we are on
  // the conversation we navigated to.
  const selfNavigated = useRef<string | null>(null)
  const previousRouteId = useRef<string | undefined>(undefined)
  useEffect(() => {
    const previous = previousRouteId.current
    previousRouteId.current = routeId
    if (previous === routeId) return
    if (selfNavigated.current === routeId) return
    setActiveJobId(null)
    setPendingTask(null)
    setSubmission(null)
    setVisibleCount(50)
  }, [routeId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, job?.status, job?.final_answer, events.length])

  useEffect(() => {
    if (job && TERMINAL.has(job.status)) mutateConversation()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  async function handleSend(task: string, files: File[]) {
    if (!token) return
    setSubmitting(true)
    setError(null)

    // Show the turn and its pipeline straight away. These used to be set only after
    // the uploads and POST /chat had all resolved, so pressing send produced no
    // visible change at all until the job existed -- and with an attachment that
    // needs OCR, ingest is synchronous and that wait runs into minutes.
    setActiveJobId(null)
    setPendingTask(task)
    setSubmission({
      task,
      phase: files.length > 0 ? 'uploading' : 'submitting',
      uploaded: 0,
      total: files.length,
      startedAt: new Date().toISOString(),
    })

    try {
      const uploadedFileIds: string[] = []
      for (const file of files) {
        const uploaded = await uploadFile(file, 'private', token)
        uploadedFileIds.push(uploaded.file_id)
        setSubmission((current) => (current ? { ...current, uploaded: current.uploaded + 1 } : current))
      }
      setSubmission((current) => (current ? { ...current, phase: 'submitting' } : current))

      const isNewConversation = !routeId
      const response = await sendChatMessage(task, token, routeId, uploadedFileIds)
      setSubmission((current) => (current ? { ...current, phase: 'accepted' } : current))
      setActiveJobId(response.data.job_id)
      if (isNewConversation) {
        globalMutate(['conversations', token])
        selfNavigated.current = response.data.conversation_id
        navigate(`/app/feed/${response.data.conversation_id}`, { replace: true })
      } else {
        mutateConversation()
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Unable to submit task'
      setError(message)
      // Keep the turn on screen rather than making it vanish: the pipeline marks
      // stage one failed and says why, which is more use than an empty feed.
      setSubmission((current) => (current ? { ...current, phase: 'failed', error: message } : current))
    } finally {
      setSubmitting(false)
    }
  }

  // Persisted messages already include the turn we just sent once the GET catches up
  // (the backend writes the user message synchronously before /chat returns). Hide the
  // trailing user message here only while it still exactly matches our own pending
  // turn, so it renders exactly once -- via the live panel below, not duplicated.
  const hideTrailingUser =
    pendingTask &&
    messages.length > 0 &&
    messages[messages.length - 1].role === 'user' &&
    messages[messages.length - 1].content === pendingTask
  const allHistoryMessages = hideTrailingUser ? messages.slice(0, -1) : messages
  const hiddenCount = Math.max(0, allHistoryMessages.length - visibleCount)
  const historyMessages = hiddenCount > 0 ? allHistoryMessages.slice(-visibleCount) : allHistoryMessages
  const submissionInFlight = submission?.phase === 'uploading' || submission?.phase === 'submitting'
  const busy = Boolean(submissionInFlight || (job && !TERMINAL.has(job.status)))

  // Once the finished turn lands in the conversation, history renders BOTH sides of
  // it in the right order. The live panel must then stop repeating the prompt and the
  // answer, or the turn appears twice -- and because the live panel sits after all
  // history, the repeat shows the prompt *below* the answer. The pipeline itself
  // stays: it is the only record of how the answer was produced.
  const turnPersisted = Boolean(
    pendingTask && job && TERMINAL.has(job.status) && messages[messages.length - 1]?.role === 'assistant',
  )

  return (
    <div className="flex h-screen min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-white/7 px-8 py-4">
          <div className="flex min-w-0 items-center gap-4">
            <span className="label-micro flex shrink-0 items-center gap-2">
              <span className={`h-1.5 w-1.5 rounded-full bg-accent ${busy ? 'animate-status-pulse' : ''}`} />
              Active Protocol
            </span>
            <span className="h-4 w-px shrink-0 bg-white/12" />
            <h1 className="truncate font-display text-[19px] leading-none font-medium text-foreground">
              {conversation?.title ?? 'New Session'}
            </h1>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button type="button" aria-label="Share session" className="rounded-lg p-2 text-muted-foreground transition hover:bg-surface hover:text-foreground">
              <ShareIcon size={17} />
            </button>
            <button type="button" aria-label="Star session" className="rounded-lg p-2 text-muted-foreground transition hover:bg-surface hover:text-foreground">
              <StarIcon size={17} />
            </button>
          </div>
        </header>

        <div ref={scrollRef} className="scroll-slim min-h-0 flex-1 overflow-y-auto px-8 py-8">
          {historyMessages.length === 0 && !pendingTask ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="border-hairline flex h-12 w-12 items-center justify-center rounded-2xl bg-surface">
                <span className="h-2.5 w-2.5 rounded-full bg-accent" style={{ boxShadow: '0 0 10px var(--color-accent)' }} />
              </div>
              <h2 className="mt-6 font-display text-[24px] font-medium text-foreground">Protocol Initialized.</h2>
              <p className="mt-3 max-w-md text-[14px] leading-relaxed text-muted-foreground">
                Instruct Sovereign Intelligence to analyze documents, search authorized knowledge, or synthesize a deliverable.
              </p>
            </div>
          ) : (
            <div className="mx-auto flex max-w-[760px] flex-col gap-8">
              {hiddenCount > 0 ? (
                <button type="button" onClick={() => setVisibleCount((count) => count + 50)} className="label-micro mx-auto text-accent hover:underline">
                  Show {hiddenCount} earlier message{hiddenCount === 1 ? '' : 's'}
                </button>
              ) : null}

              {historyMessages.map((message, index) =>
                message.role === 'assistant' ? (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                    className="flex gap-5"
                  >
                    <AssistantOrb />
                    <div className="min-w-0 flex-1">
                      <h3 className="font-display text-[19px] font-medium text-foreground">{turnHeader(index, false)}</h3>
                      <div className="markdown mt-4">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                      </div>
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                    className="flex items-start justify-end gap-3"
                  >
                    <p className="border-hairline max-w-[80%] rounded-2xl bg-surface px-5 py-3.5 text-[14.5px] leading-relaxed text-foreground">
                      {message.content}
                    </p>
                    <Avatar name={rank.name} size={36} />
                  </motion.div>
                ),
              )}

              {pendingTask ? (
                <>
                  {!turnPersisted ? (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                      className="flex items-start justify-end gap-3"
                    >
                      <p className="border-hairline max-w-[80%] rounded-2xl bg-surface px-5 py-3.5 text-[14.5px] leading-relaxed text-foreground">
                        {pendingTask}
                      </p>
                      <Avatar name={rank.name} size={36} />
                    </motion.div>
                  ) : null}

                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 30, delay: 0.08 }}
                    className="flex gap-5"
                  >
                    <AssistantOrb />
                    <div className="min-w-0 flex-1">
                      {!turnPersisted ? (
                        <div className="flex items-center gap-3">
                          <h3 className="font-display text-[19px] font-medium text-foreground">
                            {turnHeader(historyMessages.length, true, job?.status)}
                          </h3>
                          {job ? <StatusPill status={job.status} /> : null}
                        </div>
                      ) : null}

                      {job?.final_answer && !turnPersisted ? (
                        <div className="markdown mt-4">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{job.final_answer}</ReactMarkdown>
                        </div>
                      ) : job?.error ? (
                        <p className="mt-4 text-sm text-danger">{job.error}</p>
                      ) : null}

                      {/* Live stage readout first -- it is the thing worth watching while
                          the job runs. The flat event log stays available underneath for
                          debugging, collapsed by default. */}
                      <ProtocolPipeline events={events} job={job} submission={submission} />
                      {job ? <MetricsCard job={job} /> : null}
                      {job?.status === 'awaiting_approval' ? <ApprovalGate job={job} onResolved={() => {}} /> : null}
                      {events.length > 0 ? (
                        <details className="group mt-3">
                          <summary className="label-micro cursor-pointer list-none text-muted-foreground transition hover:text-foreground">
                            Raw event log ({events.length}) <span className="group-open:hidden">▸</span><span className="hidden group-open:inline">▾</span>
                          </summary>
                          <ActivityTimeline events={events} />
                        </details>
                      ) : null}
                    </div>
                  </motion.div>
                </>
              ) : null}
            </div>
          )}
        </div>

        {error ? <p className="px-8 pb-1 text-xs text-danger">{error}</p> : null}

        <div className="shrink-0 px-8 pb-5">
          <Composer onSubmit={handleSend} submitting={submitting} />
          <div className="mt-3 flex items-center justify-center gap-8">
            <span className="label-micro">◈ Node: OS-Alpha</span>
            <span className="label-micro">⬡ Encryption: AES-256</span>
          </div>
        </div>
      </div>

      <ArtifactsRail artifacts={railArtifacts} busy={busy} />
    </div>
  )
}

export default IntelligenceFeedPage

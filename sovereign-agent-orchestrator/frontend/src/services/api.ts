import type {
  AuthUser,
  Conversation,
  ConversationMessage,
  FileRecord,
  Job,
  JobEvent,
  JobSummary,
  KnowledgeSearchResult,
  LoginResponse,
} from '../types/api'

export type { AuthUser, LoginResponse, FileRecord, Job, JobSummary, JobEvent, Conversation, ConversationMessage, KnowledgeSearchResult }
// Kept for older imports written against the pre-rebuild api.ts, which exported the
// login/user type as `User` rather than `AuthUser`.
export type User = AuthUser

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8080/api/v1'
const PREVIEW_MODE = import.meta.env.DEV

const previewJob: Job = {
  job_id: 'preview-job-001', task: 'Synthesize the latest operating signals', status: 'done',
  routing: { task_type: 'analysis', model_id: 'preview-model', model_name: 'Sovereign Analysis', confidence: 0.94, reason: 'Preview dataset' },
  plan: [{ step_id: 'step-1', description: 'Collect relevant signals', tool: 'knowledge.search', tool_args: {}, status: 'done' }, { step_id: 'step-2', description: 'Verify the synthesis', tool: 'verification.run', tool_args: {}, status: 'done' }],
  verification: { passed: true, checks: { sources: true, consistency: true, citations: true }, notes: ['Preview verification passed'] },
  artifacts: [{ artifact_id: 'artifact-001', name: 'operating-brief.md', mime_type: 'text/markdown', size_bytes: 18420, url: '#' }],
  final_answer: 'Operating signals are stable. Three priority changes were verified across the available knowledge sources.',
  retrieval: [{ source: 'Operations handbook', score: 0.94 }, { source: 'Q3 planning brief', score: 0.88 }],
}
const previewJobs: JobSummary[] = [
  { job_id: previewJob.job_id, task: previewJob.task, status: 'done', created_at: '2026-09-23T10:42:00Z', task_type: 'analysis', model_name: 'Sovereign Analysis', artifacts: ['operating-brief.md'], verification_passed: true },
  { job_id: 'preview-job-002', task: 'Review onboarding friction points', status: 'awaiting_approval', created_at: '2026-09-23T09:16:00Z', task_type: 'review', model_name: 'Sovereign Review', artifacts: [], verification_passed: false },
  { job_id: 'preview-job-003', task: 'Compare regional launch notes', status: 'acting', created_at: '2026-09-22T16:08:00Z', task_type: 'research', model_name: 'Sovereign Research', artifacts: [], verification_passed: false },
]
const previewFiles: FileRecord[] = [{ id: 'file-001', name: 'Operations handbook.pdf', metadata: { visibility_tier: 'higher', size_bytes: 2457600, mime_type: 'application/pdf' }, created_at: '2026-09-22T14:12:00Z' }, { id: 'file-002', name: 'Q3 planning brief.docx', metadata: { visibility_tier: 'admin', size_bytes: 884000, mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, created_at: '2026-09-21T11:30:00Z' }]
const previewConversations: Conversation[] = [{ id: 'preview-conversation-001', tenant_id: 'preview-tenant', owner_id: 'preview-admin', title: 'Operating signals review', created_at: '2026-09-23T10:30:00Z', updated_at: '2026-09-23T10:42:00Z', archived: false }]

function previewResponse<T>(path: string): T | undefined {
  if (!PREVIEW_MODE) return undefined
  if (path === '/health') return { status: 'ok' } as T
  if (path.startsWith('/agent?')) return { data: previewJobs } as T
  if (path === `/agent/${previewJob.job_id}`) return previewJob as T
  if (path === '/files') return { data: previewFiles } as T
  if (path === '/files/scopes') return { scopes: ['admin', 'higher', 'lower'] } as T
  if (path === '/conversations') return { data: previewConversations } as T
  if (path.startsWith('/conversations/')) return { data: previewConversations[0], messages: [{ id: 'message-001', conversation_id: previewConversations[0].id, role: 'assistant', content: previewJob.final_answer ?? '', citations: [], created_at: '2026-09-23T10:42:00Z' }] } as T
  if (path === '/knowledge/search') return { data: previewFiles.map((file) => ({ content: `Preview result from ${file.name}`, metadata: { source: file.name }, score: 0.9 })) } as T
  return undefined
}

type ApiError = Error & { status?: number }

export const UNAUTHORIZED_EVENT = 'sovereign:unauthorized'

function notifyIfUnauthorized(response: Response, token?: string) {
  if (token && response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
}

async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  if (PREVIEW_MODE) {
    const preview = previewResponse<T>(path)
    if (preview !== undefined) return Promise.resolve(preview)
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
  })
  if (!response.ok) {
    notifyIfUnauthorized(response, token)
    const error = new Error((await response.json().catch(() => null))?.detail ?? `Request failed (${response.status})`) as ApiError
    error.status = response.status
    throw error
  }
  return response.json() as Promise<T>
}

export const healthCheck = () => request<{ status: string }>('/health')
// The existing dev-auth endpoint accepts account names, not email addresses.
// Map only its known development addresses; the server still determines the issued role.
export const devLogin = (email: string, password: string) => {
  const accounts: Record<string, string> = {
    'admin@sovereign.io': 'admin',
    'higher@sovereign.io': 'higher',
    'lower@sovereign.io': 'lower',
  }
  const username = accounts[email.trim().toLowerCase()]
  if (!username) return Promise.reject(new Error('This email is not registered for development access.'))
  return request<LoginResponse>('/auth/dev/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}
export const getUploadScopes = (token: string) => request<{ scopes: string[] }>('/files/scopes', {}, token)
export const listFiles = (token: string) => request<{ data: FileRecord[] }>('/files', {}, token)
// Omitting scope lets the server apply the caller's role default (app/access.py::DEFAULT_SCOPE).
export const uploadFile = (file: File, scope: string | undefined, token: string) => { const body = new FormData(); body.append('file', file); if (scope) body.append('scope', scope); return request<{ file_id: string; index: { tier: string } }>('/files', { method: 'POST', body }, token) }
export const deleteFile = (fileId: string, token: string) => request<{ file_id: string }>(`/files/${fileId}`, { method: 'DELETE' }, token)
export const searchKnowledge = (query: string, token: string) => request<{ data: KnowledgeSearchResult[] }>('/knowledge/search', { method: 'POST', body: JSON.stringify({ query, top_k: 8, metadata: {} }) }, token)
export const createAgentJob = (task: string, token: string, fileIds: string[] = []) => request<{ job_id: string; status: string }>('/agent/run', { method: 'POST', body: JSON.stringify({ task, user_context: {}, attachments: fileIds.map((file_id) => ({ file_id })) }) }, token)
export const listJobs = (token: string, limit = 20) => request<{ data: JobSummary[] }>(`/agent?limit=${limit}`, {}, token)
export const getJob = (jobId: string, token: string) => request<Job>(`/agent/${jobId}`, {}, token)

// Conversation-based chat (multi-turn, backs the Intelligence Feed). Distinct from
// createAgentJob/getJob above (single-shot task, no conversation) -- both create the
// same kind of job server-side, the conversation endpoints just also thread messages.
export const createConversation = (token: string, title = 'New conversation') => request<{ data: Conversation }>('/conversations', { method: 'POST', body: JSON.stringify({ title }) }, token)
export const listConversations = (token: string) => request<{ data: Conversation[] }>('/conversations', {}, token)
export const getConversation = (conversationId: string, token: string) => request<{ data: Conversation; messages: ConversationMessage[] }>(`/conversations/${conversationId}`, {}, token)
export const sendChatMessage = (message: string, token: string, conversationId?: string, fileIds: string[] = []) =>
  request<{ data: { job_id: string; conversation_id: string; status: string } }>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId, attachments: fileIds.map((file_id) => ({ file_id })) }),
  }, token)

export const approveJob = (jobId: string, approved: boolean, reviewerUserId: string, token: string) =>
  request<{ job_id: string; status: string }>(`/agent/${jobId}/approve`, { method: 'POST', body: JSON.stringify({ approved, reviewer_user_id: reviewerUserId }) }, token)
export const cancelJob = (jobId: string, token: string) => request<{ job_id: string; status: string }>(`/agent/${jobId}/cancel`, { method: 'POST' }, token)

// The events endpoint is a bearer-authenticated SSE stream, so it can't be read with
// EventSource (no custom headers). Read it by hand with fetch + a streaming reader
// instead, parsing "event:"/"data:" frames split on blank lines. Each frame's data
// line is the full stored envelope: {event_id, type, data, timestamp}.
export async function streamJobEvents(jobId: string, token: string, onEvent: (event: JobEvent) => void, signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/agent/${jobId}/events`, { headers: { Authorization: `Bearer ${token}` }, signal })
  notifyIfUnauthorized(response, token)
  if (!response.ok || !response.body) throw new Error(`Event stream failed (${response.status})`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      try { onEvent(JSON.parse(dataLine.slice(5).trim()) as JobEvent) } catch { /* ignore malformed frame */ }
    }
  }
}
export async function downloadArtifact(jobId: string, artifactName: string, token: string) {
  const response = await fetch(`${API_BASE_URL}/agent/${jobId}/artifacts/${encodeURIComponent(artifactName)}`, { headers: { Authorization: `Bearer ${token}` } })
  notifyIfUnauthorized(response, token)
  if (!response.ok) throw new Error(`Artifact download failed (${response.status})`)
  return response.blob()
}

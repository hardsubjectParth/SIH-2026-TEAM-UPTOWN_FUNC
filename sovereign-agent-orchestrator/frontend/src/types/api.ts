// Field names here are taken from the real backend (app/schemas/contracts.py,
// app/storage/store.py), not the "Sovereign OS" rebuild spec's §6 verbatim --
// several of its guessed field names don't match this checkout (see the
// mismatch table in the rebuild plan): Conversation/Message use `id`, not
// `conversation_id`/`message_id`; Artifact uses `url`, not `download_url`;
// JobStatus has no `running` value.

export type Role = 'admin' | 'higher' | 'lower'
export type Tier = Role

export interface AuthUser { id: string; role: Role; tenant_id: string }
export interface LoginResponse { access_token: string; token_type: 'bearer'; expires_in: number; user: AuthUser }

export interface FileRecord {
  id: string
  name: string
  metadata: { visibility_tier?: string; size_bytes?: number; mime_type?: string }
  created_at?: string
}

export type JobStatus =
  | 'queued'
  | 'planning'
  | 'acting'
  | 'observing'
  | 'verifying'
  | 'awaiting_approval'
  | 'delivering'
  | 'failed'
  | 'done'
  | 'cancelled'

export interface RoutingDecision {
  task_type: string
  model_id: string
  model_name?: string
  confidence: number
  reason: string
  fallback_model_id?: string
}

export interface PlanStep {
  step_id: string
  description: string
  tool?: string
  tool_args: Record<string, unknown>
  status: string
}

export interface Verification {
  passed: boolean
  checks: Record<string, boolean>
  notes: string[]
}

export interface JobArtifact {
  artifact_id: string
  name: string
  mime_type: string
  size_bytes: number
  url: string
}

export interface RetrievalHit { source: string; score: number }

export interface Job {
  job_id: string
  task: string
  status: JobStatus
  conversation_id?: string
  routing?: RoutingDecision
  plan?: PlanStep[]
  verification?: Verification
  requires_human_approval?: boolean
  approval?: { risk_tier?: number; reason?: string } | null
  artifacts: JobArtifact[]
  final_answer?: string | null
  error?: string | null
  retrieval?: RetrievalHit[]
}

export interface JobSummary {
  job_id: string
  task: string
  status: JobStatus
  created_at?: string
  task_type?: string
  model_id?: string
  model_name?: string
  artifacts: string[]
  final_answer?: string
  error?: string
  verification_passed?: boolean
}

export interface JobEvent {
  event_id: string
  type: string
  data: Record<string, unknown>
  timestamp: string
}

export interface Conversation {
  id: string
  tenant_id: string
  owner_id: string
  title: string
  created_at: string
  updated_at: string
  archived: boolean | number
}

export interface Citation { chunk_id: string; document_id?: string; source: string; content: string; score: number }

export interface ConversationMessage {
  id: string | number
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  created_at: string
}

export interface KnowledgeSearchResult {
  content: string
  metadata: Record<string, string>
  score: number
}

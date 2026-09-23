from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict

class JobStatus(str, Enum):
    queued='queued'; planning='planning'; acting='acting'; observing='observing'; verifying='verifying'; awaiting_approval='awaiting_approval'; delivering='delivering'; failed='failed'; done='done'; cancelled='cancelled'
class PolicyDecision(str, Enum):
    allow='allow'; deny='deny'; require_approval='require_approval'
class UserContext(BaseModel):
    user_id: str='cli-user'; role: str='user'; department: str='general'; clearance: str='internal'; project: str='demo'
class Attachment(BaseModel):
    file_id: str|None=None; name: str|None=None; path: str|None=None; mime_type: str|None=None
class RunOptions(BaseModel):
    max_iterations: int|None=None
class AgentRunRequest(BaseModel):
    task: str=Field(min_length=1); conversation_id: str|None=None; user_context: UserContext=UserContext(); attachments: list[Attachment]=[]; options: RunOptions=RunOptions()
class ChatRequest(BaseModel):
    message: str=Field(min_length=1, max_length=20000)
    conversation_id: str|None=None
    attachments: list[Attachment]=[]
    options: RunOptions=RunOptions()
class ConversationCreate(BaseModel):
    title: str='New conversation'
class SearchRequest(BaseModel):
    query: str=Field(min_length=1, max_length=20000)
    top_k: int=Field(default=8, ge=1, le=50)
    metadata: dict[str,Any]={}
class EvaluationCase(BaseModel):
    query: str=Field(min_length=1, max_length=20000)
    expected_file_ids: list[str]=[]
    top_k: int=Field(default=5, ge=1, le=50)
class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase]=Field(min_length=1, max_length=500)
class ShareRequest(BaseModel):
    user_id: str=Field(min_length=1, max_length=255)
    permission: str='read'
    expires_at: str|None=None
class Citation(BaseModel):
    chunk_id: str
    document_id: str|None=None
    source: str
    content: str
    score: float
    metadata: dict[str,Any]={}
class Conversation(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id: str; tenant_id: str; owner_id: str; title: str; created_at: str; updated_at: str; archived: bool|int=False
class Message(BaseModel):
    id: str|int; conversation_id: str; role: str; content: str; citations: list[Citation]=[]; created_at: str
class ApprovalRequest(BaseModel):
    # reviewer_user_id is accepted for compatibility with existing callers and
    # ignored: the reviewer recorded is always the one holding the token.
    approved: bool; reviewer_user_id: str|None=None
class RoutingDecision(BaseModel):
    task_type: str; model_id: str; confidence: float; reason: str; fallback_model_id: str|None=None
class PlanStep(BaseModel):
    step_id: str; description: str; tool: str; tool_args: dict[str,Any]={}; status: str='pending'
class ToolCall(BaseModel):
    call_id: str; tool: str; risk_tier: int; policy_decision: PolicyDecision; success: bool|None=None; result_summary: str|None=None
class Verification(BaseModel):
    passed: bool; checks: dict[str,bool]; notes: list[str]=[]
class Artifact(BaseModel):
    artifact_id: str; name: str; mime_type: str; size_bytes: int; url: str
class Event(BaseModel):
    event_id: str; type: str; status: JobStatus; data: dict[str,Any]={}; timestamp: str
class Job(BaseModel):
    job_id: str; status: JobStatus; task: str; routing: RoutingDecision|None=None; plan: list[PlanStep]=[]; tool_calls: list[ToolCall]=[]; observations: list[dict[str,Any]]=[]; verification: Verification|None=None; requires_human_approval: bool=False; approval: dict[str,Any]|None=None; artifacts: list[Artifact]=[]; final_answer: str|None=None; error: str|None=None

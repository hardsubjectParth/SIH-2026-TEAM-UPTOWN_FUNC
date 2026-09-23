import asyncio, uuid, mimetypes, shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from app.access import allowed_scopes
from app.schemas.contracts import *
from app.auth import current_identity
from app.dev_auth import DevLoginRequest, DevLoginResponse, issue_dev_token
from app.operations import UPLOADS, JOBS, RETRIEVALS

router=APIRouter(prefix='/api/v1')

@router.post('/auth/dev/login', response_model=DevLoginResponse, include_in_schema=False)
def dev_login(request: DevLoginRequest):
 return issue_dev_token(request)

SERVICE=None

def init_service(s):
 global SERVICE; SERVICE=s
def _prepare_attachments(jid, attachments, identity):
 prepared=[]
 for attachment in attachments:
  if not attachment.file_id: raise HTTPException(422,'ATTACHMENT_FILE_ID_REQUIRED')
  record=SERVICE.store.file_for(attachment.file_id, identity)
  if not record: raise HTTPException(403,'ATTACHMENT_NOT_AUTHORIZED')
  destination=SERVICE.workspace.safe(jid, 'input/'+Path(record['name']).name, True)
  shutil.copyfile(record['path'], destination)
  prepared.append({'file_id': record['id'], 'name': record['name'], 'path': str(destination.relative_to(SERVICE.workspace.root/jid)), 'mime_type': record['metadata'].get('mime_type')})
 return prepared
@router.get('/health')
def health(): return {'status':'ok'}
@router.get('/ready')
def ready(): return SERVICE.readiness
@router.get('/system/capabilities')
def capabilities(): return SERVICE.capabilities
@router.get('/system/network')
def system_network():
 from urllib.parse import urlparse
 from app.config import settings as _settings
 target = urlparse(_settings.ollama_base_url)
 status = SERVICE.network.check()
 status['ollama_reachable'] = SERVICE.network.probe_local(target.hostname or '127.0.0.1', target.port or 11434)
 return status
@router.get('/tools')
def list_tools(identity: dict=Depends(current_identity)):
 return {'tools': SERVICE.tools.names()}
@router.get('/models')
def list_models(identity: dict=Depends(current_identity)):
 return {'models': [{'id': m['id'], 'model': m.get('model'), 'capabilities': m.get('capabilities', []), 'enabled': m.get('enabled', False), 'tier': m.get('tier'), 'use_for': m.get('use_for', [])} for m in SERVICE.router.models]}
@router.get('/metrics', include_in_schema=False)
def metrics(): return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
@router.get('/files/scopes')
def upload_scopes(identity: dict=Depends(current_identity)):
 return {'scopes': allowed_scopes(identity['role'])}
@router.post('/files')
async def upload(file: UploadFile=File(...), scope: str|None=Form(default=None), identity: dict=Depends(current_identity)):
 fid=str(uuid.uuid4()); p=SERVICE.workspace.root/'uploads'; p.mkdir(exist_ok=True); dest=p/(fid+'_'+Path(file.filename or 'upload').name)
 data=await file.read(SERVICE.controls.max_upload_bytes + 1); SERVICE.controls.authorize_upload(identity, len(data)); scan=SERVICE.controls.scanner.scan(data); dest.write_bytes(data)
 try:
  # Writes into exactly one of the admin/higher/lower pgvector databases, resolved
  # server-side from the caller's verified role -- the client cannot pick a tier
  # it is not entitled to.
  indexed=await SERVICE.tools.rag.ingest(dest, identity, scope, {'mime_type':file.content_type,'file_id':fid,'tenant_id':identity['tenant_id'],'owner_id':identity['user_id'],'source_name':Path(file.filename or 'upload').name})
 except ValueError as exc:
  raise HTTPException(400,str(exc)) from exc
 SERVICE.store.register_file(fid, identity['user_id'], identity['tenant_id'], file.filename or 'upload', str(dest), {'mime_type':file.content_type, 'size_bytes':len(data), 'malware_scan':scan, 'index':indexed, 'visibility_tier':indexed.get('tier')})
 UPLOADS.labels('success').inc()
 SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'file_indexed', fid, indexed)
 return {'file_id':fid,'name':file.filename,'mime_type':file.content_type,'size_bytes':len(data),'index':indexed}
@router.get('/files')
def files(identity: dict=Depends(current_identity)):
 return {'data': SERVICE.store.files(identity)}
@router.delete('/files/{file_id}')
def delete_file(file_id: str, identity: dict=Depends(current_identity)):
 record=SERVICE.store.delete_file(file_id, identity)
 if not record: raise HTTPException(404,'FILE_NOT_FOUND')
 SERVICE.tools.rag.delete_document(file_id, record['metadata'].get('visibility_tier'))
 path=Path(record['path'])
 if path.is_file(): path.unlink()
 SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'file_deleted', file_id)
 return {'file_id':file_id,'deleted':True}
@router.post('/files/{file_id}/shares')
def share_file(file_id: str, req: ShareRequest, identity: dict=Depends(current_identity)):
 share=SERVICE.store.share_file(file_id, identity, req.user_id, req.permission, req.expires_at)
 if not share: raise HTTPException(403,'FILE_SHARE_NOT_AUTHORIZED')
 SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'file_shared', file_id, share)
 return {'data':share}
@router.get('/files/{file_id}/shares')
def file_shares(file_id: str, identity: dict=Depends(current_identity)):
 shares=SERVICE.store.file_shares(file_id, identity)
 if shares is None: raise HTTPException(404,'FILE_NOT_FOUND')
 return {'data':shares}
@router.delete('/files/shares/{share_id}')
def revoke_file_share(share_id: str, identity: dict=Depends(current_identity)):
 if not SERVICE.store.revoke_share(share_id, identity): raise HTTPException(404,'SHARE_NOT_FOUND')
 SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'file_share_revoked', share_id)
 return {'share_id':share_id,'revoked':True}
@router.post('/conversations')
def create_conversation(req: ConversationCreate, identity: dict=Depends(current_identity)):
 return {'data': SERVICE.store.create_conversation(str(uuid.uuid4()), identity['tenant_id'], identity['user_id'], req.title)}
@router.get('/conversations')
def list_conversations(identity: dict=Depends(current_identity)):
 return {'data': SERVICE.store.conversations(identity)}
@router.get('/conversations/{conversation_id}')
def get_conversation(conversation_id: str, identity: dict=Depends(current_identity)):
 conversation=SERVICE.store.conversation(conversation_id, identity)
 if not conversation: raise HTTPException(404,'CONVERSATION_NOT_FOUND')
 return {'data':conversation,'messages':SERVICE.store.messages(conversation_id)}
@router.get('/conversations/{conversation_id}/messages')
def conversation_messages(conversation_id: str, identity: dict=Depends(current_identity)):
 if not SERVICE.store.conversation(conversation_id, identity): raise HTTPException(404,'CONVERSATION_NOT_FOUND')
 return {'data':SERVICE.store.messages(conversation_id)}
@router.post('/knowledge/search')
async def knowledge_search(request: SearchRequest, identity: dict=Depends(current_identity)):
 metadata={key:value for key,value in request.metadata.items() if key not in {'tenant_id','owner_id','clearance','file_id','visibility_tier'}}
 metadata.update({'tenant_id': identity['tenant_id']})
 RETRIEVALS.labels('api').inc()
 # Only ever queries the pgvector database(s) this role may read (see app/access.py).
 # Tier membership IS the authorization, so no per-owner file filter is applied here:
 # everything inside a readable tier database is, by design, readable by that role.
 return {'data':await SERVICE.tools.rag.search(request.query, identity, request.top_k, metadata), 'query':request.query}
@router.post('/knowledge/evaluate')
async def knowledge_evaluate(request: EvaluationRequest, identity: dict=Depends(current_identity)):
 metadata={'tenant_id': identity['tenant_id']}
 return {'data':await SERVICE.tools.rag.evaluate([case.model_dump() for case in request.cases], identity, metadata)}
@router.post('/chat')
async def chat(req: ChatRequest, identity: dict=Depends(current_identity)):
 conversation_id=req.conversation_id
 if conversation_id:
  if not SERVICE.store.conversation(conversation_id, identity): raise HTTPException(404,'CONVERSATION_NOT_FOUND')
 else:
  conversation_id=str(uuid.uuid4())
  SERVICE.store.create_conversation(conversation_id, identity['tenant_id'], identity['user_id'], req.message[:80])
 jid=str(uuid.uuid4())
 SERVICE.workspace.create(jid)
 attachments=_prepare_attachments(jid, req.attachments, identity)
 context={'user_id':identity['user_id'],'role':identity['role'],'tenant_id':identity['tenant_id'],'clearance':identity['clearance']}
 SERVICE.store.add_message(str(uuid.uuid4()), conversation_id, 'user', req.message)
 j={'job_id':jid,'status':'queued','task':req.message,'conversation_id':conversation_id,'user_context':context,'attachments':attachments,'routing':None,'plan':[],'tool_calls':[],'observations':[],'verification':None,'requires_human_approval':False,'approval':None,'artifacts':[],'final_answer':None,'error':None,'task_type':'general'}
 SERVICE.store.save(j); SERVICE.store.enqueue(jid); SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'chat_message_created', conversation_id, {'job_id':jid})
 JOBS.labels('chat').inc()
 SERVICE._emit(j,'job_created',{'status':'queued','conversation_id':conversation_id})
 return {'data':{'job_id':jid,'conversation_id':conversation_id,'status':'queued'}}
@router.post('/agent/run')
async def run(req:AgentRunRequest, identity: dict=Depends(current_identity)):
 jid=str(uuid.uuid4()); context=req.user_context.model_dump(); context.update(identity); context['requested_role']=req.user_context.role
 conversation_id=req.conversation_id
 if conversation_id:
  if not SERVICE.store.conversation(conversation_id, identity): raise HTTPException(404,'CONVERSATION_NOT_FOUND')
 else:
  conversation_id=str(uuid.uuid4()); SERVICE.store.create_conversation(conversation_id, identity['tenant_id'], identity['user_id'], req.task[:80])
 SERVICE.workspace.create(jid)
 attachments=_prepare_attachments(jid, req.attachments, identity)
 j={'job_id':jid,'status':'queued','task':req.task,'conversation_id':conversation_id,'user_context':context,'attachments':attachments,'options':req.options.model_dump(),'routing':None,'plan':[],'tool_calls':[],'observations':[],'verification':None,'requires_human_approval':False,'approval':None,'artifacts':[],'final_answer':None,'error':None,'task_type':'document_workflow'}; SERVICE.store.add_message(str(uuid.uuid4()), conversation_id, 'user', req.task); SERVICE.store.save(j); SERVICE.store.enqueue(jid); SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'job_created', jid, {'task': req.task, 'attachments': [a['file_id'] for a in attachments]}); JOBS.labels('agent').inc(); SERVICE._emit(j,'job_created',{'status':'queued','conversation_id':conversation_id}); return {'job_id':jid,'conversation_id':conversation_id,'status':'queued'}
@router.get('/agent')
def list_jobs(limit: int = 20, identity: dict=Depends(current_identity)):
 return {'data': [{
   'job_id': j['job_id'], 'task': j.get('task'), 'status': j.get('status'),
   'created_at': j.get('created_at'), 'task_type': j.get('task_type'),
   'conversation_id': j.get('conversation_id'),
   'model_id': (j.get('routing') or {}).get('model_id'),
   'model_name': (j.get('routing') or {}).get('model_name'),
   # Full artifact records, not just names: the Intelligence Feed's artifact rail
   # lists every artifact produced across a conversation, and needs size/mime to
   # render each one without N follow-up GET /agent/{id} calls.
   'artifacts': j.get('artifacts', []),
   'final_answer': j.get('final_answer'), 'error': j.get('error'),
   'verification_passed': (j.get('verification') or {}).get('passed'),
 } for j in SERVICE.store.recent_jobs(identity, limit)]}
@router.get('/agent/{job_id}')
def get_job(job_id, identity: dict=Depends(current_identity)):
 j=SERVICE.store.get(job_id)
 if not j: raise HTTPException(404,'JOB_NOT_FOUND')
 context=j.get('user_context',{})
 if context.get('tenant_id') != identity['tenant_id']: raise HTTPException(404,'JOB_NOT_FOUND')
 # Own jobs always; anything in the tenant if admin; and, for a reviewer, another
 # user's job only while it is waiting on them. Without this last clause enforcing
 # who may approve leaves nobody able to see what needs approving. It is
 # deliberately narrow: the same job in any other status stays invisible.
 visible=(context.get('user_id')==identity['user_id']
          or identity.get('role')=='admin'
          or (identity.get('role')=='higher' and j.get('status')=='awaiting_approval'))
 if not visible: raise HTTPException(404,'JOB_NOT_FOUND')
 return j
@router.post('/agent/{job_id}/approve')
async def approve(job_id,req:ApprovalRequest, identity: dict=Depends(current_identity)):
 # The role is checked before the job is even looked up, so an analyst gets the
 # same 403 whether or not the job exists -- otherwise the response distinguishes
 # "not allowed" from "no such job" and becomes an existence oracle. The approval
 # is always recorded against the verified token, never req.reviewer_user_id.
 if identity.get('role') not in {'higher','admin'}: raise HTTPException(403,'APPROVAL_NOT_AUTHORIZED')
 j=get_job(job_id, identity)
 if not j: raise HTTPException(404,'JOB_NOT_FOUND')
 if j['status']!='awaiting_approval': raise HTTPException(409,'JOB_NOT_AWAITING_APPROVAL')
 # A reviewer cannot clear their own job; an administrator can, because there is
 # no one above them to ask and a deadlock would be worse than the concentration.
 if identity.get('role')=='higher' and j.get('user_context',{}).get('user_id')==identity['user_id']: raise HTTPException(403,'SELF_APPROVAL_NOT_ALLOWED')
 await SERVICE.resume(j,req.approved,identity['user_id']); SERVICE.store.audit(identity['user_id'], identity['tenant_id'], 'approval_decision', job_id, {'approved': req.approved}); return {'job_id':job_id,'status':j['status']}
@router.post('/agent/{job_id}/cancel')
def cancel(job_id, identity: dict=Depends(current_identity)):
 j=get_job(job_id, identity)
 if not j: raise HTTPException(404,'JOB_NOT_FOUND')
 if j['status'] in {'done','failed','cancelled'}: raise HTTPException(409,'JOB_ALREADY_FINISHED')
 j['status']='cancelled'; SERVICE.store.save(j); SERVICE._emit(j,'job_cancelled',{}); return {'job_id':job_id,'status':'cancelled'}
@router.get('/agent/{job_id}/events')
def events(job_id, identity: dict=Depends(current_identity)):
 get_job(job_id, identity)
 async def gen():
  sent=0
  while True:
   rows=SERVICE.store.events(job_id)
   for e in rows[sent:]: yield f"event: {e['type']}\ndata: {__import__('json').dumps(e)}\n\n"
   sent=len(rows); j=SERVICE.store.get(job_id)
   if j and j['status'] in {'done','failed','cancelled'} and sent>=len(rows): break
   await asyncio.sleep(.25)
 return StreamingResponse(gen(),media_type='text/event-stream')
@router.get('/agent/{job_id}/artifacts')
def artifacts(job_id, identity: dict=Depends(current_identity)):
 j=get_job(job_id, identity)
 if not j: raise HTTPException(404,'JOB_NOT_FOUND')
 return j['artifacts']
@router.get('/agent/{job_id}/artifacts/{artifact_name}')
def artifact(job_id,artifact_name, identity: dict=Depends(current_identity)):
 get_job(job_id, identity)
 p=SERVICE.workspace.safe(job_id,'output/'+artifact_name)
 if not p.is_file(): raise HTTPException(404,'ARTIFACT_NOT_FOUND')
 return FileResponse(p,filename=p.name,media_type=mimetypes.guess_type(p.name)[0] or 'application/octet-stream')

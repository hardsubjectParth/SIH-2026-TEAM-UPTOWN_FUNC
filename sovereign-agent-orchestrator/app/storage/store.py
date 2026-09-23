import json
import threading
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, text


class Store:
    def __init__(self, url='sqlite:///./orchestrator.db'):
        self.url = url
        self.engine = create_engine(url, future=True, pool_pre_ping=True)
        self.lock = threading.Lock()
        self._create_schema()

    @staticmethod
    def _decode(value):
        return value if isinstance(value, (dict, list)) else json.loads(value or '{}')

    @staticmethod
    def _iso(value):
        """Timestamps out of the store are always ISO-8601 strings.

        SQLite stores them as the ISO text we wrote; PostgreSQL stores TIMESTAMPTZ and
        psycopg returns a datetime object. That difference reached the API unchanged and
        broke the SSE stream outright -- json.dumps cannot serialise a datetime, so the
        live event stream died on the first event and the progress pane never received
        anything. Normalising here keeps every reader, and both backends, on one shape.
        """
        return value.isoformat() if isinstance(value, datetime) else value

    @classmethod
    def _row(cls, mapping, **overrides):
        """A result row as plain JSON-safe values, identical on either backend."""
        return {**{key: cls._iso(value) for key, value in dict(mapping).items()}, **overrides}

    def _create_schema(self):
        if self.url.startswith('postgresql'):
            # Production Postgres is provisioned by migrations/core/001_operational.sql.
            # If the core tables are already there, do not issue runtime DDL.
            try:
                with self.engine.connect() as db:
                    db.execute(text('SELECT 1 FROM jobs LIMIT 0'))
                    db.execute(text('SELECT 1 FROM job_queue LIMIT 0'))
                return
            except Exception:
                pass  # fall through to CREATE IF NOT EXISTS (dev convenience)
        integer = 'INTEGER PRIMARY KEY AUTOINCREMENT' if self.url.startswith('sqlite') else 'BIGSERIAL PRIMARY KEY'
        with self.engine.begin() as db:
            # API and worker initialize Store concurrently against the same Postgres
            # database. CREATE INDEX IF NOT EXISTS is not race-safe by itself, so
            # serialize schema creation per database during startup.
            if self.url.startswith('postgresql'):
                db.execute(text("SELECT pg_advisory_xact_lock(hashtext('sovereign-agent-orchestrator-schema'))"))
            db.execute(text('CREATE TABLE IF NOT EXISTS jobs(id VARCHAR(255) PRIMARY KEY, data TEXT NOT NULL)'))
            db.execute(text(f'CREATE TABLE IF NOT EXISTS events(id {integer}, job_id VARCHAR(255), type VARCHAR(255), data TEXT, created_at VARCHAR(255))'))
            db.execute(text(f'CREATE TABLE IF NOT EXISTS approvals(id {integer}, job_id VARCHAR(255), approved INTEGER, reviewer VARCHAR(255), created_at VARCHAR(255))'))
            db.execute(text('CREATE TABLE IF NOT EXISTS files(id VARCHAR(255) PRIMARY KEY, owner_id VARCHAR(255) NOT NULL, tenant_id VARCHAR(255) NOT NULL, name VARCHAR(255) NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL)'))
            db.execute(text(f'CREATE TABLE IF NOT EXISTS audit_events(id {integer}, actor_id VARCHAR(255), tenant_id VARCHAR(255), action VARCHAR(255) NOT NULL, resource VARCHAR(255), data TEXT, created_at VARCHAR(255))'))
            db.execute(text('CREATE TABLE IF NOT EXISTS job_queue(job_id VARCHAR(255) PRIMARY KEY, status VARCHAR(32) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at VARCHAR(255) NOT NULL)'))
            db.execute(text('CREATE TABLE IF NOT EXISTS conversations(id VARCHAR(255) PRIMARY KEY, tenant_id VARCHAR(255) NOT NULL, owner_id VARCHAR(255) NOT NULL, title VARCHAR(512) NOT NULL, created_at VARCHAR(255) NOT NULL, updated_at VARCHAR(255) NOT NULL, archived INTEGER NOT NULL DEFAULT 0)'))
            db.execute(text('CREATE TABLE IF NOT EXISTS messages(id VARCHAR(255) PRIMARY KEY, conversation_id VARCHAR(255) NOT NULL, role VARCHAR(32) NOT NULL, content TEXT NOT NULL, citations TEXT NOT NULL, created_at VARCHAR(255) NOT NULL)'))
            db.execute(text('CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages(conversation_id, id)'))
            db.execute(text('CREATE TABLE IF NOT EXISTS file_shares(id VARCHAR(255) PRIMARY KEY, file_id VARCHAR(255) NOT NULL, tenant_id VARCHAR(255) NOT NULL, shared_with_user_id VARCHAR(255) NOT NULL, permission VARCHAR(32) NOT NULL DEFAULT \'read\', expires_at VARCHAR(255), revoked INTEGER NOT NULL DEFAULT 0, created_at VARCHAR(255) NOT NULL)'))
            db.execute(text('CREATE INDEX IF NOT EXISTS file_shares_access_idx ON file_shares(file_id, shared_with_user_id, revoked)'))

    def save(self, job):
        job.setdefault('created_at', datetime.now(timezone.utc).isoformat())
        values = {'id': job['job_id'], 'data': json.dumps(job, default=str)}
        with self.lock, self.engine.begin() as db:
            statement = 'INSERT OR REPLACE INTO jobs(id,data) VALUES(:id,:data)' if self.url.startswith('sqlite') else 'INSERT INTO jobs(id,data) VALUES(:id,:data) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data'
            db.execute(text(statement), values)

    def get(self, jid):
        with self.engine.connect() as db:
            row = db.execute(text('SELECT data FROM jobs WHERE id=:id'), {'id': jid}).first()
        return self._decode(row[0]) if row else None

    def recent_jobs(self, identity, limit=20):
        """Jobs the caller may see (own tenant; own jobs unless admin), newest first."""
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT data FROM jobs')).fetchall()
        jobs = []
        for (raw,) in rows:
            job = self._decode(raw)
            context = job.get('user_context', {})
            if context.get('tenant_id') != identity['tenant_id']:
                continue
            # Mirrors the visibility rule in routes.get_job: a reviewer also sees the
            # jobs waiting on them, and only while they are waiting.
            if (context.get('user_id') != identity['user_id']
                    and identity.get('role') != 'admin'
                    and not (identity.get('role') == 'higher' and job.get('status') == 'awaiting_approval')):
                continue
            jobs.append(job)
        jobs.sort(key=lambda job: job.get('created_at') or '', reverse=True)
        return jobs[:min(max(limit, 1), 100)]

    def event(self, jid, typ, data):
        with self.lock, self.engine.begin() as db:
            db.execute(text('INSERT INTO events(job_id,type,data,created_at) VALUES(:job,:type,:data,:created)'), {'job': jid, 'type': typ, 'data': json.dumps(data, default=str), 'created': datetime.now(timezone.utc).isoformat()})

    def events(self, jid):
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT id,type,data,created_at FROM events WHERE job_id=:job ORDER BY id'), {'job': jid}).fetchall()
        return [{'event_id': str(row[0]), 'type': row[1], 'data': self._decode(row[2]), 'timestamp': self._iso(row[3])} for row in rows]

    def approval(self, jid, approved, reviewer):
        with self.lock, self.engine.begin() as db:
            db.execute(text('INSERT INTO approvals(job_id,approved,reviewer,created_at) VALUES(:job,:approved,:reviewer,:created)'), {'job': jid, 'approved': bool(approved), 'reviewer': reviewer, 'created': datetime.now(timezone.utc).isoformat()})

    def register_file(self, file_id, owner_id, tenant_id, name, path, metadata):
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO files(id,owner_id,tenant_id,name,path,metadata) VALUES(:id,:owner,:tenant,:name,:path,:metadata)'), {'id': file_id, 'owner': owner_id, 'tenant': tenant_id, 'name': name, 'path': path, 'metadata': json.dumps(metadata,default=str)})

    def files(self, identity, limit=100):
        with self.engine.connect() as db:
            # The owner check belongs in the query, not after it. Filtering in Python
            # meant LIMIT was applied to every file in the tenant first, so a user
            # whose own uploads happened to sort after 100 other people's saw a
            # truncated list -- or none at all -- with no indication anything was
            # missing.
            rows = db.execute(text('SELECT id,owner_id,tenant_id,name,path,metadata FROM files WHERE tenant_id=:tenant AND (:is_admin = 1 OR owner_id = :owner) ORDER BY name LIMIT :limit'), {'tenant': identity['tenant_id'], 'owner': identity['user_id'], 'is_admin': 1 if identity.get('role') == 'admin' else 0, 'limit': min(max(limit, 1), 100)}).fetchall()
        return [self._row(row._mapping, metadata=self._decode(row.metadata)) for row in rows]

    def user_storage_bytes(self, identity):
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT owner_id,metadata FROM files WHERE tenant_id=:tenant'), {'tenant': identity['tenant_id']}).fetchall()
        return sum(int(self._decode(row.metadata).get('size_bytes', 0)) for row in rows if row.owner_id == identity['user_id'] or identity.get('role') == 'admin')

    def file_for(self, file_id, identity):
        with self.engine.connect() as db:
            row = db.execute(text('SELECT id,owner_id,tenant_id,name,path,metadata FROM files WHERE id=:id AND tenant_id=:tenant'), {'id': file_id, 'tenant': identity['tenant_id']}).first()
        if not row or (row.owner_id != identity['user_id'] and identity.get('role') != 'admin' and file_id not in self.accessible_file_ids(identity)):
            return None
        return self._row(row._mapping, metadata=self._decode(row.metadata))

    def accessible_file_ids(self, identity):
        now = datetime.now(timezone.utc).isoformat()
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT f.id FROM files f LEFT JOIN file_shares s ON s.file_id=f.id AND s.shared_with_user_id=:user AND s.revoked=false AND (s.expires_at IS NULL OR s.expires_at>:now) WHERE f.tenant_id=:tenant AND (f.owner_id=:user OR :admin=1 OR s.id IS NOT NULL)'), {'tenant': identity['tenant_id'], 'user': identity['user_id'], 'admin': int(identity.get('role') == 'admin'), 'now': now}).fetchall()
        return [row[0] for row in rows]

    def share_file(self, file_id, identity, user_id, permission='read', expires_at=None):
        with self.engine.connect() as db:
            row = db.execute(text('SELECT id,tenant_id,owner_id FROM files WHERE id=:id AND tenant_id=:tenant'), {'id': file_id, 'tenant': identity['tenant_id']}).first()
        if not row or (row.owner_id != identity['user_id'] and identity.get('role') != 'admin'):
            return None
        share_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO file_shares(id,file_id,tenant_id,shared_with_user_id,permission,expires_at,created_at) VALUES(:id,:file,:tenant,:user,:permission,:expires,:created)'), {'id': share_id, 'file': file_id, 'tenant': identity['tenant_id'], 'user': user_id, 'permission': permission, 'expires': expires_at, 'created': now})
        return {'id': share_id, 'file_id': file_id, 'shared_with_user_id': user_id, 'permission': permission, 'expires_at': expires_at, 'created_at': now}

    def revoke_share(self, share_id, identity):
        with self.engine.begin() as db:
            result = db.execute(text('UPDATE file_shares SET revoked=true WHERE id=:id AND tenant_id=:tenant AND EXISTS (SELECT 1 FROM files f WHERE f.id=file_shares.file_id AND (f.owner_id=:user OR :admin=1))'), {'id': share_id, 'tenant': identity['tenant_id'], 'user': identity['user_id'], 'admin': int(identity.get('role') == 'admin')})
        return result.rowcount > 0

    def file_shares(self, file_id, identity):
        if not self.file_for(file_id, identity):
            return None
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT id,file_id,shared_with_user_id,permission,expires_at,revoked,created_at FROM file_shares WHERE file_id=:file ORDER BY created_at DESC'), {'file': file_id}).fetchall()
        return [self._row(row._mapping) for row in rows]

    def delete_file(self, file_id, identity):
        record = self.file_for(file_id, identity)
        if not record:
            return None
        with self.engine.begin() as db:
            db.execute(text('DELETE FROM files WHERE id=:id'), {'id': file_id})
        return record

    def audit(self, actor_id, tenant_id, action, resource, data=None):
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO audit_events(actor_id,tenant_id,action,resource,data,created_at) VALUES(:actor,:tenant,:action,:resource,:data,:created)'), {'actor': actor_id, 'tenant': tenant_id, 'action': action, 'resource': resource, 'data': json.dumps(data or {},default=str), 'created': datetime.now(timezone.utc).isoformat()})

    def enqueue(self, job_id):
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO job_queue(job_id,status,created_at) VALUES(:job,:status,:created)'), {'job': job_id, 'status': 'queued', 'created': datetime.now(timezone.utc).isoformat()})

    def claim_next(self):
        with self.lock, self.engine.begin() as db:
            if self.url.startswith('postgresql'):
                # FOR UPDATE SKIP LOCKED lets multiple workers race the queue safely; any
                # worker that would block on a locked row skips it instead of stalling.
                row = db.execute(text("""
                    WITH next_job AS (
                        SELECT job_id FROM job_queue
                        WHERE status = 'queued'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE job_queue queue
                    SET status = 'running', attempts = queue.attempts + 1
                    FROM next_job
                    WHERE queue.job_id = next_job.job_id
                    RETURNING queue.job_id
                """)).first()
            else:
                row = db.execute(text("SELECT job_id FROM job_queue WHERE status='queued' ORDER BY created_at LIMIT 1")).first()
                if row:
                    db.execute(text("UPDATE job_queue SET status='running', attempts=attempts+1 WHERE job_id=:job AND status='queued'"), {'job': row[0]})
            if not row:
                return None
        return self.get(row[0])

    def finish_queue(self, job_id, failed=False):
        with self.engine.begin() as db:
            db.execute(text('UPDATE job_queue SET status=:status WHERE job_id=:job'), {'status': 'failed' if failed else 'done', 'job': job_id})

    def create_conversation(self, conversation_id, tenant_id, owner_id, title):
        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO conversations(id,tenant_id,owner_id,title,created_at,updated_at) VALUES(:id,:tenant,:owner,:title,:created,:updated)'), {'id': conversation_id, 'tenant': tenant_id, 'owner': owner_id, 'title': title[:512] or 'New conversation', 'created': now, 'updated': now})
        return self.conversation(conversation_id, {'tenant_id': tenant_id, 'user_id': owner_id})

    def conversation(self, conversation_id, identity):
        with self.engine.connect() as db:
            row = db.execute(text('SELECT id,tenant_id,owner_id,title,created_at,updated_at,archived FROM conversations WHERE id=:id AND tenant_id=:tenant'), {'id': conversation_id, 'tenant': identity['tenant_id']}).first()
        if not row or (row.owner_id != identity['user_id'] and identity.get('role') != 'admin'):
            return None
        return self._row(row._mapping)

    def conversations(self, identity, limit=50):
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT id,tenant_id,owner_id,title,created_at,updated_at,archived FROM conversations WHERE tenant_id=:tenant AND (owner_id=:owner OR :admin=1) AND archived=false ORDER BY updated_at DESC LIMIT :limit'), {'tenant': identity['tenant_id'], 'owner': identity['user_id'], 'admin': int(identity.get('role') == 'admin'), 'limit': min(max(limit, 1), 100)}).fetchall()
        return [self._row(row._mapping) for row in rows]

    def add_message(self, message_id, conversation_id, role, content, citations=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as db:
            db.execute(text('INSERT INTO messages(id,conversation_id,role,content,citations,created_at) VALUES(:id,:conversation,:role,:content,:citations,:created)'), {'id': message_id, 'conversation': conversation_id, 'role': role, 'content': content, 'citations': json.dumps(citations or [],default=str), 'created': now})
            db.execute(text('UPDATE conversations SET updated_at=:updated WHERE id=:id'), {'id': conversation_id, 'updated': now})

    def messages(self, conversation_id, limit=20):
        # Ordered by created_at, not by id: message ids are random UUIDs, so
        # `ORDER BY id` sorted a conversation lexicographically by UUID -- which is
        # to say, arbitrarily. Turns rendered out of order (a prompt below the answer
        # it belonged to), and with LIMIT applied to that ordering a long conversation
        # returned an arbitrary subset rather than the most recent messages. The
        # orchestrator feeds this same call to the model as conversation history, so
        # the model was reading scrambled context too. created_at is a UTC ISO-8601
        # string, which sorts correctly lexicographically; id breaks ties so the order
        # is at least stable between calls.
        with self.engine.connect() as db:
            rows = db.execute(text('SELECT id,conversation_id,role,content,citations,created_at FROM messages WHERE conversation_id=:conversation ORDER BY created_at DESC, id DESC LIMIT :limit'), {'conversation': conversation_id, 'limit': min(max(limit, 1), 100)}).fetchall()
        return [self._row(row._mapping, citations=self._decode(row.citations)) for row in reversed(rows)]

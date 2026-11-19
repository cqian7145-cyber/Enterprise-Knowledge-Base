"""Additive, transactional upgrades for existing pilot databases."""
from .db import connect, now


def migrate():
    with connect(True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
            db.execute('ALTER TABLE revisions ADD COLUMN edit_version INTEGER NOT NULL DEFAULT 1')
            db.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
            db.execute("CREATE TABLE scope_options(store TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('job','station')),code TEXT NOT NULL,label TEXT NOT NULL,PRIMARY KEY(store,kind,code))")
            db.execute('INSERT INTO schema_migrations VALUES(1,?)', (now(),))
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
            db.execute("ALTER TABLE revisions ADD COLUMN change_reason TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE TRIGGER immutable_approved_reason BEFORE UPDATE ON revisions WHEN OLD.approved_at IS NOT NULL AND NEW.change_reason<>OLD.change_reason BEGIN SELECT RAISE(ABORT,'Approved revision is immutable'); END")
            db.execute('CREATE TABLE knowledge_metadata(document_id INTEGER PRIMARY KEY REFERENCES documents(id),owner_id INTEGER REFERENCES users(id),review_due_at TEXT,last_reviewed_at TEXT,metadata_version INTEGER NOT NULL DEFAULT 1)')
            db.execute('CREATE TABLE knowledge_events(id INTEGER PRIMARY KEY,document_id INTEGER NOT NULL REFERENCES documents(id),revision_id INTEGER REFERENCES revisions(id),actor INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)')
            db.execute("CREATE TABLE knowledge_proposals(id INTEGER PRIMARY KEY,store TEXT NOT NULL,feedback_id INTEGER UNIQUE REFERENCES feedback(id),document_id INTEGER REFERENCES documents(id),description TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','draft_created','rejected','closed')),revision_id INTEGER UNIQUE REFERENCES revisions(id),created_by INTEGER NOT NULL REFERENCES users(id),decision_note TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
            db.execute('CREATE TABLE escalations(query_id INTEGER PRIMARY KEY REFERENCES queries(id),feedback_id INTEGER NOT NULL UNIQUE REFERENCES feedback(id),created_at TEXT NOT NULL)')
            db.execute('CREATE INDEX knowledge_events_document ON knowledge_events(document_id,id)')
            db.execute('CREATE INDEX proposals_store_state ON knowledge_proposals(store,state)')
            db.execute('INSERT INTO schema_migrations VALUES(2,?)', (now(),))

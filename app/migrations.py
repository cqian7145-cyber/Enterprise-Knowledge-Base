"""Additive, transactional upgrades for existing pilot databases."""
import sqlite3
from .db import ROOT, connect, now


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
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone():
            db.execute('ALTER TABLE modules ADD COLUMN course_id INTEGER REFERENCES modules(id)')
            db.execute('ALTER TABLE modules ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
            db.execute("ALTER TABLE modules ADD COLUMN change_note TEXT NOT NULL DEFAULT ''")
            db.execute('ALTER TABLE modules ADD COLUMN created_at TEXT')
            db.execute('UPDATE modules SET course_id=id,created_at=?', (now(),))
            db.execute('CREATE UNIQUE INDEX course_versions ON modules(course_id,version)')
            db.execute('ALTER TABLE assignments ADD COLUMN assigned_at TEXT')
            db.execute('ALTER TABLE assignments ADD COLUMN due_at TEXT')
            db.execute('ALTER TABLE assignments ADD COLUMN superseded_by INTEGER REFERENCES assignments(id)')
            db.execute('UPDATE assignments SET assigned_at=?', (now(),))
            db.execute('CREATE TABLE practical_reviews(id INTEGER PRIMARY KEY,assignment_id INTEGER NOT NULL REFERENCES assignments(id),reviewer_id INTEGER NOT NULL REFERENCES users(id),passed INTEGER NOT NULL,note TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL)')
            db.execute("INSERT INTO practical_reviews(assignment_id,reviewer_id,passed,note,evidence,created_at) SELECT id,practical_by,1,practical_note,'历史实操记录',practical_at FROM assignments WHERE practical_at IS NOT NULL")
            db.execute("CREATE TABLE flow_runs(id INTEGER PRIMARY KEY,store TEXT NOT NULL,station TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('opening','closing','handoff')),business_date TEXT NOT NULL,owner_id INTEGER NOT NULL REFERENCES users(id),recipient_id INTEGER REFERENCES users(id),state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','closed')),note TEXT NOT NULL DEFAULT '',created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,closed_at TEXT,closed_by INTEGER REFERENCES users(id),version INTEGER NOT NULL DEFAULT 1,UNIQUE(store,station,kind,business_date))")
            db.execute("CREATE TABLE flow_items(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES flow_runs(id),position INTEGER NOT NULL,label TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','done','issue')),note TEXT NOT NULL DEFAULT '',evidence TEXT NOT NULL DEFAULT '',updated_by INTEGER REFERENCES users(id),updated_at TEXT,UNIQUE(run_id,position))")
            db.execute("CREATE TABLE flow_incidents(id INTEGER PRIMARY KEY,store TEXT NOT NULL,station TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('repair','exception')),title TEXT NOT NULL,description TEXT NOT NULL,report_evidence TEXT NOT NULL DEFAULT '',owner_id INTEGER NOT NULL REFERENCES users(id),item_id INTEGER UNIQUE REFERENCES flow_items(id),state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','resolved','closed')),resolution TEXT,close_evidence TEXT,resolved_by INTEGER REFERENCES users(id),resolved_at TEXT,created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,closed_by INTEGER REFERENCES users(id),closed_at TEXT,version INTEGER NOT NULL DEFAULT 1)")
            db.execute('CREATE INDEX flow_incident_queue ON flow_incidents(store,state,station)')
            db.execute('INSERT INTO schema_migrations VALUES(3,?)', (now(),))
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=4').fetchone():
            statement = ''
            for line in (ROOT / 'app' / 'commerce_schema.sql').read_text(encoding='utf8').splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            if statement.strip():
                raise RuntimeError('Incomplete commerce schema')
            db.execute('INSERT INTO schema_migrations VALUES(4,?)', (now(),))
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=5').fetchone():
            statement = ''
            for line in (ROOT / 'app' / 'org_schema.sql').read_text(encoding='utf8').splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            if statement.strip():
                raise RuntimeError('Incomplete organization schema')
            from .tenancy import ensure_registry
            ensure_registry(db)
            db.execute('INSERT INTO schema_migrations VALUES(5,?)', (now(),))

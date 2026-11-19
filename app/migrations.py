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

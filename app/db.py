"""SQLite connections are per operation; all mutations use BEGIN IMMEDIATE."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

@contextmanager
def connect(write=False):
    path = Path(os.environ.get('BAROS_DB', str(ROOT / 'data' / 'baros.sqlite')))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize():
    with connect() as db:
        db.executescript((ROOT / 'app' / 'schema.sql').read_text(encoding='utf8'))

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return salt + ':' + digest

def verify_password(password, stored):
    salt, _ = stored.split(':')
    return hmac.compare_digest(password_hash(password, salt), stored)

def audit(db, user, action, target):
    db.execute('INSERT INTO audit(store,actor,action,target,created_at) VALUES(?,?,?,?,?)',
               (user['store'], user['id'], action, str(target), now()))

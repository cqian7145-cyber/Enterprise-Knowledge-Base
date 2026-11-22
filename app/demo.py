"""Explicit, fail-closed, offline demo importer; never invoked by application startup."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch
from .db import ROOT, initialize
from .dbtools import snapshot
from .demo_data import DATASET, LABEL

CONFIRMATION='SIMULATED-DATA'


def validated_target(database,environment,confirm):
    if environment!='demo' or confirm!=CONFIRMATION:
        raise ValueError('Require --environment demo --confirm SIMULATED-DATA')
    raw=Path(database)
    if not raw.is_absolute():raise ValueError('Demo database must use an explicit absolute path')
    target=raw.resolve()
    if target==(ROOT/'data'/'baros.sqlite').resolve():raise ValueError('Default business database is forbidden')
    if 'demo' not in target.stem.lower():raise ValueError('Demo database filename must contain demo')
    return target


def existing_manifest(target):
    if not target.exists():return None
    if not target.is_file():raise ValueError('Destination must be a new demo database file')
    try:
        with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT dataset,payload FROM demo_manifest WHERE id=1').fetchone()
            if not row or row[0]!=DATASET:raise ValueError('Destination is not this demo dataset; refusing to modify it')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Existing demo integrity validation failed')
            return json.loads(row[1])
    except sqlite3.DatabaseError as exc:raise ValueError('Existing destination has no valid demo marker; refusing to modify it') from exc


def seed_realistic_demo(database,password=None,*,environment,confirm,anchor=None,_fail_after=None):
    target=validated_target(database,environment,confirm)
    existing=existing_manifest(target)
    if existing:return {**existing,'unchanged':True,'database':str(target)}
    if not isinstance(password,str) or not 12<=len(password)<=200:raise ValueError('Operator must supply a password of 12–200 characters')
    anchor=anchor or datetime.now(timezone.utc)
    if anchor.tzinfo is None or anchor>datetime.now(timezone.utc):raise ValueError('Demo anchor must be timezone-aware and not in the future')
    anchor=anchor.astimezone(timezone.utc).replace(microsecond=0)
    target.parent.mkdir(parents=True,exist_ok=True)
    phase='initialize'
    try:
        with tempfile.TemporaryDirectory(prefix='baros-demo-build-',dir=target.parent) as staging:
            stage=Path(staging)/'demo-staging.sqlite'
            with patch.dict(os.environ,{'BAROS_DB':str(stage),'BAROS_SECURE_COOKIE':'0'}):
                initialize()
                db=sqlite3.connect(stage,check_same_thread=False);db.row_factory=sqlite3.Row
                db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
                try:
                    phase='business-api-replay'
                    from .demo_fixture import build
                    manifest=build(db,password,anchor,_fail_after)
                    # Session material never ships with the demonstration dataset.
                    db.execute('DELETE FROM sessions');db.execute('DELETE FROM login_limits')
                    counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['users','documents','revisions','modules','assignments','attempts','practical_reviews','flow_runs','flow_incidents','inv_skus','inv_costs','inv_sales','inv_sales_batches','inv_counts','insight_reports','hq_deliveries','agent_plans','work_tasks']}
                    manifest['counts']=counts
                    db.execute('CREATE TABLE demo_manifest(id INTEGER PRIMARY KEY CHECK(id=1),dataset TEXT NOT NULL,payload TEXT NOT NULL)')
                    db.execute('INSERT INTO demo_manifest VALUES(1,?,?)',(DATASET,json.dumps(manifest,ensure_ascii=False)))
                    if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Demo fixture violates foreign keys')
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Demo fixture integrity failure')
                    db.commit()
                except BaseException:db.rollback();raise
                finally:db.close()
            phase='exclusive-publish'
            snapshot(stage,target)  # SQLite backup API creates an exclusive, non-overwriting destination.
        return {**manifest,'unchanged':False,'database':str(target)}
    except Exception as exc:
        # No payload, password, hash, Cookie or real records in error logs.
        with target.with_name(target.name+'.import-errors.jsonl').open('a',encoding='utf8') as log:
            log.write(json.dumps({'dataset':DATASET,'label':LABEL,'phase':phase,'error_type':type(exc).__name__,'rolled_back':True,'target_created':target.exists(),'at':datetime.now(timezone.utc).isoformat()})+'\n')
        raise

"""Destructive upgrade/restore drill operates only inside pytest's disposable directory."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from contextlib import closing
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import ROOT,initialize,password_hash,encode
from app.dbtools import snapshot


def test_legacy_upgrade_backup_and_isolated_restore(tmp_path,monkeypatch):
    start=time.perf_counter();source=(tmp_path/'legacy-v0.sqlite').resolve()
    before=(tmp_path/'before-upgrade.sqlite').resolve();upgraded=(tmp_path/'after-upgrade.sqlite').resolve();restored=(tmp_path/'restored-new.sqlite').resolve()
    assert all(p.is_relative_to(tmp_path.resolve()) for p in (source,before,upgraded,restored))
    assert source!=(ROOT/'data'/'baros.sqlite').resolve()
    password='Recovery-only-e2e-password'
    with closing(sqlite3.connect(source)) as db:
        db.executescript((ROOT/'app'/'schema.sql').read_text(encoding='utf8'))
        for uid,role in [(1,'admin'),(2,'staff')]:db.execute('INSERT INTO users(id,username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?,?)',(uid,'recovery'+str(uid),'纯虚构恢复账号'+str(uid),password_hash(password),role,'recovery','bartender',encode(['main'])))
        db.execute("INSERT INTO documents(id,store,title,kind,jobs,stations,aliases) VALUES(1,'recovery','纯虚构历史标准','sop',?,?,?)",(encode(['bartender']),encode(['main']),encode([])))
        payload=encode({'summary':'原始批准说明','steps':['核对器具并请主管验收']})
        db.execute("INSERT INTO revisions(id,document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(1,1,1,'published',?,'纯虚构恢复演练来源','2020-01-01T00:00:00+00:00',1,1,'2020-01-01T00:00:00+00:00')",(payload,))
        db.execute("INSERT INTO modules(id,store,title,objective,revision_ids,quiz,pass_score,created_by) VALUES(1,'recovery','历史培训','保持历史培训证据',?,?,100,1)",(encode([1]),encode([{'question':'是否核对','options':['是','否'],'answer':0}])))
        db.execute("INSERT INTO assignments(id,module_id,user_id,assigned_by,best_score,practical_by,practical_note,practical_at) VALUES(1,1,2,1,100,1,'纯虚构现场实操已通过','2020-01-02T00:00:00+00:00')")
        db.execute("INSERT INTO attempts(assignment_id,score,created_at) VALUES(1,100,'2020-01-02T00:00:00+00:00')")
        db.commit()
    backup_start=time.perf_counter();snapshot(source,before);backup_duration=time.perf_counter()-backup_start
    monkeypatch.setenv('BAROS_DB',str(source));upgrade_start=time.perf_counter();initialize();upgrade_duration=time.perf_counter()-upgrade_start
    with closing(sqlite3.connect(source)) as db:
        assert [r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')]==[1,2,3,4,5]
        assert db.execute('SELECT content FROM revisions WHERE id=1').fetchone()[0]==payload
        assert db.execute('SELECT best_score,practical_note FROM assignments WHERE id=1').fetchone()==(100,'纯虚构现场实操已通过')
        assert db.execute('SELECT COUNT(*) FROM practical_reviews').fetchone()[0]==1
    snapshot(source,upgraded)
    restore_start=time.perf_counter();snapshot(upgraded,restored);restore_duration=time.perf_counter()-restore_start
    def rows(p,table):
        with closing(sqlite3.connect(p)) as db:return db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
    tables=['documents','revisions','modules','assignments','attempts','practical_reviews','tenants','stores']
    assert all(rows(source,t)==rows(restored,t) for t in tables)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):snapshot(upgraded,source)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    monkeypatch.setenv('BAROS_DB',str(restored));initialize();initialize()
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    with TestClient(app) as client:
        login=client.post('/api/login',json={'username':'recovery2','password':password});assert login.status_code==200
        assert client.get('/api/knowledge/1').json()['content']['summary']=='原始批准说明'
        assert client.get('/api/academy/evidence').json()['items'][0]['qualified'] is True
    # Pre-upgrade backup is still an actual v0 file, a rollback route for the old release.
    with closing(sqlite3.connect(before)) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone()
        assert db.execute('SELECT content FROM revisions').fetchone()[0]==payload
    output=ROOT/'test-results'/'recovery';output.mkdir(parents=True,exist_ok=True)
    record={'synthetic_only':True,'source_schema':'v0','upgraded_schema':5,'preserved_tables':tables,'integrity':'ok','foreign_keys':'ok','no_overwrite':True,'restored_api_login':True,'restored_training_qualified':True,'backup_seconds':round(backup_duration,4),'upgrade_seconds':round(upgrade_duration,4),'restore_seconds':round(restore_duration,4),'total_seconds':round(time.perf_counter()-start,4),'rto_promise':False}
    (output/'drill.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')

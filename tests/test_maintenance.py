import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect, initialize
from app.dbtools import snapshot
from test_baros import clients, create, publish, PASSWORD


def test_edit_conflict_state_and_diff(clients):
    admin, staff, outsider, _ = clients
    item, data = create(admin)
    payload = {'content': {**data['content'], 'summary': '更新后的标准'}, 'source': '主管确认新来源', 'edit_version': 1}
    url = f"/api/manage/revisions/{item['id']}/edit"
    assert staff.post(url, json=payload).status_code == 403
    assert outsider.post(url, json=payload).status_code == 404
    assert admin.post(url, json=payload).json()['edit_version'] == 2
    assert admin.post(url, json=payload).status_code == 409
    assert admin.post(f"/api/manage/revisions/{item['id']}/submit", json={'edit_version': 1}).status_code == 409
    diff = admin.get(f"/api/manage/revisions/{item['id']}/diff").json()
    assert diff['before'] is None and diff['after']['content']['summary'] == '更新后的标准'
    assert publish(admin, item['id']).status_code == 200
    payload['edit_version'] = 2
    assert admin.post(url, json=payload).status_code == 409
    v2, _ = create(admin, document_id=item['document_id'], **data)
    diff = admin.get(f"/api/manage/revisions/{v2['id']}/diff").json()
    assert diff['previous_version'] == 1 and 'summary' in diff['changed_fields']
    assert outsider.get(f"/api/manage/revisions/{v2['id']}/diff").status_code == 404


def test_reset_revoke_force_change_and_audit(clients):
    admin, staff, outsider, _ = clients
    endpoint = '/api/admin/users/2/reset-password'
    temporary, new = 'Temporary-only-2026', 'Changed-new-pass-2026'
    assert staff.post(endpoint, json={'temporary_password': temporary}).status_code == 403
    assert outsider.post(endpoint, json={'temporary_password': temporary}).status_code == 404
    assert admin.post(endpoint, json={'temporary_password': temporary}).status_code == 200
    assert staff.get('/api/me').status_code == 401
    assert staff.post('/api/login', json={'username': 'staff', 'password': PASSWORD}).status_code == 401
    r = staff.post('/api/login', json={'username': 'staff', 'password': temporary})
    assert r.json()['user']['must_change_password'] == 1
    staff.headers['X-CSRF-Token'] = r.json()['csrf']
    assert staff.get('/api/knowledge').status_code == 403
    assert staff.post('/api/ask', json={'question':'金汤力','station':'main'}).status_code == 403
    assert staff.post('/api/password', json={'current_password':'wrong','new_password':new}).status_code == 403
    assert staff.post('/api/password', json={'current_password':temporary,'new_password':temporary}).status_code == 422
    assert staff.post('/api/password', json={'current_password':temporary,'new_password':new}).status_code == 200
    assert staff.get('/api/me').status_code == 401
    r = staff.post('/api/login', json={'username': 'staff', 'password': new})
    staff.headers['X-CSRF-Token'] = r.json()['csrf']
    assert r.json()['user']['must_change_password'] == 0
    assert staff.get('/api/knowledge').status_code == 200
    records = admin.get('/api/manage/audit').json()
    assert any(r['action']=='password_reset' for r in records)
    assert all(temporary not in json.dumps(r) and new not in json.dumps(r) for r in records)


def test_config_scope_change_and_session_revocation(clients):
    admin, staff, outsider, _ = clients
    option = {'kind':'station','code':'second','label':'二楼吧台'}
    assert staff.post('/api/admin/scope-options',json=option).status_code == 403
    assert admin.post('/api/admin/scope-options',json=option).status_code == 200
    assert option in admin.get('/api/config').json()
    assert option not in outsider.get('/api/config').json()
    edit = {'name':'新姓名','role':'staff','job':'bartender','stations':['second']}
    assert outsider.post('/api/admin/users/2/edit',json=edit).status_code == 404
    assert admin.post('/api/admin/users/1/edit',json=edit).status_code == 409
    assert admin.post('/api/admin/users/2/edit',json={**edit,'stations':['nonexistent']}).status_code == 422
    assert admin.post('/api/admin/users/2/edit',json=edit).status_code == 200
    assert staff.get('/api/me').status_code == 401
    r=staff.post('/api/login',json={'username':'staff','password':PASSWORD})
    staff.headers['X-CSRF-Token']=r.json()['csrf']
    assert staff.get('/api/knowledge').json() == []
    assert staff.post('/api/ask',json={'question':'金汤力','station':'main'}).status_code == 403
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM assignments WHERE user_id=2').fetchone()[0] == 1
    assert staff.get('/api/training').json()[0]['stale'] is True


def test_new_account_must_change_and_dictionary_validation(clients):
    admin, staff, _, _=clients
    data={'username':'new-worker','name':'新员工','password':PASSWORD,'role':'staff','job':'bartender','stations':['main']}
    assert admin.post('/api/admin/users',json={**data,'job':'unknown'}).status_code == 422
    assert admin.post('/api/admin/users',json=data).status_code == 200
    with TestClient(app) as client:
        r=client.post('/api/login',json={'username':data['username'],'password':PASSWORD})
        assert r.json()['user']['must_change_password'] == 1
        assert client.get('/api/manage/users').status_code == 403


def test_snapshot_restore_no_overwrite_and_migration(clients, tmp_path, monkeypatch):
    import os
    source=os.environ['BAROS_DB']
    backup=tmp_path/'backups'/'snapshot.sqlite'
    restored=tmp_path/'restored.sqlite'
    snapshot(source,backup)
    snapshot(backup,restored)
    with sqlite3.connect(restored) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 4
        assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0] == 1
    with pytest.raises(FileExistsError):snapshot(source,backup)
    with pytest.raises(ValueError):snapshot(source,source)
    monkeypatch.setenv('BAROS_DB',str(restored))
    initialize(); initialize()
    with connect() as db:
        assert [r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')] == [1, 2]


def test_legacy_database_upgrade_preserves_data(tmp_path,monkeypatch):
    from app.db import ROOT
    path=tmp_path/'legacy.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript((ROOT/'app'/'schema.sql').read_text(encoding='utf8'))
        db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)', ('legacy','旧员工','hash','staff','pilot','bartender',json.dumps(['main'])))
    monkeypatch.setenv('BAROS_DB',str(path))
    initialize();initialize()
    with connect() as db:
        row=db.execute('SELECT * FROM users').fetchone()
        assert row['username']=='legacy' and row['must_change_password']==0
        assert 'edit_version' in {r[1] for r in db.execute('PRAGMA table_info(revisions)')}


def test_mutations_require_csrf(clients):
    admin, _, _, _ = clients
    token=admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/admin/users/2/reset-password',json={'temporary_password':PASSWORD}).status_code==403
    assert admin.post('/api/admin/scope-options',json={'kind':'job','code':'test','label':'测试'}).status_code==403
    admin.headers['X-CSRF-Token']=token


def test_chunked_body_limit_and_invalid_length(clients):
    admin, _, _, _=clients
    assert admin.post('/api/login',content=iter([b'x'*70000,b'x'*70000]),headers={'Content-Type':'application/json'}).status_code==413
    assert admin.post('/api/login',content=b'{}',headers={'Content-Length':'bad'}).status_code==400
    assert admin.post('/api/login',content=b'{}',headers={'Content-Length':'999999'}).status_code==413
    # A small streaming JSON body still reaches the real handler.
    body=json.dumps({'username':'admin','password':PASSWORD}).encode()
    assert admin.post('/api/login',content=iter([body[:10],body[10:]]),headers={'Content-Type':'application/json'}).status_code==200

"""Pilot administration: editable drafts, credentials and scope dictionaries."""
import json
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from .db import audit, connect, encode, now, password_hash, verify_password
from .main import Content, Input, admin, fail, get_revision, identity, manager

router = APIRouter()


class DraftEdit(Input):
    content: Content
    source: str = Field(min_length=1, max_length=500)
    edit_version: int = Field(ge=1)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class PasswordReset(Input):
    temporary_password: str = Field(min_length=12, max_length=200)


class UserEdit(Input):
    name: str = Field(min_length=1, max_length=80)
    role: Literal['staff', 'manager', 'admin']
    job: str = Field(min_length=1, max_length=80)
    stations: list[str] = Field(min_length=1, max_length=20)


class ScopeOption(Input):
    kind: Literal['job', 'station']
    code: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    label: str = Field(min_length=1, max_length=80)

    @field_validator('label')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('显示名称不能为空')
        return value.strip()


def ensure_options(db, store):
    # Recover existing internal identifiers without changing knowledge scope.
    rows = db.execute('SELECT job,stations FROM users WHERE store=?', (store,)).fetchall()
    jobs = {r['job'] for r in rows}
    stations = {s for r in rows for s in json.loads(r['stations'])}
    for r in db.execute('SELECT jobs,stations FROM documents WHERE store=?', (store,)):
        jobs.update(json.loads(r['jobs']))
        stations.update(json.loads(r['stations']))
    for kind, codes in [('job', jobs), ('station', stations)]:
        for code in codes:
            label = {'bartender': '调酒师', 'server': '服务员', 'main': '主吧台', 'terrace': '露台吧台'}.get(code, code)
            db.execute('INSERT OR IGNORE INTO scope_options VALUES(?,?,?,?)', (store, kind, code, label))


def validate_options(db, store, job, stations):
    ensure_options(db, store)
    options = db.execute('SELECT kind,code FROM scope_options WHERE store=?', (store,)).fetchall()
    if job not in {r['code'] for r in options if r['kind'] == 'job'} or not set(stations) <= {r['code'] for r in options if r['kind'] == 'station'}:
        fail(422, '请先在岗位与吧台配置中添加对应标识')
    if len(set(stations)) != len(stations):
        fail(422, '吧台不能重复')


@router.get('/api/config')
def configuration(user=Depends(identity)):
    with connect(True) as db:
        ensure_options(db, user['store'])
        return [dict(r) for r in db.execute('SELECT kind,code,label FROM scope_options WHERE store=? ORDER BY kind,code', (user['store'],))]


@router.post('/api/admin/scope-options')
def save_option(data: ScopeOption, user=Depends(admin)):
    with connect(True) as db:
        ensure_options(db, user['store'])
        db.execute('INSERT INTO scope_options VALUES(?,?,?,?) ON CONFLICT(store,kind,code) DO UPDATE SET label=excluded.label',
                   (user['store'], data.kind, data.code, data.label))
        audit(db, user, 'scope_option_saved', data.kind + ':' + data.code)
    return {'ok': True}


@router.post('/api/manage/revisions/{rid}/edit')
def edit_draft(rid: int, data: DraftEdit, user=Depends(manager)):
    with connect(True) as db:
        doc, rev = get_revision(db, rid, user)
        if rev['state'] != 'draft':
            fail(409, '只能编辑草稿；待审核或已发布内容不可覆盖')
        if not set(json.loads(doc['stations'])) <= set(json.loads(user['stations'])):
            fail(403, '无权编辑其他吧台的知识')
        if rev['edit_version'] != data.edit_version:
            fail(409, '草稿已被修改，请重新打开后核对，当前输入尚未保存')
        if doc['kind'] == 'recipe' and (not data.content.ingredients or not data.content.technique or not data.content.glass):
            fail(422, '配方必须填写原料、技法和杯型')
        db.execute('UPDATE revisions SET content=?,source=?,edit_version=edit_version+1 WHERE id=?',
                   (encode(data.content.model_dump()), data.source, rid))
        audit(db, user, 'draft_edited', rid)
    return {'id': rid, 'edit_version': data.edit_version + 1}


@router.get('/api/manage/revisions/{rid}/diff')
def revision_diff(rid: int, user=Depends(manager)):
    with connect() as db:
        doc, rev = get_revision(db, rid, user)
        previous = db.execute('SELECT * FROM revisions WHERE document_id=? AND version<? AND approved_at IS NOT NULL ORDER BY version DESC LIMIT 1', (doc['id'], rev['version'])).fetchone()
        before = {'content': json.loads(previous['content']), 'source': previous['source']} if previous else None
        after = {'content': json.loads(rev['content']), 'source': rev['source']}
    return {'revision_id': rid, 'previous_version': previous['version'] if previous else None, 'before': before, 'after': after,
            'changed_fields': [k for k in after['content'] if before is None or before['content'].get(k) != after['content'][k]] + (['source'] if before is None or before['source'] != after['source'] else [])}


@router.post('/api/password')
def change_password(data: PasswordChange, user=Depends(identity)):
    with connect(True) as db:
        stored = db.execute('SELECT password FROM users WHERE id=?', (user['id'],)).fetchone()['password']
        if not verify_password(data.current_password, stored):
            fail(403, '当前密码不正确')
        if verify_password(data.new_password, stored):
            fail(422, '新密码不能与当前密码相同')
        db.execute('UPDATE users SET password=?,must_change_password=0 WHERE id=?', (password_hash(data.new_password), user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        audit(db, user, 'password_changed', user['id'])
    return {'ok': True, 'message': '密码已修改，请使用新密码重新登录'}


@router.post('/api/admin/users/{uid}/reset-password')
def reset_password(uid: int, data: PasswordReset, user=Depends(admin)):
    if uid == user['id']:
        fail(409, '请使用修改密码功能修改自己的密码')
    with connect(True) as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND store=? AND active=1', (uid, user['store'])).fetchone():
            fail(404, '账号不存在或已停用')
        db.execute('UPDATE users SET password=?,must_change_password=1 WHERE id=?', (password_hash(data.temporary_password), uid))
        db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        audit(db, user, 'password_reset', uid)
    return {'ok': True}


@router.post('/api/admin/users/{uid}/edit')
def edit_user(uid: int, data: UserEdit, user=Depends(admin)):
    if uid == user['id']:
        fail(409, '不可修改自己的角色与范围，避免管理员被锁定')
    with connect(True) as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND store=? AND active=1', (uid, user['store'])).fetchone():
            fail(404, '账号不存在或已停用')
        validate_options(db, user['store'], data.job, data.stations)
        db.execute('UPDATE users SET name=?,role=?,job=?,stations=? WHERE id=?', (data.name, data.role, data.job, encode(data.stations), uid))
        db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        audit(db, user, 'user_scope_changed', uid)
    return {'ok': True}

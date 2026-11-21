"""Immutable course editions, relearning assignments and skill evidence."""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from .db import audit, connect, encode, now
from .main import (Input, ModuleIn, active_materials, assignment_row, fail,
                   identity, manager, normalized_date, scope)

router = APIRouter()


class CourseVersion(ModuleIn):
    change_note: str = Field(min_length=5, max_length=1000)
    due_at: str | None = None


class Review(Input):
    passed: bool
    note: str = Field(min_length=5, max_length=1000)
    evidence: str = Field(min_length=5, max_length=2000)

    @field_validator('note', 'evidence')
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError('观察记录和技能证据至少5字')
        return value.strip()


def course_key(module):
    return module['course_id'] or module['id']


def latest(db, module):
    return db.execute('SELECT * FROM modules WHERE COALESCE(course_id,id)=? ORDER BY version DESC LIMIT 1',
                      (course_key(module),)).fetchone()


def create_course(db, data, user, previous=None):
    if any(q.answer >= len(q.options) or any(not o.strip() for o in q.options) for q in data.quiz):
        fail(422, '测验选项或正确答案无效')
    if len(set(data.revision_ids)) != len(data.revision_ids):
        fail(422, '请勿重复选择资料')
    active_materials(db, data.revision_ids, user)
    if previous and len(data.change_note.strip()) < 5:
        fail(422, '请填写至少5字的课程变更原因')
    if previous and latest(db, previous)['id'] != previous['id']:
        fail(409, '课程已有新版本，请打开最新课程')
    version = previous['version'] + 1 if previous else 1
    cid = course_key(previous) if previous else None
    mid = db.execute('INSERT INTO modules(store,title,objective,revision_ids,quiz,pass_score,created_by,course_id,version,change_note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (user['store'],data.title,data.objective,encode(data.revision_ids),encode([q.model_dump() for q in data.quiz]),data.pass_score,user['id'],cid,version,getattr(data,'change_note',''),now())).lastrowid
    if not previous:
        db.execute('UPDATE modules SET course_id=? WHERE id=?', (mid,mid))
    assigned, blocked = [], []
    due = normalized_date(data.due_at) if getattr(data,'due_at',None) else None
    if due and due <= now():
        fail(422, '重学截止时间必须晚于当前时间')
    if previous:
        audience = db.execute('SELECT DISTINCT u.* FROM assignments a JOIN modules m ON m.id=a.module_id JOIN users u ON u.id=a.user_id WHERE COALESCE(m.course_id,m.id)=? AND u.active=1', (cid,)).fetchall()
        for original in audience:
            from .tenancy import scoped_person
            target = scoped_person(db, original['id'], user['store'])
            if not target:
                blocked.append({'user_id':original['id'],'name':original['name'],'reason':'已失去该门店授权'})
                continue
            try:
                active_materials(db, data.revision_ids, target)
            except HTTPException:
                blocked.append({'user_id':target['id'],'name':target['name'],'reason':'当前岗位或吧台无资料权限'})
                continue
            aid = db.execute('INSERT INTO assignments(module_id,user_id,assigned_by,assigned_at,due_at) VALUES(?,?,?,?,?)', (mid,target['id'],user['id'],now(),due)).lastrowid
            db.execute('UPDATE assignments SET superseded_by=? WHERE user_id=? AND module_id IN (SELECT id FROM modules WHERE COALESCE(course_id,id)=? AND id<>?) AND superseded_by IS NULL', (aid,target['id'],cid,mid))
            assigned.append(target['id'])
    audit(db,user,'course_version_created' if previous else 'module_created',mid)
    return {'id':mid,'course_id':cid or mid,'version':version,'reassigned':assigned,'blocked':blocked}


def assignment_status(db, row, target):
    item = dict(row)
    module = db.execute('SELECT * FROM modules WHERE id=?', (row['module_id'],)).fetchone()
    item.update(version=module['version'],course_id=course_key(module))
    reason = None
    try:
        active_materials(db,json.loads(module['revision_ids']),target)
    except HTTPException:
        reason = '资料已更新、停用或超出当前权限'
    obsolete = latest(db,module)['id'] != module['id']
    item['stale'] = bool(reason or obsolete or row['superseded_by'])
    item['stale_reason'] = reason or ('课程已有新版本，请完成重学' if obsolete else '')
    item['status'] = 'stale' if item['stale'] else 'completed' if row['practical_at'] else 'practical' if row['best_score'] is not None and row['best_score'] >= module['pass_score'] else 'learning'
    item['overdue'] = bool(row['due_at'] and row['due_at'] < now() and item['status'] != 'completed' and not row['superseded_by'])
    return item


def require_current_course(db, row):
    module = db.execute('SELECT * FROM modules WHERE id=?', (row['module_id'],)).fetchone()
    if row['superseded_by'] or latest(db,module)['id'] != module['id']:
        fail(409,'课程已有新版本，请完成重学任务')


@router.post('/api/manage/modules/{mid}/version')
def new_version(mid: int, data: CourseVersion, user=Depends(manager)):
    with connect(True) as db:
        previous = db.execute('SELECT * FROM modules WHERE id=? AND store=?',(mid,user['store'])).fetchone()
        if not previous:
            fail(404,'课程不存在')
        return create_course(db,data,user,previous)


@router.post('/api/manage/training/{aid}/reviews')
def review(aid: int, data: Review, user=Depends(manager)):
    with connect(True) as db:
        row = assignment_row(db,aid,user)
        require_current_course(db,row)
        if row['user_id'] == user['id']:
            fail(403,'不可验收自己的任务')
        from .tenancy import scoped_person
        target = scoped_person(db,row['user_id'],user['store'])
        if not target:
            fail(409,'员工账号已停用')
        active_materials(db,json.loads(row['revision_ids']),target)
        active_materials(db,json.loads(row['revision_ids']),user)
        if row['practical_at'] or row['best_score'] is None or row['best_score'] < row['pass_score']:
            fail(409,'须先通过理论测验，且不能重复验收已完成任务')
        if not data.note.strip() or not data.evidence.strip():
            fail(422,'请填写观察记录和证据')
        rid = db.execute('INSERT INTO practical_reviews(assignment_id,reviewer_id,passed,note,evidence,created_at) VALUES(?,?,?,?,?,?)',(aid,user['id'],data.passed,data.note,data.evidence,now())).lastrowid
        if data.passed:
            db.execute('UPDATE assignments SET practical_by=?,practical_note=?,practical_at=? WHERE id=?',(user['id'],data.note,now(),aid))
        audit(db,user,'practical_passed' if data.passed else 'practical_retry',aid)
    return {'id':rid,'passed':data.passed}


@router.get('/api/academy/evidence')
def evidence(user_id: int | None = None, user=Depends(identity)):
    uid = user_id if user_id is not None else user['id']
    if uid != user['id'] and user['role'] == 'staff':
        fail(403,'只能查看自己的技能证据')
    with connect() as db:
        from .tenancy import scoped_person
        target = scoped_person(db,uid,user['store'],True)
        if not target:
            fail(404,'员工不存在')
        result = []
        for row in db.execute('SELECT a.*,m.title,m.pass_score,m.revision_ids FROM assignments a JOIN modules m ON m.id=a.module_id WHERE a.user_id=? AND m.store=? ORDER BY a.id DESC',(uid,user['store'])):
            item = assignment_status(db,row,target)
            item['materials'] = json.loads(row['revision_ids'])
            item['material_versions'] = []
            for rid in item['materials']:
                material = db.execute('SELECT r.id revision_id,r.version,r.source,d.* FROM revisions r JOIN documents d ON d.id=r.document_id WHERE r.id=? AND d.store=?', (rid,user['store'])).fetchone()
                if material and scope(material,user):
                    item['material_versions'].append({k:material[k] for k in ('revision_id','title','version','source')})
                else:
                    item['material_versions'].append({'revision_id':rid,'title':'超出当前资料权限','version':None,'source':''})
            item['attempts'] = [dict(r) for r in db.execute('SELECT id,score,created_at FROM attempts WHERE assignment_id=? ORDER BY id',(row['id'],))]
            item['reviews'] = [dict(r) for r in db.execute('SELECT r.*,u.name reviewer_name FROM practical_reviews r JOIN users u ON u.id=r.reviewer_id WHERE assignment_id=? ORDER BY r.id',(row['id'],))]
            item['qualified'] = item['status'] == 'completed' and bool(target['active'])
            result.append(item)
        return {'user_id':uid,'name':target['name'],'items':result,'definition':'技能证据仅对应记录中的课程和资料版本；理论通过后仍须主管实操通过。失效或旧版记录保留，但不代表当前具备上岗资格。'}

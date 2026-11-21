"""BarOS pilot: approved evidence retrieval, without generative answers."""
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import ROOT, audit, connect, encode, initialize, now, password_hash, verify_password


def fail(status, message):
    raise HTTPException(status, message)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(Input):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class Ask(Input):
    question: str = Field(min_length=2, max_length=500)
    station: str = Field(min_length=1, max_length=80)


class Ingredient(Input):
    name: str = Field(min_length=1, max_length=80)
    amount: str = Field(min_length=1, max_length=20, pattern=r'^\d+(\.\d+)?$')
    unit: Literal['ml', 'g', '滴', '片', '个', '份']


class ServiceFields(Input):
    context: str = Field(min_length=5,max_length=1000)
    response: str = Field(min_length=5,max_length=2000)
    escalation_trigger: str = Field(default='',max_length=1000)
    escalation_contact: str = Field(default='',max_length=300)
    practice_prompt: str = Field(default='',max_length=2000)
    assessment_points: list[str] = Field(default_factory=list,max_length=20)


class Content(Input):
    summary: str = Field(min_length=1, max_length=2000)
    service: ServiceFields | None = None
    steps: list[str] = Field(min_length=1, max_length=30)
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=30)
    technique: str = Field(default='', max_length=300)
    glass: str = Field(default='', max_length=100)
    garnish: str = Field(default='', max_length=100)
    allergens: list[str] = Field(default_factory=list, max_length=30)

    @field_validator('steps', 'allergens')
    @classmethod
    def bounded_text(cls, values):
        if any(not x.strip() or len(x) > 1000 for x in values):
            raise ValueError('步骤或过敏原文本为空或过长')
        return values


class Draft(Input):
    document_id: int | None = None
    title: str = Field(min_length=1, max_length=120)
    kind: Literal['recipe', 'sop', 'rule', 'service_script', 'complaint_card', 'service_scenario']
    jobs: list[str] = Field(min_length=1, max_length=20)
    stations: list[str] = Field(min_length=1, max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    risk: bool = False
    source: str = Field(min_length=1, max_length=500)
    content: Content
    change_reason: str = Field(default='', max_length=1000)


class RevisionSubmit(Input):
    edit_version: int | None = Field(default=None, ge=1)


class Publish(Input):
    effective_at: str
    expires_at: str | None = None
    risk_confirmed: bool = False


class FeedbackIn(Input):
    query_id: int
    kind: Literal['helpful', 'missing', 'error']
    description: str = Field(default='', max_length=2000)


class Resolve(Input):
    resolution: str = Field(min_length=1, max_length=1000)


class QuizQuestion(Input):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0)


class ModuleIn(Input):
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)
    revision_ids: list[int] = Field(min_length=1, max_length=30)
    quiz: list[QuizQuestion] = Field(min_length=1, max_length=30)
    pass_score: int = Field(ge=1, le=100, default=80)


class Assign(Input):
    module_id: int
    user_id: int
    due_at: str | None = None


class Submit(Input):
    answers: list[int] = Field(max_length=30)


class Practical(Input):
    note: str = Field(min_length=5, max_length=1000)


class UserIn(Input):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=200)
    role: Literal['staff', 'manager', 'admin']
    job: str = Field(min_length=1, max_length=80)
    stations: list[str] = Field(min_length=1, max_length=20)


def public_user(user):
    result = {k: json.loads(user[k]) if k == 'stations' else user[k]
              for k in ('id', 'username', 'name', 'role', 'store', 'job', 'stations', 'must_change_password')}
    data = dict(user)
    return {**result, 'home_store': data.get('home_store',user['store']), 'tenant_id': data.get('tenant_id'), 'hq_owner': bool(data.get('hq_owner',False))}


def identity(request: Request):
    token = request.cookies.get('baros_session', '')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect(True) as db:
        row = db.execute('SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id '
                         'WHERE s.token=? AND s.expires>? AND u.active=1', (digest, now())).fetchone()
    if not row:
        fail(401, '请先登录')
    if row['must_change_password'] and request.url.path not in ('/api/me', '/api/password', '/api/logout'):
        fail(403, '请先修改初始密码')
    if request.method != 'GET' and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), row['csrf']):
        fail(403, '请求校验失败，请刷新后重试')
    from .tenancy import context
    with connect(True) as db:
        return context(db, dict(row), request.headers.get('x-baros-store') if request.url.path not in ('/api/logout','/api/password') else None)


def manager(user=Depends(identity)):
    if user['role'] not in ('manager', 'admin'):
        fail(403, '需要主管权限')
    return user


def admin(user=Depends(identity)):
    if user['role'] != 'admin':
        fail(403, '需要管理员权限')
    return user


def scope(doc, user, station=None):
    stations = json.loads(user['stations'])
    return (doc['store'] == user['store'] and user['job'] in json.loads(doc['jobs'])
            and bool(set(stations) & set(json.loads(doc['stations'])))
            and (station is None or station in stations and station in json.loads(doc['stations'])))


def current(db, document_id):
    # Do not resurrect an earlier standard if the newest applicable approval is retired/expired.
    row = db.execute('SELECT * FROM revisions WHERE document_id=? AND approved_at IS NOT NULL '
                     'AND effective_at<=? ORDER BY version DESC LIMIT 1', (document_id, now())).fetchone()
    if row and row['state'] == 'published' and (not row['expires_at'] or row['expires_at'] > now()):
        return dict(row)
    return None


def card(doc, revision):
    return {**dict(doc), 'jobs': json.loads(doc['jobs']), 'stations': json.loads(doc['stations']),
            'aliases': json.loads(doc['aliases']), 'revision_id': revision['id'],
            'version': revision['version'], 'state': revision['state'],
            'effective_at': revision['effective_at'], 'expires_at': revision['expires_at'],
            'source': revision['source'], 'content': json.loads(revision['content'])}


def accessible(db, user, station=None):
    result = []
    for doc in db.execute('SELECT * FROM documents WHERE store=? ORDER BY id', (user['store'],)):
        if scope(doc, user, station):
            rev = current(db, doc['id'])
            if rev:
                result.append(card(doc, rev))
    return result


def get_revision(db, revision_id, user):
    revision = db.execute('SELECT * FROM revisions WHERE id=?', (revision_id,)).fetchone()
    if not revision:
        fail(404, '资料不存在')
    doc = db.execute('SELECT * FROM documents WHERE id=? AND store=?',
                     (revision['document_id'], user['store'])).fetchone()
    if not doc:
        fail(404, '资料不存在')
    return doc, revision


def active_materials(db, ids, user):
    results = []
    for revision_id in ids:
        doc, rev = get_revision(db, revision_id, user)
        active = current(db, doc['id'])
        if not scope(doc, user) or not active or active['id'] != rev['id']:
            fail(409, '培训资料已更新、停用或不在员工权限内，请主管重新分配有效模块')
        results.append(card(doc, rev))
    return results


def normalized_date(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            fail(422, '时间必须包含时区')
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
    except ValueError:
        fail(422, '时间格式无效')


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title='BarOS', version='0.6.0', lifespan=lifespan)


@app.middleware('http')
async def guard(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return Response('Cross-origin request rejected', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'answer_mode': 'approved_extracts'}


@app.post('/api/login')
def login(data: Login, response: Response, request: Request):
    key = hashlib.sha256((request.client.host + ':' + data.username).encode()).hexdigest()
    with connect(True) as db:
        limit = db.execute('SELECT * FROM login_limits WHERE key=?', (key,)).fetchone()
        if limit and limit['reset'] > time.time() and limit['count'] >= 8:
            fail(429, '尝试过于频繁，请 15 分钟后重试')
        db.execute('INSERT INTO login_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET '
                   'count=CASE WHEN reset<? THEN 1 ELSE count+1 END, '
                   'reset=CASE WHEN reset<? THEN excluded.reset ELSE reset END',
                   (key, time.time() + 900, time.time(), time.time()))
        user = db.execute('SELECT * FROM users WHERE username=? AND active=1', (data.username,)).fetchone()
        valid = verify_password(data.password, user['password'] if user else DUMMY_PASSWORD)
        if valid and user:
            db.execute('DELETE FROM login_limits WHERE key=?', (key,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?', (now(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf,
                        (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(timespec='seconds')))
    if not valid or not user:
        fail(401, '账号或密码不正确')
    response.set_cookie('baros_session', token, httponly=True, samesite='strict',
                        secure=os.getenv('BAROS_SECURE_COOKIE') == '1', max_age=43200)
    from .tenancy import context
    with connect(True) as db:
        logged_user = context(db, dict(user))
    return {'user': public_user(logged_user), 'csrf': csrf}


DUMMY_PASSWORD = password_hash(secrets.token_urlsafe(20))


@app.get('/api/me')
def me(user=Depends(identity)):
    return {'user': public_user(user), 'csrf': user['csrf']}


@app.post('/api/logout')
def logout(response: Response, request: Request, user=Depends(identity)):
    with connect(True) as db:
        db.execute('DELETE FROM sessions WHERE token=?',
                   (hashlib.sha256(request.cookies['baros_session'].encode()).hexdigest(),))
    response.delete_cookie('baros_session')
    return {'ok': True}


@app.get('/api/knowledge')
def knowledge(station: str | None = None, user=Depends(identity)):
    if station and station not in json.loads(user['stations']):
        fail(403, '无权访问该吧台')
    with connect() as db:
        return accessible(db, user, station)


@app.get('/api/knowledge/{document_id}')
def detail(document_id: int, user=Depends(identity)):
    with connect() as db:
        for item in accessible(db, user):
            if item['id'] == document_id:
                return item
    fail(404, '未找到已授权的有效知识')


@app.post('/api/ask')
def ask(data: Ask, user=Depends(identity)):
    if data.station not in json.loads(user['stations']):
        fail(403, '无权访问该吧台')
    from .retrieval import retrieve, evidence
    started = time.perf_counter()
    with connect(True) as db:
        sources, status = retrieve(data.question, accessible(db, user, data.station))
        citations = []
        if status == 'answered':
            citation, status = evidence(data.question, sources[0])
            if citation:
                citations.append(citation)
        if status == 'no_evidence':
            sources = []
        query_id = db.execute('INSERT INTO queries(user_id,store,station,question,revision_ids,resolved,created_at) VALUES(?,?,?,?,?,?,?)',
                              (user['id'],user['store'],data.station,data.question,encode([x['revision_id'] for x in sources]),bool(citations),now())).lastrowid
        supervisors = [{'id':r['id'],'name':r['name']} for r in db.execute("SELECT id,name,stations FROM users WHERE store=? AND active=1 AND role IN ('manager','admin')",(user['store'],)) if data.station in json.loads(r['stations'])]
    messages = {'answered':'找到以下有效标准，请按资料核对操作。','needs_clarification':'找到多个可能适用的标准，请选择知识卡核对。','no_evidence':'未找到已审核标准，请咨询当班主管。请勿凭猜测操作。','needs_supervisor':'该问题需要主管确认，请勿自行替换配方或作安全保证。下方资料仅供核对。'}
    return {'query_id':query_id,'resolved':bool(citations),'sources':sources,'status':status,'citations':citations,
            'answer':citations[0]['text'] if citations else None,'message':messages[status],
            'supervisors':supervisors,'retrieval_mode':'local_hybrid','elapsed_ms':round((time.perf_counter()-started)*1000,2)}


@app.post('/api/feedback')
def feedback(data: FeedbackIn, user=Depends(identity)):
    with connect(True) as db:
        query = db.execute('SELECT id FROM queries WHERE id=? AND user_id=? AND store=?',
                           (data.query_id, user['id'], user['store'])).fetchone()
        if not query:
            fail(404, '查询记录不存在')
        fid = db.execute('INSERT INTO feedback(query_id,user_id,kind,description,created_at) VALUES(?,?,?,?,?)',
                         (data.query_id, user['id'], data.kind, data.description, now())).lastrowid
    return {'id': fid}


@app.get('/api/manage/revisions')
def revisions(user=Depends(manager)):
    with connect() as db:
        rows = db.execute('SELECT r.*,d.title,d.kind,d.risk,d.jobs,d.stations,d.aliases FROM revisions r JOIN documents d ON d.id=r.document_id '
                          'WHERE d.store=? ORDER BY r.id DESC', (user['store'],)).fetchall()
        return [{**dict(r), 'content': json.loads(r['content'])} for r in rows]


@app.post('/api/manage/drafts')
def draft(data: Draft, user=Depends(manager)):
    with connect(True) as db:
        return create_draft_record(db, data, user)


def create_draft_record(db, data, user):
    from .service import validate_service
    validate_service(data.kind, data.content)
    if data.kind == 'complaint_card':
        data = data.model_copy(update={'risk': True})
    if data.kind == 'recipe' and (not data.content.ingredients or not data.content.technique or not data.content.glass):
        fail(422, '配方必须填写原料、技法和杯型')
    if not set(data.stations) <= set(json.loads(user['stations'])):
        fail(403, '不可创建其他吧台的知识')
    if data.document_id:
        doc = db.execute('SELECT * FROM documents WHERE id=? AND store=?',
                         (data.document_id, user['store'])).fetchone()
        if not doc:
            fail(404, '知识不存在')
        expected = (data.title, data.kind, data.jobs, data.stations, data.aliases, int(data.risk))
        actual = (doc['title'], doc['kind'], json.loads(doc['jobs']), json.loads(doc['stations']), json.loads(doc['aliases']), doc['risk'])
        if expected != actual:
            fail(422, '同一知识的新版本须保留标题、分类及适用范围；调整范围请建立新知识')
        document_id = data.document_id
    else:
        document_id = db.execute('INSERT INTO documents(store,title,kind,jobs,stations,aliases,risk) VALUES(?,?,?,?,?,?,?)',
                                 (user['store'], data.title, data.kind, encode(data.jobs), encode(data.stations), encode(data.aliases), data.risk)).lastrowid
    version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM revisions WHERE document_id=?', (document_id,)).fetchone()[0]
    rid = db.execute('INSERT INTO revisions(document_id,version,state,content,source,created_by) VALUES(?,?,?,?,?,?)',
                     (document_id, version, 'draft', encode(data.content.model_dump()), data.source, user['id'])).lastrowid
    audit(db, user, 'draft_created', rid)
    db.execute('UPDATE revisions SET change_reason=? WHERE id=?', (data.change_reason, rid))
    from .memory import record_event
    record_event(db, document_id, rid, user, 'draft_created', {'reason': data.change_reason})
    return {'id': rid, 'document_id': document_id, 'version': version}


@app.post('/api/manage/revisions/{rid}/submit')
def submit_revision(rid: int, data: RevisionSubmit, user=Depends(manager)):
    with connect(True) as db:
        _, rev = get_revision(db, rid, user)
        if rev['state'] != 'draft':
            fail(409, '只能提交草稿')
        if data.edit_version is not None and data.edit_version != rev['edit_version']:
            fail(409, '草稿已更新，请重新查看后提交')
        db.execute("UPDATE revisions SET state='review' WHERE id=?", (rid,))
        audit(db, user, 'submitted', rid)
        from .memory import record_event
        record_event(db, rev['document_id'], rid, user, 'submitted', {})
    return {'ok': True}


@app.post('/api/manage/revisions/{rid}/publish')
def publish(rid: int, data: Publish, user=Depends(manager)):
    effective = normalized_date(data.effective_at)
    expires = normalized_date(data.expires_at) if data.expires_at else None
    if expires and expires <= max(effective, now()):
        fail(422, '失效时间须晚于生效时间及当前时间')
    with connect(True) as db:
        doc, rev = get_revision(db, rid, user)
        if rev['state'] != 'review':
            fail(409, '只能发布待审核版本')
        from .service import validate_service
        validate_service(doc['kind'], Content.model_validate(json.loads(rev['content'])))
        if (doc['risk'] or doc['kind'] == 'complaint_card' or (doc['kind'] == 'recipe' and json.loads(rev['content']).get('allergens'))) and not data.risk_confirmed:
            fail(422, '高风险知识须由负责人确认标准资料')
        if db.execute('SELECT 1 FROM revisions WHERE document_id=? AND approved_at IS NOT NULL AND version>?',
                      (doc['id'], rev['version'])).fetchone():
            fail(409, '已有更新的批准版本，请创建新版本')
        db.execute("UPDATE revisions SET state='published',effective_at=?,expires_at=?,approved_by=?,approved_at=? WHERE id=?",
                   (effective, expires, user['id'], now(), rid))
        audit(db, user, 'published', rid)
        from .memory import record_event
        record_event(db, doc['id'], rid, user, 'published', {'effective_at': effective})
    return {'ok': True}


@app.post('/api/manage/revisions/{rid}/retire')
def retire(rid: int, user=Depends(manager)):
    with connect(True) as db:
        _, rev = get_revision(db, rid, user)
        if rev['state'] != 'published':
            fail(409, '只能停用已发布版本')
        db.execute("UPDATE revisions SET state='retired' WHERE id=?", (rid,))
        audit(db, user, 'retired', rid)
        from .memory import record_event
        record_event(db, rev['document_id'], rid, user, 'retired', {})
    return {'ok': True}


@app.get('/api/manage/feedback')
def feedback_list(user=Depends(manager)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT f.*,q.question,q.revision_ids FROM feedback f JOIN queries q ON q.id=f.query_id '
                                           'WHERE q.store=? ORDER BY f.id DESC', (user['store'],))]


@app.post('/api/manage/feedback/{fid}/resolve')
def resolve_feedback(fid: int, data: Resolve, user=Depends(manager)):
    with connect(True) as db:
        if not db.execute('SELECT 1 FROM feedback f JOIN queries q ON q.id=f.query_id WHERE f.id=? AND q.store=?', (fid, user['store'])).fetchone():
            fail(404, '反馈不存在')
        if db.execute("SELECT 1 FROM knowledge_proposals WHERE feedback_id=? AND state IN ('open','draft_created')", (fid,)).fetchone():
            fail(409, '反馈已转为提案，请在提案中记录驳回或生效后的完成结果')
        db.execute("UPDATE feedback SET state='closed',resolution=? WHERE id=?", (data.resolution, fid))
        audit(db, user, 'feedback_resolved', fid)
    return {'ok': True}


@app.post('/api/manage/modules')
def create_module(data: ModuleIn, user=Depends(manager)):
    from .academy import create_course
    with connect(True) as db:
        return create_course(db, data, user)


@app.get('/api/manage/modules')
def list_modules(user=Depends(manager)):
    from .academy import latest
    with connect() as db:
        result = []
        for r in db.execute('SELECT * FROM modules WHERE store=? ORDER BY id DESC', (user['store'],)):
            item = {**dict(r), 'course_id': r['course_id'] or r['id'], 'revision_ids': json.loads(r['revision_ids']), 'quiz': json.loads(r['quiz']), 'is_latest': latest(db, r)['id'] == r['id']}
            try:
                active_materials(db, item['revision_ids'], user)
                item['stale'] = False
            except HTTPException:
                item['stale'] = True
            result.append(item)
        return result


@app.post('/api/manage/assignments')
def assign(data: Assign, user=Depends(manager)):
    with connect(True) as db:
        module = db.execute('SELECT * FROM modules WHERE id=? AND store=?', (data.module_id, user['store'])).fetchone()
        from .tenancy import scoped_person
        target = scoped_person(db, data.user_id, user['store'])
        if not module or not target:
            fail(404, '员工或培训模块不存在')
        from .academy import latest
        if latest(db, module)['id'] != module['id']:
            fail(409, '请分配最新课程版本')
        active_materials(db, json.loads(module['revision_ids']), user)
        active_materials(db, json.loads(module['revision_ids']), target)
        due = normalized_date(data.due_at) if data.due_at else None
        if due and due <= now():
            fail(422, '截止时间必须晚于当前时间')
        if db.execute('SELECT 1 FROM assignments WHERE module_id=? AND user_id=?', (data.module_id, data.user_id)).fetchone():
            fail(409, '该员工已被分配此模块')
        aid = db.execute('INSERT INTO assignments(module_id,user_id,assigned_by,assigned_at,due_at) VALUES(?,?,?,?,?)', (data.module_id, data.user_id, user['id'], now(), due)).lastrowid
        db.execute('UPDATE assignments SET superseded_by=? WHERE user_id=? AND id<>? AND superseded_by IS NULL AND module_id IN (SELECT id FROM modules WHERE COALESCE(course_id,id)=?)', (aid, data.user_id, aid, module['course_id'] or module['id']))
        audit(db, user, 'training_assigned', aid)
    return {'id': aid}


def assignment_row(db, aid, user, own=False):
    row = db.execute('SELECT a.*,m.title,m.objective,m.revision_ids,m.quiz,m.pass_score FROM assignments a '
                     'JOIN modules m ON m.id=a.module_id WHERE a.id=? AND m.store=?', (aid, user['store'])).fetchone()
    if not row or (own and row['user_id'] != user['id']):
        fail(404, '任务不存在')
    return row


@app.get('/api/training')
def training(user=Depends(identity)):
    with connect() as db:
        rows = db.execute('SELECT a.*,m.title,m.pass_score FROM assignments a JOIN modules m ON m.id=a.module_id '
                          'WHERE a.user_id=? AND m.store=?', (user['id'], user['store'])).fetchall()
        from .academy import assignment_status
        return [assignment_status(db, r, user) for r in rows]


@app.get('/api/training/{aid}')
def training_detail(aid: int, user=Depends(identity)):
    with connect() as db:
        row = assignment_row(db, aid, user, True)
        from .academy import require_current_course
        require_current_course(db, row)
        materials = active_materials(db, json.loads(row['revision_ids']), user)
        quiz = [{k: v for k, v in q.items() if k != 'answer'} for q in json.loads(row['quiz'])]
        return {**dict(row), 'quiz': quiz, 'materials': materials}


@app.post('/api/training/{aid}/submit')
def exam(aid: int, data: Submit, user=Depends(identity)):
    with connect(True) as db:
        row = assignment_row(db, aid, user, True)
        from .academy import require_current_course
        require_current_course(db, row)
        active_materials(db, json.loads(row['revision_ids']), user)
        quiz = json.loads(row['quiz'])
        if len(data.answers) != len(quiz) or any(a < 0 or a >= len(q['options']) for a, q in zip(data.answers, quiz)):
            fail(422, '请完成全部试题')
        score = round(100 * sum(a == q['answer'] for a, q in zip(data.answers, quiz)) / len(quiz))
        db.execute('INSERT INTO attempts(assignment_id,score,created_at) VALUES(?,?,?)', (aid, score, now()))
        db.execute('UPDATE assignments SET best_score=MAX(COALESCE(best_score,0),?) WHERE id=?', (score, aid))
    return {'score': score, 'passed': score >= row['pass_score'], 'message': '理论测验通过后，仍需主管进行实际操作验收。'}


@app.get('/api/manage/training')
def progress(user=Depends(manager)):
    from .academy import assignment_status
    with connect() as db:
        result = []
        for r in db.execute('SELECT a.*,m.title,m.pass_score,u.name FROM assignments a JOIN modules m ON m.id=a.module_id JOIN users u ON u.id=a.user_id WHERE m.store=?', (user['store'],)):
            from .tenancy import scoped_person
            target = scoped_person(db, r['user_id'], user['store'], True) or db.execute('SELECT * FROM users WHERE id=?',(r['user_id'],)).fetchone()
            result.append({**assignment_status(db, r, target), 'active': bool(target['active'])})
        return result


@app.post('/api/manage/training/{aid}/practical')
def practical(aid: int, data: Practical, user=Depends(manager)):
    if len(data.note.strip()) < 5:
        fail(422, '请填写至少5字的实操观察记录')
    with connect(True) as db:
        row = assignment_row(db, aid, user)
        from .academy import require_current_course
        require_current_course(db, row)
        active_materials(db, json.loads(row['revision_ids']), user)
        if row['user_id'] == user['id']:
            fail(403, '不可验收自己的上岗任务')
        from .tenancy import scoped_person
        target = scoped_person(db, row['user_id'], user['store'])
        if not target:
            fail(409, '员工账号已停用')
        active_materials(db, json.loads(row['revision_ids']), target)
        if row['best_score'] is None or row['best_score'] < row['pass_score']:
            fail(409, '请先完成理论测验')
        if row['practical_at']:
            fail(409, '已经验收，请保留原始记录')
        db.execute('UPDATE assignments SET practical_by=?,practical_note=?,practical_at=? WHERE id=?', (user['id'], data.note, now(), aid))
        db.execute('INSERT INTO practical_reviews(assignment_id,reviewer_id,passed,note,evidence,created_at) VALUES(?,?,1,?,?,?)', (aid, user['id'], data.note, data.note, now()))
        audit(db, user, 'practical_confirmed', aid)
    return {'ok': True}


@app.get('/api/manage/users')
def users(user=Depends(manager)):
    with connect() as db:
        from .tenancy import scoped_people
        return [public_user(r) for r in scoped_people(db, user['store'])]


@app.post('/api/admin/users')
def create_user(data: UserIn, user=Depends(admin)):
    from .maintenance import validate_options
    with connect(True) as db:
        validate_options(db, user['store'], data.job, data.stations)
        if db.execute('SELECT 1 FROM users WHERE username=?', (data.username,)).fetchone():
            fail(409, '账号已存在')
        uid = db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)',
                         (data.username, data.name, password_hash(data.password), data.role, user['store'], data.job, encode(data.stations))).lastrowid
        db.execute('UPDATE users SET must_change_password=1 WHERE id=?', (uid,))
        audit(db, user, 'user_created', uid)
    return {'id': uid}


@app.post('/api/admin/users/{uid}/deactivate')
def deactivate(uid: int, user=Depends(admin)):
    if uid == user['id']:
        fail(409, '不可停用自己的账号')
    with connect(True) as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND store=?', (uid, user['store'])).fetchone():
            fail(404, '账号不存在')
        db.execute('UPDATE users SET active=0 WHERE id=?', (uid,))
        db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        audit(db, user, 'user_deactivated', uid)
    return {'ok': True}


@app.get('/api/manage/stats')
def stats(days: int = 7, user=Depends(manager)):
    if not 1 <= days <= 90:
        fail(422, '统计天数须在 1 至 90 天之间')
    end = now()
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
    with connect() as db:
        row = dict(db.execute('SELECT COUNT(*) queries,COUNT(DISTINCT user_id) users,COALESCE(SUM(1-resolved),0) unresolved '
                               'FROM queries WHERE store=? AND created_at>=? AND created_at<=?', (user['store'], start, end)).fetchone())
        row['frequent'] = [dict(r) for r in db.execute('SELECT question,COUNT(*) count FROM queries WHERE store=? '
                                                      'AND created_at>=? AND created_at<=? GROUP BY question ORDER BY count DESC LIMIT 8', (user['store'], start, end))]
        row['pending'] = db.execute("SELECT COUNT(*) FROM revisions r JOIN documents d ON d.id=r.document_id WHERE d.store=? AND r.state='review'", (user['store'],)).fetchone()[0]
        row['open_feedback'] = db.execute("SELECT COUNT(*) FROM feedback f JOIN queries q ON q.id=f.query_id WHERE q.store=? AND f.state='open' AND f.kind<>'helpful'", (user['store'],)).fetchone()[0]
    return {**row, 'start': start, 'end': end, 'definition': '查询量、人数、未匹配及高频问题按上述时间范围统计；未匹配表示未找到标准，并非实际未解决率。待审核与反馈为当前存量。培训进度见培训管理，为当前快照。'}


@app.get('/api/manage/audit')
def audit_log(user=Depends(manager)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM audit WHERE store=? ORDER BY id DESC LIMIT 200', (user['store'],))]


@app.get('/')
def index():
    return FileResponse(ROOT / 'web' / 'index.html')


from .request_limits import RequestLimitMiddleware
app.add_middleware(RequestLimitMiddleware)

from .maintenance import router as maintenance_router
app.include_router(maintenance_router)
from .memory import router as memory_router
app.include_router(memory_router)


from .academy import router as academy_router
app.include_router(academy_router)
from .operations import router as operations_router
app.include_router(operations_router)

from .service import router as service_router
app.include_router(service_router)
from .inventory import router as inventory_router
app.include_router(inventory_router)
from .insight import router as insight_router
app.include_router(insight_router)

from .hq import router as hq_router
app.include_router(hq_router)
from .tasks import router as tasks_router
app.include_router(tasks_router)
from .agents import router as agents_router
app.include_router(agents_router)

app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')

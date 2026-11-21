"""HQ releases never bypass local adoption, review or active store context."""
import json
from fastapi import APIRouter,Depends
from pydantic import Field
from .db import audit,connect,encode,now
from .main import Input,Content,Draft,fail,identity,manager,normalized_date,create_draft_record,current
from .inventory import CleanInput
from .tenancy import owner_user,permitted_stores,scoped_people
from .business import replay,remember
from .report_math import digest

router=APIRouter()


def owner(user=Depends(identity)):
    return owner_user(user)


class StoreIn(CleanInput):
    code: str = Field(min_length=1,max_length=60,pattern=r'^[a-zA-Z0-9_.-]+$')
    name: str = Field(min_length=2,max_length=120)
    verification_note: str = Field(min_length=5,max_length=1000)
    job: str = Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    station: str = Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')


class GrantIn(CleanInput):
    user_id: int
    store: str
    role: str = Field(pattern=r'^(staff|manager|admin)$')
    job: str
    stations: list[str] = Field(min_length=1,max_length=20)
    expires_at: str
    note: str = Field(min_length=5,max_length=1000)


class Note(CleanInput):
    note: str = Field(min_length=5,max_length=1000)


class TransferIn(Note):
    destination_code: str


class TransferDecision(Note):
    accepted: bool


class TemplateIn(CleanInput):
    template_id: int | None = None
    title: str = Field(min_length=2,max_length=120)
    kind: str = Field(pattern=r'^(recipe|sop|rule|service_script|complaint_card|service_scenario)$')
    content: Content
    source: str = Field(min_length=5,max_length=1000)
    change_note: str = Field(min_length=5,max_length=1000)
    risk: bool = False


class Approve(Input):
    risk_confirmed: bool = False


class Release(CleanInput):
    stores: list[str] = Field(min_length=1,max_length=50)
    idempotency_key: str = Field(min_length=8,max_length=100)


class Sign(Note):
    accepted: bool
    jobs: list[str] = Field(default_factory=list,max_length=20)
    stations: list[str] = Field(default_factory=list,max_length=20)
    local_content: Content | None = None
    difference_note: str = Field(default='',max_length=1000)


def template_row(db,tid,user):
    row=db.execute('SELECT * FROM hq_templates WHERE id=? AND tenant_id=?',(tid,user['tenant_id'])).fetchone()
    if not row:fail(404,'总部模板不存在')
    return row


def delivery_row(db,did,user):
    row=db.execute('SELECT * FROM hq_deliveries WHERE id=? AND tenant_id=?',(did,user['tenant_id'])).fetchone()
    if not row or not user.get('hq_owner') and row['store']!=user['store']:fail(404,'发布记录不存在')
    return row


def rollout(db,row):
    if not row['local_revision_id']:return 'not_adopted'
    rev=db.execute('SELECT * FROM revisions WHERE id=?',(row['local_revision_id'],)).fetchone()
    active=current(db,rev['document_id'])
    if active and active['id']==rev['id']:return 'effective'
    if rev['state']=='published' and rev['effective_at']>now():return 'scheduled'
    return rev['state'] if rev['state'] in ('draft','review','retired') else 'outdated'


@router.get('/api/context')
def store_context(user=Depends(identity)):
    with connect() as db:
        tenant=db.execute('SELECT id,code,name FROM tenants WHERE id=?',(user['tenant_id'],)).fetchone()
        return {'tenant':dict(tenant),'home_store':user['home_store'],'active_store':user['store'],'hq_owner':user['hq_owner'],'stores':permitted_stores(db,user)}


@router.get('/api/hq')
def dashboard(user=Depends(identity)):
    if user['role']=='staff' and not user.get('hq_owner'):fail(403,'需要主管权限')
    with connect() as db:
        result={'owner':user['hq_owner'],'tenant':dict(db.execute('SELECT * FROM tenants WHERE id=?',(user['tenant_id'],)).fetchone())}
        result['stores']=[dict(r) for r in db.execute('SELECT * FROM stores WHERE tenant_id=? ORDER BY code',(user['tenant_id'],))] if user['hq_owner'] else []
        result['people']=[{'id':r['id'],'name':r['name'],'store':r['store']} for r in db.execute('SELECT u.* FROM users u JOIN stores s ON s.code=u.store WHERE s.tenant_id=? AND u.active=1 ORDER BY u.id',(user['tenant_id'],))] if user['hq_owner'] else []
        result['grants']=[dict(r) for r in db.execute('SELECT g.*,u.name FROM store_grants g JOIN users u ON u.id=g.user_id WHERE g.tenant_id=? ORDER BY g.id DESC',(user['tenant_id'],))] if user['hq_owner'] else []
        result['transfers']=[dict(r) for r in db.execute('SELECT * FROM store_transfers WHERE source_tenant=? OR destination_tenant=? ORDER BY id DESC',(user['tenant_id'],user['tenant_id']))] if user['hq_owner'] else []
        result['templates']=[{**dict(r),'content':json.loads(r['content'])} for r in db.execute('SELECT * FROM hq_templates WHERE tenant_id=? ORDER BY id DESC',(user['tenant_id'],))] if user['hq_owner'] else []
        deliveries=db.execute('SELECT d.*,t.title,t.version,t.template_id FROM hq_deliveries d JOIN hq_templates t ON t.id=d.template_version_id WHERE d.tenant_id=?'+('' if user['hq_owner'] else ' AND d.store=?')+' ORDER BY d.id DESC', (user['tenant_id'],) if user['hq_owner'] else (user['tenant_id'],user['store'])).fetchall()
        result['deliveries']=[{**dict(r),'rollout':rollout(db,r)} for r in deliveries]
        return result


@router.post('/api/hq/stores')
def create_store(data: StoreIn,user=Depends(owner)):
    with connect(True) as db:
        if db.execute('SELECT 1 FROM stores WHERE code=?',(data.code,)).fetchone():fail(409,'门店标识已使用')
        db.execute('INSERT INTO stores VALUES(?,?,?,?,?)',(data.code,user['tenant_id'],data.name,data.verification_note,now()))
        db.executemany('INSERT INTO scope_options VALUES(?,?,?,?)',[(data.code,'job',data.job,data.job),(data.code,'station',data.station,data.station)])
        audit(db,user,'hq_store_created',data.code)
    return {'code':data.code,'message':'门店已登记；访问业务数据仍须显式跨店授权。'}


@router.post('/api/hq/grants')
def grant(data: GrantIn,user=Depends(owner)):
    from .maintenance import validate_options
    expiry=normalized_date(data.expires_at)
    if expiry<=now():fail(422,'授权到期时间须晚于现在')
    with connect(True) as db:
        target=db.execute('SELECT u.* FROM users u JOIN stores s ON s.code=u.store WHERE u.id=? AND s.tenant_id=? AND u.active=1',(data.user_id,user['tenant_id'])).fetchone()
        store=db.execute('SELECT * FROM stores WHERE code=? AND tenant_id=?',(data.store,user['tenant_id'])).fetchone()
        if not target or not store:fail(404,'人员或门店不属于本租户')
        if target['store']==data.store:fail(422,'本店身份使用账号原权限，无需跨店授权')
        validate_options(db,data.store,data.job,data.stations)
        db.execute('INSERT INTO store_grants(tenant_id,user_id,store,role,job,stations,note,expires_at,granted_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,store) DO UPDATE SET role=excluded.role,job=excluded.job,stations=excluded.stations,note=excluded.note,expires_at=excluded.expires_at,granted_by=excluded.granted_by,created_at=excluded.created_at,revoked_at=NULL',(user['tenant_id'],data.user_id,data.store,data.role,data.job,encode(data.stations),data.note,expiry,user['id'],now()))
        audit(db,user,'cross_store_granted',str(data.user_id)+':'+data.store+':'+data.note)
    return {'ok':True}


@router.post('/api/hq/grants/{gid}/revoke')
def revoke_grant(gid: int,data: Note,user=Depends(owner)):
    with connect(True) as db:
        row=db.execute('SELECT * FROM store_grants WHERE id=? AND tenant_id=?',(gid,user['tenant_id'])).fetchone()
        if not row:fail(404,'授权不存在')
        db.execute('UPDATE store_grants SET revoked_at=? WHERE id=?',(now(),gid))
        audit(db,user,'cross_store_revoked',str(gid)+':'+data.note)
    return {'ok':True}


@router.post('/api/hq/transfers')
def request_transfer(data: TransferIn,user=Depends(owner)):
    with connect(True) as db:
        store=user['home_store']
        if db.execute('SELECT COUNT(*) FROM stores WHERE tenant_id=?',(user['tenant_id'],)).fetchone()[0]!=1:fail(409,'当前仅支持独立单店租户整店迁入，不拆分现有连锁')
        dest=db.execute('SELECT * FROM tenants WHERE code=?',(data.destination_code,)).fetchone()
        if not dest or dest['id']==user['tenant_id']:fail(422,'目标总部租户标识无效')
        if db.execute("SELECT 1 FROM store_transfers WHERE store=? AND state='pending'",(store,)).fetchone():fail(409,'已有待处理迁入申请')
        rid=db.execute('INSERT INTO store_transfers(store,source_tenant,destination_tenant,requested_by,note,created_at) VALUES(?,?,?,?,?,?)',(store,user['tenant_id'],dest['id'],user['id'],data.note,now())).lastrowid
        audit(db,user,'store_transfer_requested',rid)
    return {'id':rid}


@router.post('/api/hq/transfers/{tid}/decision')
def decide_transfer(tid: int,data: TransferDecision,user=Depends(owner)):
    with connect(True) as db:
        row=db.execute('SELECT * FROM store_transfers WHERE id=? AND destination_tenant=?',(tid,user['tenant_id'])).fetchone()
        if not row:fail(404,'迁入申请不存在')
        if row['state']!='pending':fail(409,'申请已处理')
        store=db.execute('SELECT * FROM stores WHERE code=?',(row['store'],)).fetchone()
        requester=db.execute("SELECT * FROM users WHERE id=? AND store=? AND role='admin' AND active=1",(row['requested_by'],row['store'])).fetchone()
        valid=store['tenant_id']==row['source_tenant'] and requester and db.execute('SELECT 1 FROM hq_members WHERE tenant_id=? AND user_id=? AND active=1',(row['source_tenant'],row['requested_by'])).fetchone()
        if not valid or db.execute('SELECT COUNT(*) FROM stores WHERE tenant_id=?',(row['source_tenant'],)).fetchone()[0]!=1:fail(409,'原门店归属、数量或申请人权限已变化，请重新申请')
        if data.accepted:
            db.execute('UPDATE stores SET tenant_id=? WHERE code=?',(user['tenant_id'],row['store']))
            db.execute('UPDATE store_grants SET revoked_at=? WHERE store=? OR user_id IN (SELECT id FROM users WHERE store=?)',(now(),row['store'],row['store']))
            db.execute('UPDATE hq_members SET active=0 WHERE tenant_id=?',(row['source_tenant'],))
            db.execute('DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE store=?)',(row['store'],))
        db.execute('UPDATE store_transfers SET state=?,decision_note=?,decided_by=?,decided_at=? WHERE id=?',('accepted' if data.accepted else 'rejected',data.note,user['id'],now(),tid))
        audit(db,user,'store_transfer_accepted' if data.accepted else 'store_transfer_rejected',tid)
    return {'ok':True,'message':'业务门店编号和历史数据保留；迁入人员须重新登录。'}


@router.post('/api/hq/templates')
def template(data: TemplateIn,user=Depends(owner)):
    from .service import validate_service
    validate_service(data.kind,data.content)
    if data.kind=='recipe' and (not data.content.ingredients or not data.content.technique or not data.content.glass):fail(422,'配方模板须完整填写原料、技法与杯型')
    with connect(True) as db:
        root=data.template_id;version=1
        if root:
            previous=template_row(db,root,user);root=previous['template_id'] or previous['id']
            latest=db.execute('SELECT * FROM hq_templates WHERE template_id=? ORDER BY version DESC LIMIT 1',(root,)).fetchone()
            if previous['id']!=latest['id'] or latest['state']!='published':fail(409,'须从最新已发布模板创建新版')
            if latest['title']!=data.title or latest['kind']!=data.kind:fail(422,'同系列模板须保留标题和类型')
            version=latest['version']+1
        rid=db.execute('INSERT INTO hq_templates(tenant_id,template_id,version,title,kind,content,source,change_note,risk,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(user['tenant_id'],root,version,data.title,data.kind,encode(data.content.model_dump()),data.source,data.change_note,data.risk or data.kind=='complaint_card',user['id'],now())).lastrowid
        if not root:db.execute('UPDATE hq_templates SET template_id=id WHERE id=?',(rid,))
        audit(db,user,'hq_template_drafted',rid)
    return {'id':rid,'version':version}


@router.post('/api/hq/templates/{tid}/submit')
def submit(tid: int,user=Depends(owner)):
    with connect(True) as db:
        row=template_row(db,tid,user)
        if row['state']!='draft':fail(409,'仅能提交模板草稿')
        db.execute("UPDATE hq_templates SET state='review' WHERE id=?",(tid,))
        audit(db,user,'hq_template_submitted',tid)
    return {'ok':True}


@router.post('/api/hq/templates/{tid}/approve')
def approve(tid: int,data: Approve,user=Depends(owner)):
    with connect(True) as db:
        row=template_row(db,tid,user)
        if row['state']!='review':fail(409,'须先提交审核')
        if (row['risk'] or row['kind']=='recipe') and not data.risk_confirmed:fail(422,'高风险／配方模板须明确确认资料')
        db.execute("UPDATE hq_templates SET state='published',approved_by=?,approved_at=? WHERE id=?",(user['id'],now(),tid))
        audit(db,user,'hq_template_approved',tid)
    return {'ok':True}


@router.post('/api/hq/templates/{tid}/release')
def release(tid: int,data: Release,user=Depends(owner)):
    with connect(True) as db:
        row=template_row(db,tid,user)
        if row['state']!='published':fail(409,'仅能分发已批准的模板版本')
        payload={'template_version_id':tid,**data.model_dump()}
        cached=replay(db,user,'hq_release',data.idempotency_key,payload)
        if cached:return cached
        if len(set(data.stores))!=len(data.stores):fail(422,'目标门店不能重复')
        ids=[]
        for store in data.stores:
            if not db.execute('SELECT 1 FROM stores WHERE code=? AND tenant_id=?',(store,user['tenant_id'])).fetchone():fail(404,'目标门店不属于本租户')
            existing=db.execute('SELECT id FROM hq_deliveries WHERE template_version_id=? AND store=?',(tid,store)).fetchone()
            rid=existing['id'] if existing else db.execute('INSERT INTO hq_deliveries(tenant_id,template_version_id,store,sent_by,created_at) VALUES(?,?,?,?,?)',(user['tenant_id'],tid,store,user['id'],now())).lastrowid
            ids.append(rid)
        result={'ids':ids}
        remember(db,user,'hq_release',data.idempotency_key,payload,result)
        audit(db,user,'hq_template_released',encode(ids))
        return result


@router.get('/api/hq/deliveries/{did}')
def delivery(did: int,user=Depends(manager)):
    with connect() as db:
        row=delivery_row(db,did,user);tpl=template_row(db,row['template_version_id'],user)
        adoption=db.execute('SELECT d.* FROM hq_adoptions a JOIN documents d ON d.id=a.document_id WHERE a.store=? AND a.template_id=?',(row['store'],tpl['template_id'])).fetchone()
        return {**dict(row),'rollout':rollout(db,row),'template':{**dict(tpl),'content':json.loads(tpl['content'])},'adoption':dict(adoption) if adoption else None}


@router.post('/api/hq/deliveries/{did}/sign')
def sign(did: int,data: Sign,user=Depends(manager)):
    with connect(True) as db:
        row=delivery_row(db,did,user)
        if row['store']!=user['store']:fail(403,'请切换到已获授权的接收门店后签收')
        if row['state']!='pending':
            if row['state']=='accepted' and data.accepted and row['sign_hash']==digest(data.model_dump()):return {'id':row['local_revision_id'],'already_signed':True}
            fail(409,'该发布已签收或驳回')
        if not data.accepted:
            db.execute("UPDATE hq_deliveries SET state='rejected',note=?,signed_by=?,signed_at=?,sign_hash=? WHERE id=?",(data.note,user['id'],now(),digest(data.model_dump()),did))
            audit(db,user,'hq_delivery_rejected',did)
            return {'rejected':True}
        tpl=template_row(db,row['template_version_id'],user)
        if data.local_content and len(data.difference_note.strip())<5:fail(422,'门店修改模板内容必须记录至少5字的差异原因')
        if not data.jobs or not data.stations:fail(422,'签收须明确本店岗位和吧台范围')
        from .maintenance import validate_options
        for job in data.jobs:
            validate_options(db,user['store'],job,data.stations)
        content=data.local_content or Content.model_validate(json.loads(tpl['content']))
        adoption=db.execute('SELECT * FROM hq_adoptions WHERE store=? AND template_id=?',(user['store'],tpl['template_id'])).fetchone()
        doc=db.execute('SELECT * FROM documents WHERE id=?',(adoption['document_id'],)).fetchone() if adoption else None
        if adoption:
            previous_delivery=db.execute('SELECT t.version FROM hq_deliveries d JOIN hq_templates t ON t.id=d.template_version_id WHERE d.id=?',(adoption['last_delivery_id'],)).fetchone()
            if previous_delivery['version']>=tpl['version']:fail(409,'门店已采用同版或更新模板，不得回退')
        draft=Draft(document_id=doc['id'] if doc else None,title=tpl['title'],kind=tpl['kind'],jobs=data.jobs,stations=data.stations,aliases=json.loads(doc['aliases']) if doc else [],risk=bool(tpl['risk']),source=tpl['source'][:400]+' / HQ '+str(tpl['template_id'])+' v'+str(tpl['version']),content=content,change_reason='总部签收：'+data.note+'；门店差异：'+(data.difference_note or '无'))
        result=create_draft_record(db,draft,user)
        db.execute("UPDATE hq_deliveries SET state='accepted',note=?,local_revision_id=?,difference_note=?,signed_by=?,signed_at=?,sign_hash=? WHERE id=?",(data.note,result['id'],data.difference_note,user['id'],now(),digest(data.model_dump()),did))
        db.execute('INSERT INTO hq_adoptions VALUES(?,?,?,?,?) ON CONFLICT(store,template_id) DO UPDATE SET last_delivery_id=excluded.last_delivery_id',(user['tenant_id'],user['store'],tpl['template_id'],result['document_id'],did))
        audit(db,user,'hq_delivery_adopted_draft',did)
        return result

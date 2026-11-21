"""Fixed daily checklists, acknowledged handoffs, incident closure and manager queues."""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator, ValidationInfo
from .db import audit, connect, now
from .main import Input, current, fail, identity, manager

router = APIRouter()
TEMPLATES = {
    'opening': {'title':'开吧清单','items':['检查营业区域与消防通道','检查设备运行与制冰状态','核对原料标签、效期与过敏原','确认器具清洁与岗位准备']},
    'closing': {'title':'收吧清单','items':['清洁消毒器具及操作台','检查原料密封、标签与储存','按门店标准确认设备和水电状态','记录遗留问题并完成交接']},
    'handoff': {'title':'交接记录','items':['交代当前营业与岗位状态','核对原料及待补充事项','交代设备异常和未关闭事项','写明下一班待办与注意事项']},
}


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


class RunIn(Input):
    kind: Literal['opening','closing','handoff']
    station: str = Field(min_length=1,max_length=80)
    business_date: str
    owner_id: int
    recipient_id: int | None = None

    @field_validator('business_date')
    @classmethod
    def valid_date(cls,value):
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('日期须为 YYYY-MM-DD')
        return value


class Version(Input):
    version: int = Field(ge=1)


class ItemIn(Version):
    state: Literal['done','issue']
    note: str = Field(min_length=5,max_length=1000)
    evidence: str = Field(min_length=5,max_length=2000)

    @field_validator('note','evidence')
    @classmethod
    def nonblank(cls,value):
        if len(value.strip()) < 5:
            raise ValueError('请填写至少5字的记录和证据')
        return value.strip()


class CloseRun(Version):
    note: str = Field(min_length=5,max_length=1000)


class IncidentIn(Input):
    station: str = Field(min_length=1,max_length=80)
    title: str = Field(min_length=2,max_length=120)
    description: str = Field(min_length=5,max_length=2000)
    evidence: str = Field(min_length=5,max_length=2000)
    owner_id: int

    @field_validator('title','description','evidence')
    @classmethod
    def nonblank(cls,value,info: ValidationInfo):
        if len(value.strip()) < (2 if info.field_name == 'title' else 5):
            raise ValueError('请填写有效内容')
        return value.strip()


class ResolveIncident(Version):
    resolution: str = Field(min_length=5,max_length=2000)
    evidence: str = Field(min_length=5,max_length=2000)

    @field_validator('resolution','evidence')
    @classmethod
    def nonblank(cls,value):
        if len(value.strip()) < 5:
            raise ValueError('处理说明和关闭证据至少5字')
        return value.strip()


class AssignOwner(Version):
    owner_id: int


class AssignRun(AssignOwner):
    recipient_id: int | None = None


def station_allowed(user,station):
    if station not in json.loads(user['stations']):
        fail(403,'无权访问该吧台')


def person(db,uid,user,station):
    from .tenancy import scoped_person
    row = scoped_person(db,uid,user['store'])
    if not row or station not in json.loads(row['stations']):
        fail(422,'负责人或接班人须是该吧台的有效员工')
    return row


def record(db,table,rid,user):
    row = db.execute('SELECT * FROM '+table+' WHERE id=? AND store=?',(rid,user['store'])).fetchone()
    if not row:
        fail(404,'记录不存在')
    station_allowed(user,row['station'])
    return row


def check_version(row,version):
    if row['version'] != version:
        fail(409,'记录已被更新，请重新打开后操作')


def require_owner(row,user):
    if user['role'] == 'staff' and row['owner_id'] != user['id']:
        fail(403,'请由负责人处理')


def named(db,row):
    item = dict(row)
    for key in ('owner_id','recipient_id','created_by','closed_by','resolved_by'):
        if item.get(key):
            member = db.execute('SELECT name,active FROM users WHERE id=?',(item[key],)).fetchone()
            item[key.replace('_id','_name') if key.endswith('_id') else key+'_name'] = member['name'] if member else '未知'
            if key == 'owner_id':
                item['owner_active'] = bool(member and member['active'])
    return item


@router.get('/api/flow/templates')
def templates(user=Depends(identity)):
    return TEMPLATES


@router.get('/api/flow/people')
def people(station: str, user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        from .tenancy import scoped_people
        return [{'id':r['id'],'name':r['name']} for r in scoped_people(db,user['store']) if station in json.loads(r['stations'])]


@router.get('/api/flow/runs')
def runs(station: str, user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        rows = db.execute("SELECT * FROM flow_runs WHERE store=? AND station=? ORDER BY CASE WHEN state='closed' THEN 1 ELSE 0 END,business_date DESC,id DESC LIMIT 200",(user['store'],station)).fetchall()
        return [{**named(db,r),'done':db.execute("SELECT COUNT(*) FROM flow_items WHERE run_id=? AND state<>'pending'",(r['id'],)).fetchone()[0],'total':db.execute('SELECT COUNT(*) FROM flow_items WHERE run_id=?',(r['id'],)).fetchone()[0]} for r in rows]


@router.post('/api/flow/runs')
def start_run(data: RunIn, user=Depends(identity)):
    station_allowed(user,data.station)
    if user['role'] == 'staff' and data.owner_id != user['id']:
        fail(403,'员工只能创建自己负责的清单')
    if data.business_date != today():
        fail(422,'只能创建北京时间当天的清单，历史记录可查询')
    with connect(True) as db:
        person(db,data.owner_id,user,data.station)
        if data.kind == 'handoff':
            if not data.recipient_id or data.recipient_id == data.owner_id:
                fail(422,'交接须选择另一位有效接班人')
            person(db,data.recipient_id,user,data.station)
        elif data.recipient_id is not None:
            fail(422,'开收吧清单无需接班人')
        existing = db.execute('SELECT id FROM flow_runs WHERE store=? AND station=? AND kind=? AND business_date=?',(user['store'],data.station,data.kind,data.business_date)).fetchone()
        if existing:
            fail(409,'当天已有此类清单，请打开已有记录')
        rid = db.execute('INSERT INTO flow_runs(store,station,kind,business_date,owner_id,recipient_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',(user['store'],data.station,data.kind,data.business_date,data.owner_id,data.recipient_id,user['id'],now())).lastrowid
        db.executemany('INSERT INTO flow_items(run_id,position,label) VALUES(?,?,?)',[(rid,i,label) for i,label in enumerate(TEMPLATES[data.kind]['items'])])
        audit(db,user,'flow_started','run:'+str(rid))
    return {'id':rid}


@router.get('/api/flow/runs/{rid}')
def run_detail(rid: int, user=Depends(identity)):
    with connect() as db:
        row = record(db,'flow_runs',rid,user)
        return {**named(db,row),'items':[dict(r) for r in db.execute('SELECT i.*,x.id incident_id,x.state incident_state FROM flow_items i LEFT JOIN flow_incidents x ON x.item_id=i.id WHERE run_id=? ORDER BY position',(rid,))]}


@router.post('/api/flow/runs/{rid}/items/{iid}')
def update_item(rid: int, iid: int, data: ItemIn, user=Depends(identity)):
    with connect(True) as db:
        run = record(db,'flow_runs',rid,user)
        require_owner(run,user)
        check_version(run,data.version)
        if run['state'] != 'open':
            fail(409,'已关闭清单不可修改')
        person(db,run['owner_id'],user,run['station'])
        item = db.execute('SELECT * FROM flow_items WHERE id=? AND run_id=?',(iid,rid)).fetchone()
        if not item:
            fail(404,'检查项不存在')
        if item['state'] != 'pending':
            fail(409,'检查项已提交，原始证据予以保留；新异常请另行报修')
        db.execute('UPDATE flow_items SET state=?,note=?,evidence=?,updated_by=?,updated_at=? WHERE id=?',(data.state,data.note,data.evidence,user['id'],now(),iid))
        if data.state == 'issue':
            db.execute("INSERT INTO flow_incidents(store,station,kind,title,description,report_evidence,owner_id,item_id,created_by,created_at) VALUES(?,?,'exception',?,?,?,?,?,?,?)",(user['store'],run['station'],item['label'],data.note,data.evidence,run['owner_id'],iid,user['id'],now()))
        db.execute('UPDATE flow_runs SET version=version+1 WHERE id=?',(rid,))
        audit(db,user,'flow_item_'+data.state,'run:'+str(rid))
    return {'ok':True}


@router.post('/api/flow/runs/{rid}/owner')
def assign_run(rid: int, data: AssignRun, user=Depends(manager)):
    with connect(True) as db:
        row = record(db,'flow_runs',rid,user)
        check_version(row,data.version)
        if row['state'] != 'open':
            fail(409,'已关闭记录不可改派')
        person(db,data.owner_id,user,row['station'])
        recipient = data.recipient_id or row['recipient_id']
        if row['kind'] == 'handoff':
            if not recipient or recipient == data.owner_id:
                fail(422,'交班人与接班人须不同')
            person(db,recipient,user,row['station'])
        elif data.recipient_id is not None:
            fail(422,'开收吧清单无需接班人')
        db.execute('UPDATE flow_runs SET owner_id=?,recipient_id=?,version=version+1 WHERE id=?',(data.owner_id,recipient,rid))
        audit(db,user,'flow_owner_changed','run:'+str(rid))
    return {'ok':True}


@router.post('/api/flow/runs/{rid}/close')
def close_run(rid: int, data: CloseRun, user=Depends(identity)):
    if len(data.note.strip()) < 5:
        fail(422,'请填写至少5字的关闭记录')
    with connect(True) as db:
        row = record(db,'flow_runs',rid,user)
        check_version(row,data.version)
        if row['state'] != 'open':
            fail(409,'记录已关闭')
        person(db,row['owner_id'],user,row['station'])
        if row['kind'] == 'handoff':
            if user['id'] != row['recipient_id']:
                fail(403,'须由指定接班人确认交接')
        else:
            require_owner(row,user)
        if db.execute("SELECT 1 FROM flow_items WHERE run_id=? AND state='pending'",(rid,)).fetchone():
            fail(409,'请逐项填写检查结果与证据')
        db.execute("UPDATE flow_runs SET state='closed',note=?,closed_at=?,closed_by=?,version=version+1 WHERE id=?",(data.note,now(),user['id'],rid))
        audit(db,user,'handoff_acknowledged' if row['kind']=='handoff' else 'flow_closed','run:'+str(rid))
    return {'ok':True,'message':'清单已关闭，异常事项继续在异常台账中跟进。'}


@router.get('/api/flow/incidents')
def incidents(station: str, user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        return [named(db,r) for r in db.execute("SELECT * FROM flow_incidents WHERE store=? AND station=? ORDER BY CASE WHEN state='closed' THEN 1 ELSE 0 END,id DESC LIMIT 200",(user['store'],station))]


@router.get('/api/flow/incidents/{rid}')
def incident_detail(rid: int, user=Depends(identity)):
    with connect() as db:
        return named(db,record(db,'flow_incidents',rid,user))


@router.post('/api/flow/incidents')
def report(data: IncidentIn, user=Depends(identity)):
    station_allowed(user,data.station)
    if user['role']=='staff' and data.owner_id != user['id']:
        fail(403,'请先提交自己负责的报修，由主管改派')
    with connect(True) as db:
        person(db,data.owner_id,user,data.station)
        rid=db.execute("INSERT INTO flow_incidents(store,station,kind,title,description,report_evidence,owner_id,created_by,created_at) VALUES(?,?,'repair',?,?,?,?,?,?)",(user['store'],data.station,data.title,data.description,data.evidence,data.owner_id,user['id'],now())).lastrowid
        audit(db,user,'repair_reported','incident:'+str(rid))
    return {'id':rid}


@router.post('/api/flow/incidents/{rid}/owner')
def assign_incident(rid: int, data: AssignOwner, user=Depends(manager)):
    with connect(True) as db:
        row=record(db,'flow_incidents',rid,user)
        check_version(row,data.version)
        if row['state']=='closed':
            fail(409,'已关闭记录不可改派')
        person(db,data.owner_id,user,row['station'])
        db.execute('UPDATE flow_incidents SET owner_id=?,version=version+1 WHERE id=?',(data.owner_id,rid))
        audit(db,user,'incident_owner_changed','incident:'+str(rid))
    return {'ok':True}


@router.post('/api/flow/incidents/{rid}/resolve')
def resolve_incident(rid: int, data: ResolveIncident, user=Depends(identity)):
    with connect(True) as db:
        row=record(db,'flow_incidents',rid,user)
        require_owner(row,user)
        check_version(row,data.version)
        if row['state'] != 'open':
            fail(409,'该异常已提交处理结果')
        db.execute("UPDATE flow_incidents SET state='resolved',resolution=?,close_evidence=?,resolved_by=?,resolved_at=?,version=version+1 WHERE id=?",(data.resolution,data.evidence,user['id'],now(),rid))
        audit(db,user,'incident_resolved','incident:'+str(rid))
    return {'ok':True}


@router.post('/api/flow/incidents/{rid}/close')
def close_incident(rid: int, data: Version, user=Depends(manager)):
    with connect(True) as db:
        row=record(db,'flow_incidents',rid,user)
        check_version(row,data.version)
        if row['state'] != 'resolved' or not row['resolution'] or not row['close_evidence']:
            fail(409,'请负责人先提交处理结果及关闭证据')
        db.execute("UPDATE flow_incidents SET state='closed',closed_by=?,closed_at=?,version=version+1 WHERE id=?",(user['id'],now(),rid))
        audit(db,user,'incident_closed','incident:'+str(rid))
    return {'ok':True}


@router.get('/api/manage/command')
def command(user=Depends(manager)):
    from .academy import assignment_status
    day=today()
    with connect() as db:
        allowed=set(json.loads(user['stations']))
        run_rows=[r for r in db.execute('SELECT * FROM flow_runs WHERE store=? ORDER BY business_date,id',(user['store'],)) if r['station'] in allowed]
        run_tasks=[named(db,r) for r in run_rows if r['state']=='open']
        missing=[{'station':station,'kind':kind,'title':TEMPLATES[kind]['title']} for station in sorted(allowed) for kind in ('opening','closing','handoff') if not any(r['station']==station and r['kind']==kind and r['business_date']==day for r in run_rows)]
        issue_tasks=[named(db,r) for r in db.execute("SELECT * FROM flow_incidents WHERE store=? AND state<>'closed' ORDER BY id",(user['store'],)) if r['station'] in allowed]
        training=[]
        for row in db.execute('SELECT a.*,m.title,m.pass_score,u.name FROM assignments a JOIN modules m ON m.id=a.module_id JOIN users u ON u.id=a.user_id WHERE m.store=? AND u.active=1 AND a.superseded_by IS NULL',(user['store'],)):
            from .tenancy import scoped_person
            target=scoped_person(db,row['user_id'],user['store'])
            if not target:continue
            if not allowed.intersection(json.loads(target['stations'])):
                continue
            item=assignment_status(db,row,target)
            if item['status']!='completed':
                training.append(item)
        standards=[]
        for doc in db.execute('SELECT * FROM documents WHERE store=?',(user['store'],)):
            if not allowed.intersection(json.loads(doc['stations'])):
                continue
            active=current(db,doc['id'])
            for rev in db.execute('SELECT * FROM revisions WHERE document_id=? AND approved_at IS NOT NULL ORDER BY version DESC',(doc['id'],)):
                if rev['version']>1 or rev['effective_at']>now():
                    standards.append({'document_id':doc['id'],'title':doc['title'],'revision_id':rev['id'],'version':rev['version'],'change_note':rev['change_reason'],'effective_at':rev['effective_at'],'state':'current' if active and active['id']==rev['id'] else 'scheduled' if rev['state']=='published' and rev['effective_at']>now() else 'historical'})
        feedback=[dict(r) for r in db.execute("SELECT f.id,f.description,q.question,q.station FROM feedback f JOIN queries q ON q.id=f.query_id WHERE q.store=? AND f.state='open' AND f.kind<>'helpful'",(user['store'],)) if r['station'] in allowed]
        pending=sum(bool(allowed.intersection(json.loads(r['stations']))) for r in db.execute("SELECT d.stations FROM revisions r JOIN documents d ON d.id=r.document_id WHERE d.store=? AND r.state='review'",(user['store'],)))
        todos=[dict(r) for r in db.execute("SELECT t.*,u.name owner_name FROM work_tasks t JOIN users u ON u.id=t.owner_id WHERE t.store=? AND t.state='open' ORDER BY due_at,id",(user['store'],)) if r['station'] in allowed]
    return {'tasks':todos,'business_date':day,'generated_at':now(),'runs':run_tasks,'missing_runs':missing,'incidents':issue_tasks,'training':training,'standard_changes':standards,'feedback':feedback,'pending_reviews':pending,'counts':{'runs':len(run_tasks),'missing_runs':len(missing),'incidents':len(issue_tasks),'training':len(training),'overdue_training':sum(t['overdue'] for t in training),'standard_changes':sum(s['state'] in ('current','scheduled') for s in standards)},'definition':'按北京时间营业日展示已授权吧台的业务记录。未创建清单单独提示；未关闭事项包含历史遗留；课程旧版保留证据但不算当前资格。无客流预测或虚构经营数据。'}

"""Audited, scoped work items shared by humans and the launch planner."""
from fastapi import APIRouter,Depends
from pydantic import Field
from .db import audit,connect,now
from .main import identity,manager,fail,normalized_date
from .inventory import CleanInput,own_record
from .operations import station_allowed,person
from .business import replay,remember

router=APIRouter()


class TaskIn(CleanInput):
    station: str
    title: str = Field(min_length=2,max_length=120)
    description: str = Field(min_length=5,max_length=3000)
    owner_id: int
    due_at: str
    idempotency_key: str = Field(min_length=8,max_length=100)


class Close(CleanInput):
    version: int = Field(ge=1)
    evidence: str = Field(min_length=5,max_length=2000)


def add_task(db,user,station,title,description,owner_id,due_at,source_kind,source_id):
    station_allowed(user,station)
    person(db,owner_id,user,station)
    due=normalized_date(due_at)
    if due<=now():fail(422,'待办截止时间必须晚于当前时间')
    old=db.execute('SELECT id FROM work_tasks WHERE store=? AND source_kind=? AND source_id=?',(user['store'],source_kind,source_id)).fetchone()
    if old:return old['id']
    rid=db.execute('INSERT INTO work_tasks(store,station,title,description,owner_id,due_at,created_by,created_at,source_kind,source_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(user['store'],station,title,description,owner_id,due,user['id'],now(),source_kind,source_id)).lastrowid
    audit(db,user,'work_task_created',rid)
    return rid


@router.post('/api/tasks')
def create(data: TaskIn,user=Depends(manager)):
    with connect(True) as db:
        payload=data.model_dump();cached=replay(db,user,'manual_task',data.idempotency_key,payload)
        if cached:return cached
        rid=add_task(db,user,data.station,data.title,data.description,data.owner_id,data.due_at,'manual',str(user['id'])+':'+data.idempotency_key)
        result={'id':rid};remember(db,user,'manual_task',data.idempotency_key,payload,result)
        return result


@router.get('/api/tasks')
def tasks(station: str,user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT t.*,u.name owner_name FROM work_tasks t JOIN users u ON u.id=t.owner_id WHERE t.store=? AND t.station=?'+(' AND t.owner_id=?' if user['role']=='staff' else '')+' ORDER BY t.state DESC,t.due_at,t.id',(user['store'],station,user['id']) if user['role']=='staff' else (user['store'],station))]


@router.post('/api/tasks/{tid}/close')
def close(tid: int,data: Close,user=Depends(identity)):
    with connect(True) as db:
        row=own_record(db,'work_tasks',tid,user,True)
        if user['role']=='staff' and row['owner_id']!=user['id']:fail(403,'请由负责人提交完成证据')
        if row['version']!=data.version or row['state']!='open':fail(409,'待办已更新或关闭，请刷新')
        db.execute("UPDATE work_tasks SET state='closed',evidence=?,closed_by=?,closed_at=?,version=version+1 WHERE id=?",(data.evidence,user['id'],now(),tid))
        audit(db,user,'work_task_closed',tid)
    return {'ok':True}

"""A fixed launch planner generates drafts; one allowlisted tool writes approved todos."""
import json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from .db import audit,connect,encode,now
from .main import manager,fail,get_revision,scope,normalized_date,current
from .inventory import CleanInput,own_record
from .operations import station_allowed,person
from .business import replay,remember
from .report_math import digest
from .tasks import add_task

router=APIRouter()
TOOL='create_launch_todos'
TASKS=[('standard','核对并审核发布新品配方','核对实际原料、用量、标签与资料来源；通过原知识审批流程发布，记录有效版本。'),('inventory','核对SKU、单位及历史成本','逐项完成配方SKU映射、包装换算及有来源的单位成本；缺项不得按0处理。'),('count','确认首批原料与可信盘点','核对上新所需实物原料，提交全SKU盘点并由另一位主管复核，保留来源证据。'),('service','审批新品介绍与客诉升级卡','准备真实、可核实的服务话术和客诉升级条件，提交审核；不得自行承诺过敏原安全。'),('training','完成员工理论与主管实操','把批准版本纳入Academy，完成学习、测验及主管实操验收，记录员工技能证据。'),('flow','确认设备与当班准备','通过固定开吧清单核对设备、器具和岗位准备，异常应有负责人并独立跟进。'),('launch','店长确认上新条件','人工核对配方、库存、服务、培训与异常记录后决定是否上新；待办完成不自动代表发布许可。')]


class PlanIn(CleanInput):
    title: str = Field(min_length=2,max_length=120)
    recipe_revision_id: int
    station: str
    launch_at: str
    owner_id: int
    idempotency_key: str = Field(min_length=8,max_length=100)


class TaskEdit(CleanInput):
    key: str
    owner_id: int
    due_at: str


class Edit(CleanInput):
    version: int = Field(ge=1)
    tasks: list[TaskEdit] = Field(min_length=7,max_length=7)
    note: str = Field(min_length=5,max_length=1000)


class Decision(CleanInput):
    version: int = Field(ge=1)
    approved: bool
    note: str = Field(min_length=5,max_length=1000)


class Version(CleanInput):
    version: int = Field(ge=1)


class Execute(Version):
    idempotency_key: str = Field(min_length=8,max_length=100)


def plan_row(db,pid,user):
    row=own_record(db,'agent_plans',pid,user,True)
    return row


def recipe_snapshot(doc,rev):
    return {'document_id':doc['id'],'title':doc['title'],'revision_id':rev['id'],'version':rev['version'],'state':rev['state'],'content':json.loads(rev['content']),'source':rev['source'],'effective_at':rev['effective_at'],'expires_at':rev['expires_at']}


def valid_recipe(db,rid,user,station):
    doc,rev=get_revision(db,rid,user)
    if doc['kind']!='recipe' or not scope(doc,user,station):fail(403,'计划配方不在当前岗位或吧台权限内')
    if rev['state']=='retired' or rev['expires_at'] and rev['expires_at']<=now():fail(409,'配方已停用或过期')
    if rev['state']=='published':
        active=current(db,doc['id'])
        if not active or active['id']!=rev['id']:fail(409,'请选择当前有效配方或待审核草稿')
    return doc,rev


def source_guard(db,row,user):
    doc,rev=valid_recipe(db,row['recipe_revision_id'],user,row['station'])
    if digest(recipe_snapshot(doc,rev))!=json.loads(row['inputs'])['recipe_hash']:
        fail(409,'配方内容、状态或版本依据已变化，请重新生成并审批计划')


def check_tasks(db,user,station,tasks,launch):
    if {t['key'] for t in tasks}!={t[0] for t in TASKS} or len(tasks)!=7:fail(422,'只能编辑固定七项上市准备任务的负责人和截止时间')
    for task in tasks:
        person(db,task['owner_id'],user,station)
        due=normalized_date(task['due_at'])
        if due<=now() or due>launch:fail(422,'任务截止时间须晚于现在且不晚于上市时间')
        task['due_at']=due


def tool_event(db,user,pid,payload,outcome,detail):
    db.execute('INSERT INTO agent_tool_events(store,actor,plan_id,tool_name,request_hash,outcome,detail,created_at) VALUES(?,?,?,?,?,?,?,?)',(user['store'],user['id'],pid,TOOL,digest(payload),outcome,detail,now()))


@router.post('/api/agents/plans')
def generate(data: PlanIn,user=Depends(manager)):
    station_allowed(user,data.station);launch=normalized_date(data.launch_at)
    if launch<=now():fail(422,'上市时间须晚于现在')
    with connect(True) as db:
        payload=data.model_dump();cached=replay(db,user,'launch_plan',data.idempotency_key,payload)
        if cached:return cached
        doc,rev=valid_recipe(db,data.recipe_revision_id,user,data.station)
        tasks=[{'key':key,'title':title,'description':description,'owner_id':data.owner_id,'due_at':launch} for key,title,description in TASKS]
        check_tasks(db,user,data.station,tasks,launch)
        recipe=recipe_snapshot(doc,rev)
        mapping=db.execute('SELECT id FROM inv_recipe_maps WHERE revision_id=? AND store=?',(rev['id'],user['store'])).fetchone()
        count=db.execute("SELECT id,observed_at FROM inv_counts WHERE store=? AND station=? AND state='approved' ORDER BY observed_at DESC LIMIT 1",(user['store'],data.station)).fetchone()
        inputs={'planner':'fixed_launch_readiness_v1','recipe':recipe,'recipe_hash':digest(recipe),'recipe_mapping_id':mapping['id'] if mapping else None,'latest_approved_count':dict(count) if count else None,'generated_at':now(),'limitations':['规则式计划草稿，不调用大模型。','库存、成本、服务与培训须由负责人逐项核对；生成任务不代表上新条件已满足。']}
        rid=db.execute('INSERT INTO agent_plans(store,station,title,recipe_revision_id,launch_at,inputs,tasks,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(user['store'],data.station,data.title,rev['id'],launch,encode(inputs),encode(tasks),user['id'],now())).lastrowid
        audit(db,user,'launch_plan_drafted',rid)
        result={'id':rid,'state':'draft','version':1};remember(db,user,'launch_plan',data.idempotency_key,payload,result)
        return result


@router.get('/api/agents/plans')
def plans(station: str,user=Depends(manager)):
    station_allowed(user,station)
    with connect() as db:
        return [{**dict(r),'inputs':json.loads(r['inputs']),'tasks':json.loads(r['tasks'])} for r in db.execute('SELECT * FROM agent_plans WHERE store=? AND station=? ORDER BY id DESC LIMIT 200',(user['store'],station))]


@router.get('/api/agents/plans/{pid}')
def detail(pid: int,user=Depends(manager)):
    with connect() as db:
        row=plan_row(db,pid,user)
        ids=[r[0] for r in db.execute("SELECT id FROM work_tasks WHERE store=? AND source_kind='launch_plan' AND source_id LIKE ? ORDER BY id",(user['store'],str(pid)+':%'))]
        return {**dict(row),'inputs':json.loads(row['inputs']),'tasks':json.loads(row['tasks']),'task_ids':ids}


@router.post('/api/agents/plans/{pid}/edit')
def edit(pid: int,data: Edit,user=Depends(manager)):
    with connect(True) as db:
        row=plan_row(db,pid,user)
        if row['state']!='draft' or row['version']!=data.version:fail(409,'只能编辑当前版本计划草稿')
        old=json.loads(row['tasks']);edits={t.key:t for t in data.tasks}
        if len(edits)!=7 or set(edits)!={t['key'] for t in old}:fail(422,'任务不能缺失或重复')
        for task in old:task.update(owner_id=edits[task['key']].owner_id,due_at=edits[task['key']].due_at)
        check_tasks(db,user,row['station'],old,row['launch_at'])
        db.execute('UPDATE agent_plans SET tasks=?,note=?,version=version+1 WHERE id=?',(encode(old),data.note,pid))
        audit(db,user,'launch_plan_edited',pid)
    return {'version':data.version+1}


@router.post('/api/agents/plans/{pid}/submit')
def submit(pid: int,data: Version,user=Depends(manager)):
    with connect(True) as db:
        row=plan_row(db,pid,user)
        if row['state']!='draft' or row['version']!=data.version:fail(409,'计划草稿已变化')
        source_guard(db,row,user)
        check_tasks(db,user,row['station'],json.loads(row['tasks']),row['launch_at'])
        db.execute("UPDATE agent_plans SET state='review',version=version+1 WHERE id=?",(pid,))
        audit(db,user,'launch_plan_submitted',pid)
    return {'version':data.version+1}


@router.post('/api/agents/plans/{pid}/decision')
def decide(pid: int,data: Decision,user=Depends(manager)):
    with connect(True) as db:
        row=plan_row(db,pid,user)
        if row['state']!='review' or row['version']!=data.version:fail(409,'计划不在此待审版本')
        if data.approved:
            source_guard(db,row,user)
            check_tasks(db,user,row['station'],json.loads(row['tasks']),row['launch_at'])
        db.execute('UPDATE agent_plans SET state=?,approved_by=?,approval_note=?,approved_at=?,version=version+1 WHERE id=?',('approved' if data.approved else 'draft',user['id'] if data.approved else None,data.note,now() if data.approved else None,pid))
        audit(db,user,'launch_plan_approved' if data.approved else 'launch_plan_returned',pid)
    return {'version':data.version+1}


@router.post('/api/agents/plans/{pid}/execute')
def execute(pid: int,data: Execute,user=Depends(manager)):
    payload={'plan_id':pid,**data.model_dump()};verified=None
    try:
        with connect(True) as db:
            row=plan_row(db,pid,user);verified=pid
            cached=replay(db,user,TOOL,data.idempotency_key,payload)
            if cached:
                tool_event(db,user,pid,payload,'replayed','相同请求返回既有任务，不重复创建')
                return cached
            if row['state']=='executed':
                ids=[r[0] for r in db.execute("SELECT id FROM work_tasks WHERE store=? AND source_kind='launch_plan' AND source_id LIKE ? ORDER BY id",(user['store'],str(pid)+':%'))]
                result={'id':pid,'task_ids':ids,'already_executed':True}
                remember(db,user,TOOL,data.idempotency_key,payload,result);tool_event(db,user,pid,payload,'replayed','计划已执行，返回既有任务')
                return result
            if row['state']!='approved' or not row['approved_by'] or row['version']!=data.version:fail(409,'须先人工批准当前计划版本')
            source_guard(db,row,user)
            tasks=json.loads(row['tasks']);check_tasks(db,user,row['station'],tasks,row['launch_at'])
            ids=[add_task(db,user,row['station'],t['title'],t['description'],t['owner_id'],t['due_at'],'launch_plan',str(pid)+':'+t['key']) for t in tasks]
            db.execute("UPDATE agent_plans SET state='executed',executed_at=?,version=version+1 WHERE id=?",(now(),pid))
            result={'id':pid,'task_ids':ids}
            remember(db,user,TOOL,data.idempotency_key,payload,result)
            tool_event(db,user,pid,payload,'succeeded','仅创建七项待办；没有发布知识、调整库存或改变培训资格')
            audit(db,user,'launch_plan_executed',pid)
            return result
    except HTTPException as exc:
        with connect(True) as db:tool_event(db,user,verified,payload,'blocked',str(exc.detail))
        raise


@router.get('/api/agents/tool-audit')
def events(user=Depends(manager)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM agent_tool_events WHERE store=? ORDER BY id DESC LIMIT 200',(user['store'],))]

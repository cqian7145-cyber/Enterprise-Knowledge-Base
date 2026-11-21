import json
import sqlite3
from datetime import datetime,timedelta,timezone
from test_baros import clients,create,publish,PASSWORD
from app.db import connect,initialize


def post(client,url,data,**kwargs):
    r=client.post(url,json=data,**kwargs)
    assert r.status_code==200,r.text
    return r.json()


def future(days=3):return (datetime.now(timezone.utc)+timedelta(days=days)).isoformat()


def branch(admin,code='branch2'):
    post(admin,'/api/hq/stores',{'code':code,'name':'第二门店测试','verification_note':'仅为隔离测试门店，不是真实门店验收','job':'bartender','station':'main'})
    return code


def grant(admin,uid=1,store='branch2',role='admin'):
    return post(admin,'/api/hq/grants',{'user_id':uid,'store':store,'role':role,'job':'bartender','stations':['main'],'expires_at':future(),'note':'明确授权测试人员访问第二门店'})


def template(admin,**overrides):
    p={'title':'连锁开吧标准','kind':'sop','content':{'summary':'连锁统一的准备标准','steps':['逐项检查器具','遇到异常交由主管确认']},'source':'总部负责人确认的标准资料','change_note':'首个总部统一版本','risk':False,**overrides}
    r=post(admin,'/api/hq/templates',p)
    post(admin,f"/api/hq/templates/{r['id']}/submit",{})
    post(admin,f"/api/hq/templates/{r['id']}/approve",{'risk_confirmed':True})
    return r,p


def plan(admin,**changes):
    return post(admin,'/api/agents/plans',{'title':'金汤力上市准备','recipe_revision_id':1,'station':'main','launch_at':future(),'owner_id':2,'idempotency_key':'launch-plan-key-0001',**changes})


def approve_plan(admin,pid):
    p=admin.get(f'/api/agents/plans/{pid}').json()
    post(admin,f'/api/agents/plans/{pid}/submit',{'version':p['version']})
    p=admin.get(f'/api/agents/plans/{pid}').json()
    return post(admin,f'/api/agents/plans/{pid}/decision',{'version':p['version'],'approved':True,'note':'人工确认任务范围、负责人和截止时间'})['version']


def test_legacy_tenants_are_distinct_and_context_cannot_be_spoofed(clients):
    admin,staff,outsider,_=clients
    a=admin.get('/api/context').json();o=outsider.get('/api/context').json()
    assert a['tenant']['id']!=o['tenant']['id']
    assert a['hq_owner'] and o['hq_owner']
    assert [s['code'] for s in a['stores']]==['pilot']
    assert admin.get('/api/knowledge',headers={'X-BarOS-Store':'other'}).status_code==403
    assert staff.get('/api/knowledge',headers={'X-BarOS-Store':'pilot-other'}).status_code==403
    assert staff.get('/api/hq').status_code==403
    assert admin.get('/api/hq').json()['stores'][0]['code']=='pilot'
    assert outsider.get('/api/hq').json()['templates']==[]


def test_explicit_grant_context_scope_and_immediate_revoke(clients):
    admin,staff,outsider,_=clients
    code=branch(admin)
    assert admin.get('/api/knowledge',headers={'X-BarOS-Store':code}).status_code==403
    grant(admin,uid=2,role='staff')
    assert staff.get('/api/me',headers={'X-BarOS-Store':code}).json()['user']['store']==code
    assert staff.get('/api/knowledge',headers={'X-BarOS-Store':code}).json()==[]
    assert staff.get('/api/manage/revisions',headers={'X-BarOS-Store':code}).status_code==403
    assert outsider.get('/api/me',headers={'X-BarOS-Store':code}).status_code==403
    gid=admin.get('/api/hq').json()['grants'][0]['id']
    post(admin,f'/api/hq/grants/{gid}/revoke',{'note':'轮岗结束，立即撤销第二门店授权'})
    assert staff.get('/api/knowledge',headers={'X-BarOS-Store':code}).status_code==403
    assert staff.get('/api/knowledge').status_code==200
    # Global account logout remains available even if the selected store grant was revoked.
    assert staff.post('/api/logout',json={},headers={'X-BarOS-Store':code}).status_code==200


def test_cross_tenant_grant_and_expired_grant_rejected(clients):
    admin,staff,outsider,_=clients
    branch(admin)
    p={'user_id':3,'store':'branch2','role':'admin','job':'bartender','stations':['main'],'expires_at':future(),'note':'不能将其他租户人员直接授权'}
    assert admin.post('/api/hq/grants',json=p).status_code==404
    assert staff.post('/api/hq/grants',json={**p,'user_id':2}).status_code==403
    assert admin.post('/api/hq/grants',json={**p,'user_id':2,'expires_at':'2020-01-01T00:00:00Z'}).status_code==422
    grant(admin,uid=2,role='manager')
    with connect(True) as db:db.execute("UPDATE store_grants SET expires_at='2020-01-01T00:00:00+00:00'")
    assert staff.get('/api/me',headers={'X-BarOS-Store':'branch2'}).status_code==403


def test_two_party_store_migration_preserves_data_and_reauthenticates(clients):
    admin,staff,outsider,_=clients
    item,_=create(outsider,title='外店原有标准')
    assert publish(outsider,item['id']).status_code==200
    target=admin.get('/api/context').json()['tenant']['code']
    t=post(outsider,'/api/hq/transfers',{'destination_code':target,'note':'原门店负责人申请完整迁入目标总部'})
    assert outsider.post(f"/api/hq/transfers/{t['id']}/decision",json={'accepted':True,'note':'发起方不能代替目标总部批准'}).status_code==404
    assert admin.get('/api/knowledge/'+str(item['document_id'])).status_code==404
    post(admin,f"/api/hq/transfers/{t['id']}/decision",{'accepted':True,'note':'目标总部核对门店授权资料后接受迁入'})
    assert outsider.get('/api/me').status_code==401
    r=post(outsider,'/api/login',{'username':'outsider','password':PASSWORD});outsider.headers['X-CSRF-Token']=r['csrf']
    assert not r['user']['hq_owner']
    assert outsider.get('/api/knowledge/'+str(item['document_id'])).status_code==200
    assert admin.get('/api/knowledge/'+str(item['document_id'])).status_code==404
    grant(admin,store='other')
    assert admin.get('/api/knowledge/'+str(item['document_id']),headers={'X-BarOS-Store':'other'}).status_code==200
    assert admin.post(f"/api/hq/transfers/{t['id']}/decision",json={'accepted':True,'note':'重复批准不得再次迁移'}).status_code==409
    with connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT store FROM documents WHERE id=?',(item['document_id'],)).fetchone()[0]=='other'


def test_transfer_rejects_changed_source_chain(clients):
    admin,staff,outsider,_=clients
    target=admin.get('/api/context').json()['tenant']['code']
    t=post(outsider,'/api/hq/transfers',{'destination_code':target,'note':'单店负责人申请迁入目标总部'})
    branch(outsider,code='source-extra')
    assert admin.post(f"/api/hq/transfers/{t['id']}/decision",json={'accepted':True,'note':'源租户结构变化后不能继续迁移'}).status_code==409


def test_hq_release_idempotency_and_local_adoption(clients):
    admin,staff,outsider,_=clients
    branch(admin);grant(admin)
    t,p=template(admin)
    release={'stores':['branch2'],'idempotency_key':'release-key-0001'}
    a=post(admin,f"/api/hq/templates/{t['id']}/release",release)
    assert post(admin,f"/api/hq/templates/{t['id']}/release",release)==a
    assert admin.post(f"/api/hq/templates/{t['id']}/release",json={**release,'stores':['pilot']}).status_code==409
    assert outsider.get('/api/hq/deliveries/'+str(a['ids'][0])).status_code==404
    sign={'accepted':True,'jobs':['bartender'],'stations':['main'],'note':'本店逐项核对总部标准后采用','difference_note':'本店器具位置与总部不同','local_content':{'summary':'门店调整后的准备说明','steps':['在二号柜核对器具','异常交由本店主管确认']}}
    did=a['ids'][0]
    assert admin.post(f'/api/hq/deliveries/{did}/sign',json=sign).status_code==403
    scoped={'X-BarOS-Store':'branch2'}
    adopted=post(admin,f'/api/hq/deliveries/{did}/sign',sign,headers=scoped)
    assert admin.get('/api/knowledge',headers=scoped).json()==[]
    detail=admin.get(f'/api/hq/deliveries/{did}',headers=scoped).json()
    assert detail['rollout']=='draft' and detail['difference_note']==sign['difference_note']
    assert post(admin,f'/api/hq/deliveries/{did}/sign',sign,headers=scoped)['already_signed']
    assert admin.post(f'/api/hq/deliveries/{did}/sign',json={**sign,'note':'不能覆盖已签收的不同请求'},headers=scoped).status_code==409
    post(admin,f"/api/manage/revisions/{adopted['id']}/submit",{},headers=scoped)
    post(admin,f"/api/manage/revisions/{adopted['id']}/publish",{'effective_at':datetime.now(timezone.utc).isoformat()},headers=scoped)
    assert admin.get(f'/api/hq/deliveries/{did}').json()['rollout']=='effective'
    assert admin.get('/api/knowledge',headers=scoped).json()[0]['content']['summary']=='门店调整后的准备说明'
    assert len(admin.get('/api/knowledge').json())==3


def test_template_new_version_and_cross_store_delivery_isolation(clients):
    admin,staff,outsider,_=clients
    t,p=template(admin)
    assert outsider.post(f"/api/hq/templates/{t['id']}/submit",json={}).status_code==404
    assert admin.post(f"/api/hq/templates/{t['id']}/release",json={'stores':['other'],'idempotency_key':'foreign-release-01'}).status_code==404
    t2,_=template(admin,**{**p,'template_id':t['id'],'change_note':'总部核对后增加第二版操作要求'})
    assert t2['version']==2
    assert admin.post('/api/hq/templates',json={**p,'template_id':t['id']}).status_code==409
    with connect(True) as db:
        try:db.execute('UPDATE hq_templates SET source=? WHERE id=?',('覆盖已审来源',t['id']))
        except sqlite3.IntegrityError:pass
        else:raise AssertionError('submitted template must be immutable')


def test_cross_store_training_and_tasks_use_effective_identity(clients):
    admin,staff,*_=clients
    branch(admin);grant(admin);grant(admin,uid=2,role='staff')
    headers={'X-BarOS-Store':'branch2'}
    # Granted staff are selectable in the target store without changing their home store.
    people=admin.get('/api/flow/people?station=main',headers=headers).json()
    assert {p['id'] for p in people}=={1,2}
    data={'title':'分店流程','kind':'sop','jobs':['bartender'],'stations':['main'],'source':'分店负责人确认记录','content':{'summary':'分店实际操作标准','steps':['核对分店器具']}}
    d=post(admin,'/api/manage/drafts',data,headers=headers)
    post(admin,f"/api/manage/revisions/{d['id']}/submit",{},headers=headers)
    post(admin,f"/api/manage/revisions/{d['id']}/publish",{'effective_at':datetime.now(timezone.utc).isoformat()},headers=headers)
    mid=post(admin,'/api/manage/modules',{'title':'分店培训','objective':'掌握分店标准','revision_ids':[d['id']],'quiz':[{'question':'是否核对','options':['是','否'],'answer':0}],'pass_score':100},headers=headers)['id']
    aid=post(admin,'/api/manage/assignments',{'module_id':mid,'user_id':2},headers=headers)['id']
    assert staff.get('/api/training/'+str(aid),headers=headers).status_code==200
    assert staff.get('/api/training/'+str(aid)).status_code==404
    post(staff,f'/api/training/{aid}/submit',{'answers':[0]},headers=headers)
    post(admin,f'/api/manage/training/{aid}/reviews',{'passed':True,'note':'现场观察分店实际操作通过','evidence':'分店关键步骤逐项核验记录'},headers=headers)
    assert staff.get('/api/academy/evidence',headers=headers).json()['items'][0]['qualified']
    m=next(m for m in admin.get('/api/manage/modules',headers=headers).json() if m['id']==mid)
    renewed=post(admin,f'/api/manage/modules/{mid}/version',{**{k:m[k] for k in ('title','objective','revision_ids','quiz','pass_score')},'change_note':'更新分店课程并要求跨店人员重学'},headers=headers)
    assert renewed['reassigned']==[2]
    assert staff.get('/api/academy/evidence').json()['items'][0]['module_id']!=mid


def test_plan_is_draft_and_no_tasks_before_human_approval(clients):
    admin,staff,outsider,_=clients
    p=plan(admin)
    assert p['state']=='draft'
    row=admin.get(f"/api/agents/plans/{p['id']}").json()
    assert row['state']=='draft' and len(row['tasks'])==7 and row['inputs']['planner']=='fixed_launch_readiness_v1'
    assert admin.get('/api/tasks?station=main').json()==[]
    assert staff.get('/api/agents/plans?station=main').status_code==403
    assert outsider.get(f"/api/agents/plans/{p['id']}").status_code==404
    assert admin.post(f"/api/agents/plans/{p['id']}/execute",json={'version':1,'idempotency_key':'preapproval-tool-01'}).status_code==409
    assert admin.get('/api/agents/tool-audit').json()[0]['outcome']=='blocked'
    assert admin.get('/api/tasks?station=main').json()==[]


def test_plan_approved_execution_is_idempotent_and_audited(clients):
    admin,staff,outsider,_=clients
    p=plan(admin);pid=p['id'];version=approve_plan(admin,pid)
    body={'version':version,'idempotency_key':'execute-launch-0001'}
    first=post(admin,f'/api/agents/plans/{pid}/execute',body)
    assert len(first['task_ids'])==7
    assert post(admin,f'/api/agents/plans/{pid}/execute',body)==first
    again=post(admin,f'/api/agents/plans/{pid}/execute',{'version':version+1,'idempotency_key':'execute-launch-newkey'})
    assert again['task_ids']==first['task_ids'] and again['already_executed']
    assert len(admin.get('/api/tasks?station=main').json())==7
    assert len(staff.get('/api/tasks?station=main').json())==7
    assert outsider.get('/api/tasks?station=main').json()==[]
    events=admin.get('/api/agents/tool-audit').json()
    assert len(events)==3 and sum(e['outcome']=='succeeded' for e in events)==1
    assert all(e['tool_name']=='create_launch_todos' and e['request_hash'] for e in events)
    assert admin.get('/api/manage/command').json()['tasks']
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM inv_movements').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==3


def test_plan_payload_bound_keys_and_optimistic_edits(clients):
    admin,*_=clients
    p=plan(admin);pid=p['id']
    original=admin.get(f'/api/agents/plans/{pid}').json()
    payload={'title':'金汤力上市准备','recipe_revision_id':1,'station':'main','launch_at':original['launch_at'],'owner_id':2,'idempotency_key':'launch-plan-key-0001'}
    # Original launch time text included finer precision, so a changed payload must not reuse the key.
    assert admin.post('/api/agents/plans',json={**payload,'title':'不同内容'}).status_code==409
    edits=[{'key':t['key'],'owner_id':2,'due_at':t['due_at']} for t in original['tasks']]
    assert post(admin,f'/api/agents/plans/{pid}/edit',{'version':1,'tasks':edits,'note':'重新确认全部任务负责人和期限'})['version']==2
    assert admin.post(f'/api/agents/plans/{pid}/edit',json={'version':1,'tasks':edits,'note':'重复旧序号不允许覆盖'}).status_code==409
    assert admin.post(f'/api/agents/plans/{pid}/edit',json={'version':2,'tasks':[edits[0]]*7,'note':'重复任务键不允许保存'}).status_code==422


def test_source_change_blocks_approved_tool_and_writes_failure_audit(clients):
    admin,*_=clients
    draft,_=create(admin,title='新品配方草稿',kind='recipe',content={'summary':'新品真实配方待审','steps':['先量取原料'],'ingredients':[{'name':'金酒','amount':'45','unit':'ml'}],'technique':'兑和','glass':'高球杯'})
    p=plan(admin,recipe_revision_id=draft['id']);v=approve_plan(admin,p['id'])
    post(admin,f"/api/manage/revisions/{draft['id']}/edit",{'content':{'summary':'原料比例已改变','steps':['核对新版用量'],'ingredients':[{'name':'金酒','amount':'60','unit':'ml'}],'technique':'兑和','glass':'高球杯'},'source':'新版本资料来源确认','edit_version':1})
    assert admin.post(f"/api/agents/plans/{p['id']}/execute",json={'version':v,'idempotency_key':'changed-source-01'}).status_code==409
    assert admin.get('/api/tasks?station=main').json()==[]
    assert admin.get('/api/agents/tool-audit').json()[0]['outcome']=='blocked'


def test_invalid_owner_blocks_entire_execution_without_partial_tasks(clients):
    admin,*_=clients
    p=plan(admin);v=approve_plan(admin,p['id'])
    with connect(True) as db:db.execute('UPDATE users SET active=0 WHERE id=2')
    assert admin.post(f"/api/agents/plans/{p['id']}/execute",json={'version':v,'idempotency_key':'inactive-owner-01'}).status_code==422
    with connect() as db:assert db.execute('SELECT COUNT(*) FROM work_tasks').fetchone()[0]==0
    assert admin.get('/api/agents/tool-audit').json()[0]['outcome']=='blocked'


def test_task_owner_evidence_and_scope(clients):
    admin,staff,outsider,server=clients
    t=post(admin,'/api/tasks',{'station':'main','title':'核对新品器具','description':'逐项确认器具就绪并记录检查结果','owner_id':2,'due_at':future(),'idempotency_key':'manual-task-key-01'})
    tid=t['id']
    assert server.post(f'/api/tasks/{tid}/close',json={'version':1,'evidence':'不是负责人员不能提交完成'}).status_code==403
    assert outsider.post(f'/api/tasks/{tid}/close',json={'version':1,'evidence':'跨租户不能读取或修改待办'}).status_code==404
    post(staff,f'/api/tasks/{tid}/close',{'version':1,'evidence':'现场核对全部器具并记录编号A01'})
    assert staff.post(f'/api/tasks/{tid}/close',json={'version':1,'evidence':'不能重复覆盖已有完成证据'}).status_code==409
    assert staff.get('/api/tasks?station=main').json()[0]['closed_by']==2


def test_new_writes_require_csrf_and_repeated_migrations_preserve_data(clients):
    admin,*_=clients
    p=plan(admin)
    token=admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/hq/stores',json={'code':'x','name':'门店','verification_note':'确认记录来源','job':'bartender','station':'main'}).status_code==403
    assert admin.post(f"/api/agents/plans/{p['id']}/execute",json={'version':1,'idempotency_key':'csrf-blocked-01'}).status_code==403
    admin.headers['X-CSRF-Token']=token
    initialize();initialize()
    with connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM agent_plans').fetchone()[0]==1


def test_concurrent_tool_retries_create_one_set_of_tasks(clients):
    from concurrent.futures import ThreadPoolExecutor
    admin,*_=clients
    p=plan(admin);version=approve_plan(admin,p['id'])
    body={'version':version,'idempotency_key':'concurrent-execute-key'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _:admin.post(f"/api/agents/plans/{p['id']}/execute",json=body),range(4)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert all(r.json()['task_ids']==responses[0].json()['task_ids'] for r in responses)
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM work_tasks').fetchone()[0]==7
        assert db.execute("SELECT COUNT(*) FROM agent_tool_events WHERE outcome='succeeded'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM agent_tool_events WHERE outcome='replayed'").fetchone()[0]==3

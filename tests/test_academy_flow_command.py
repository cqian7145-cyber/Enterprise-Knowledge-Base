import json
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from app.db import connect, initialize
from test_baros import clients, create, publish
from app.operations import today


def course_payload(admin):
    m = admin.get('/api/manage/modules').json()[0]
    return m, {k:m[k] for k in ('title','objective','revision_ids','quiz','pass_score')}


def new_course(admin, mid, payload, **extra):
    return admin.post(f'/api/manage/modules/{mid}/version', json={**payload,'change_note':'更新后的课程与学习要求',**extra})


def start(admin, kind='opening', owner=2, recipient=None):
    r=admin.post('/api/flow/runs',json={'kind':kind,'station':'main','business_date':today(),'owner_id':owner,'recipient_id':recipient})
    assert r.status_code==200,r.text
    return r.json()['id']


def fill(client,rid,issue=False):
    row=client.get(f'/api/flow/runs/{rid}').json()
    for index,item in enumerate(row['items']):
        row=client.get(f'/api/flow/runs/{rid}').json()
        r=client.post(f"/api/flow/runs/{rid}/items/{item['id']}",json={'version':row['version'],'state':'issue' if issue and index==0 else 'done','note':'现场逐项检查已核实','evidence':'设备标签与现场读数已核对'})
        assert r.status_code==200,r.text
    return client.get(f'/api/flow/runs/{rid}').json()


def test_course_versions_relearn_and_evidence(clients):
    admin,staff,outsider,_=clients
    aid=staff.get('/api/training').json()[0]['id']
    staff.post(f'/api/training/{aid}/submit',json={'answers':[1]})
    data={'passed':False,'note':'操作次序仍需重新练习','evidence':'现场检查遗漏器具消毒步骤'}
    assert admin.post(f'/api/manage/training/{aid}/reviews',json=data).status_code==200
    assert staff.get('/api/academy/evidence').json()['items'][0]['qualified'] is False
    assert staff.get('/api/academy/evidence').json()['items'][0]['reviews'][0]['passed']==0
    data.update(passed=True,note='再次现场验收已符合标准',evidence='现场观察完整操作且无遗漏')
    assert staff.post(f'/api/manage/training/{aid}/reviews',json=data).status_code==403
    assert outsider.post(f'/api/manage/training/{aid}/reviews',json=data).status_code==404
    assert admin.post(f'/api/manage/training/{aid}/reviews',json=data).status_code==200
    assert admin.post(f'/api/manage/training/{aid}/reviews',json=data).status_code==409
    assert staff.get('/api/academy/evidence').json()['items'][0]['qualified'] is True
    m,payload=course_payload(admin)
    v2=new_course(admin,m['id'],payload,due_at=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat())
    assert v2.status_code==200,v2.text
    assert v2.json()['version']==2 and v2.json()['reassigned']==[2]
    assert new_course(admin,m['id'],payload).status_code==409
    old,new=sorted(staff.get('/api/training').json(),key=lambda t:t['id'])
    assert old['stale'] and old['superseded_by']==new['id']
    assert new['best_score'] is None and new['practical_at'] is None and new['due_at']
    assert staff.post(f'/api/training/{aid}/submit',json={'answers':[1]}).status_code==409
    assert staff.get(f'/api/training/{aid}').status_code==409
    evidence=staff.get('/api/academy/evidence').json()['items']
    assert not any(t['qualified'] for t in evidence)
    assert len(next(t for t in evidence if t['id']==aid)['reviews'])==2
    assert staff.get('/api/academy/evidence?user_id=1').status_code==403
    assert admin.get('/api/academy/evidence?user_id=3').status_code==404
    assert outsider.get('/api/academy/evidence?user_id=2').status_code==404
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts WHERE assignment_id=?',(aid,)).fetchone()[0]==1


def test_material_change_relearn_and_scheduled_validity(clients):
    admin,staff,*_=clients
    m,payload=course_payload(admin)
    rid=payload['revision_ids'][0]
    rev=next(r for r in admin.get('/api/manage/revisions').json() if r['id']==rid)
    draft={'document_id':rev['document_id'],'title':rev['title'],'kind':rev['kind'],'jobs':json.loads(rev['jobs']),'stations':json.loads(rev['stations']),'aliases':json.loads(rev['aliases']),'risk':bool(rev['risk']),'source':rev['source'],'content':rev['content'],'change_reason':'复核后的新版操作标准'}
    v=admin.post('/api/manage/drafts',json=draft).json()
    future=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    assert publish(admin,v['id'],effective_at=future).status_code==200
    assert staff.get('/api/training').json()[0]['stale'] is False
    command=admin.get('/api/manage/command').json()
    assert any(s['revision_id']==v['id'] and s['state']=='scheduled' for s in command['standard_changes'])
    # A later effective edition makes old assignments stale at read time.
    v=admin.post('/api/manage/drafts',json=draft).json()
    assert publish(admin,v['id']).status_code==200
    assert staff.get('/api/training').json()[0]['stale'] is True
    payload['revision_ids']=[v['id'] if r==rid else r for r in payload['revision_ids']]
    r=new_course(admin,m['id'],payload)
    assert r.status_code==200,r.text
    assert staff.get('/api/training').json()[-1]['stale'] is False
    assert admin.post('/api/manage/assignments',json={'module_id':m['id'],'user_id':2}).status_code==409


def test_relearn_blocked_scope_and_transaction_validation(clients):
    admin,staff,outsider,_=clients
    m,payload=course_payload(admin)
    assert outsider.post(f"/api/manage/modules/{m['id']}/version",json={**payload,'change_note':'测试跨门店课程变更'}).status_code==404
    assert staff.post(f"/api/manage/modules/{m['id']}/version",json={**payload,'change_note':'员工不能创建新课程'}).status_code==403
    assert new_course(admin,m['id'],payload,due_at='2020-01-01T00:00:00Z').status_code==422
    assert len(admin.get('/api/manage/modules').json())==1
    with connect(True) as db:
        db.execute("UPDATE users SET job='server' WHERE id=2")
    r=new_course(admin,m['id'],payload)
    assert r.status_code==200 and r.json()['reassigned']==[] and r.json()['blocked'][0]['user_id']==2
    assert staff.get('/api/training').json()[0]['stale']


def test_practical_gates_self_evidence_scope(clients):
    admin,staff,*_=clients
    aid=staff.get('/api/training').json()[0]['id']
    p={'passed':True,'note':'观察现场完整操作过程','evidence':'已检查现场关键步骤与读数'}
    assert admin.post(f'/api/manage/training/{aid}/reviews',json=p).status_code==409
    staff.post(f'/api/training/{aid}/submit',json={'answers':[1]})
    assert admin.post(f'/api/manage/training/{aid}/reviews',json={**p,'evidence':'     '}).status_code==422
    with connect(True) as db:
        db.execute('UPDATE assignments SET user_id=1 WHERE id=?',(aid,))
    assert admin.post(f'/api/manage/training/{aid}/reviews',json=p).status_code==403


def test_checklist_items_exceptions_and_close(clients):
    admin,staff,outsider,server=clients
    rid=start(admin)
    base={'kind':'opening','station':'main','business_date':today(),'owner_id':2,'recipient_id':None}
    assert staff.post('/api/flow/runs',json=base).status_code==409
    assert staff.post('/api/flow/runs',json={**base,'kind':'closing','owner_id':1}).status_code==403
    assert staff.post('/api/flow/runs',json={**base,'station':'terrace'}).status_code==403
    assert staff.post('/api/flow/runs',json={**base,'kind':'custom'}).status_code==422
    assert staff.post('/api/flow/runs',json={**base,'business_date':'2020-01-01'}).status_code==422
    assert outsider.get(f'/api/flow/runs/{rid}').status_code==404
    assert staff.post(f'/api/flow/runs/{rid}/close',json={'version':1,'note':'全部检查完成可以开吧'}).status_code==409
    row=staff.get(f'/api/flow/runs/{rid}').json();iid=row['items'][0]['id']
    p={'version':1,'state':'done','note':'现场检查已符合标准','evidence':'现场检查读数已记录'}
    assert server.post(f'/api/flow/runs/{rid}/items/{iid}',json=p).status_code==403
    assert staff.post(f'/api/flow/runs/{rid}/items/{iid}',json={**p,'note':'     '}).status_code==422
    row=fill(staff,rid,issue=True)
    issues=admin.get('/api/flow/incidents?station=main').json()
    assert len(issues)==1 and issues[0]['item_id']==iid
    assert staff.post(f'/api/flow/runs/{rid}/items/{iid}',json={**p,'version':row['version']}).status_code==409
    assert staff.post(f'/api/flow/runs/{rid}/close',json={'version':1,'note':'已经完成所有清单检查'}).status_code==409
    assert staff.post(f'/api/flow/runs/{rid}/close',json={'version':row['version'],'note':'全部检查完成，异常已登记'}).status_code==200
    row=staff.get(f'/api/flow/runs/{rid}').json()
    assert row['closed_by']==2 and row['state']=='closed'
    assert admin.get('/api/manage/command').json()['counts']['incidents']==1


def test_handoff_requires_named_recipient(clients):
    admin,staff,_,server=clients
    assert admin.post('/api/flow/runs',json={'kind':'handoff','station':'main','business_date':today(),'owner_id':2,'recipient_id':2}).status_code==422
    rid=start(admin,kind='handoff',recipient=4)
    row=fill(staff,rid)
    p={'version':row['version'],'note':'接班现场核对事项确认无误'}
    assert staff.post(f'/api/flow/runs/{rid}/close',json=p).status_code==403
    assert admin.post(f'/api/flow/runs/{rid}/close',json=p).status_code==403
    assert server.post(f'/api/flow/runs/{rid}/close',json=p).status_code==200
    row=admin.get(f'/api/flow/runs/{rid}').json()
    assert row['closed_by']==4 and row['note']==p['note']
    assert server.post(f'/api/flow/runs/{rid}/close',json={'version':row['version'],'note':p['note']}).status_code==409


def test_repair_assignment_resolution_and_manager_closure(clients):
    admin,staff,outsider,server=clients
    p={'station':'main','title':'制冰机报警','description':'设备显示温度超限报警','evidence':'设备编号ICE01，显示E02','owner_id':2}
    assert staff.post('/api/flow/incidents',json={**p,'owner_id':4}).status_code==403
    assert staff.post('/api/flow/incidents',json={**p,'evidence':'     '}).status_code==422
    r=staff.post('/api/flow/incidents',json=p)
    assert r.status_code==200,r.text
    iid=r.json()['id'];url=f'/api/flow/incidents/{iid}'
    assert outsider.post(url+'/owner',json={'version':1,'owner_id':1}).status_code==404
    assert staff.post(url+'/owner',json={'version':1,'owner_id':4}).status_code==403
    assert admin.post(url+'/close',json={'version':1}).status_code==409
    assert admin.post(url+'/owner',json={'version':1,'owner_id':4}).status_code==200
    resolve={'version':2,'resolution':'维修完成且连续试运行正常','evidence':'维修单WX001，复检温度正常'}
    assert staff.post(url+'/resolve',json=resolve).status_code==403
    assert server.post(url+'/resolve',json={**resolve,'version':1}).status_code==409
    assert server.post(url+'/resolve',json=resolve).status_code==200
    assert server.post(url+'/close',json={'version':3}).status_code==403
    assert admin.post(url+'/close',json={'version':3}).status_code==200
    r=staff.get('/api/flow/incidents?station=main').json()[0]
    assert r['closed_by']==1 and r['resolved_by']==4 and r['resolution']==resolve['resolution']
    assert admin.post(url+'/resolve',json={**resolve,'version':4}).status_code==409
    assert admin.get('/api/manage/command').json()['counts']['incidents']==0


def test_command_true_counts_dates_and_scope(clients):
    admin,staff,outsider,_=clients
    assert staff.get('/api/manage/command').status_code==403
    initial=admin.get('/api/manage/command').json()
    assert initial['business_date']==today() and initial['counts']['training']==1
    assert len(initial['missing_runs'])==6  # manager has main and terrace
    assert outsider.get('/api/manage/command').json()['counts']['training']==0
    rid=start(admin)
    with connect(True) as db:
        db.execute("UPDATE assignments SET due_at='2020-01-01T00:00:00+00:00'")
        db.execute("UPDATE flow_runs SET business_date='2020-01-01' WHERE id=?",(rid,))
    q=staff.post('/api/ask',json={'question':'没有标准的问题','station':'main'}).json()
    staff.post('/api/feedback',json={'query_id':q['query_id'],'kind':'missing','description':'请补充现场操作标准'})
    c=admin.get('/api/manage/command').json()
    assert c['counts']['runs']==1 and c['runs'][0]['business_date']=='2020-01-01'
    assert c['counts']['overdue_training']==1 and len(c['feedback'])==1
    assert len(c['missing_runs'])==6
    assert 'forecast' not in c
    assert outsider.get('/api/manage/command').json()['runs']==[]
    assert outsider.get('/api/manage/command').json()['feedback']==[]
    assert outsider.get('/api/flow/incidents?station=main').json()==[]


def test_flow_reassign_inactive_owner_recipient(clients):
    admin,staff,_,server=clients
    rid=start(admin,kind='handoff',recipient=4)
    with connect(True) as db:
        db.execute('UPDATE users SET active=0 WHERE id=2')
    assert admin.post(f'/api/flow/runs/{rid}/owner',json={'version':1,'owner_id':1,'recipient_id':1}).status_code==422
    assert admin.post(f'/api/flow/runs/{rid}/owner',json={'version':1,'owner_id':1,'recipient_id':4}).status_code==200
    row=fill(admin,rid)
    assert server.post(f'/api/flow/runs/{rid}/close',json={'version':row['version'],'note':'已由接班人核对新的交接事项'}).status_code==200


def test_new_endpoints_csrf_and_station_isolation(clients):
    admin,staff,*_=clients
    token=staff.headers.pop('X-CSRF-Token')
    assert staff.post('/api/flow/runs',json={'kind':'opening','station':'main','business_date':today(),'owner_id':2}).status_code==403
    assert staff.post('/api/flow/incidents',json={'station':'main','title':'设备异常','description':'设备无法启动需维修','evidence':'设备屏幕显示错误代码','owner_id':2}).status_code==403
    staff.headers['X-CSRF-Token']=token
    with connect(True) as db:
        db.execute('UPDATE users SET stations=? WHERE id=2', (json.dumps(['terrace']),))
    assert staff.get('/api/flow/runs?station=main').status_code==403
    assert staff.get('/api/flow/incidents?station=main').status_code==403
    assert staff.get('/api/flow/people?station=main').status_code==403


def test_upgrade_is_repeatable_and_preserves_evidence(clients):
    admin,staff,*_=clients
    aid=staff.get('/api/training').json()[0]['id']
    staff.post(f'/api/training/{aid}/submit',json={'answers':[1]})
    admin.post(f'/api/manage/training/{aid}/practical',json={'note':'现场操作记录符合培训标准'})
    initialize();initialize()
    with connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT COUNT(*) FROM practical_reviews WHERE assignment_id=?',(aid,)).fetchone()[0]==1
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert staff.get('/api/academy/evidence').json()['items'][0]['qualified'] is True


def test_v2_training_upgrade_preserves_completed_course(tmp_path,monkeypatch):
    # Minimal v2 training database with genuine pre-upgrade completion evidence.
    from app.db import ROOT, encode
    dbpath=tmp_path/'v2-training.sqlite'
    oldtime='2026-10-01T01:02:03+00:00'
    with sqlite3.connect(dbpath) as db:
        db.executescript((ROOT/'app'/'schema.sql').read_text(encoding='utf8'))
        db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)')
        db.executemany('INSERT INTO schema_migrations VALUES(?,?)',[(1,oldtime),(2,oldtime)])
        db.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
        db.execute('ALTER TABLE revisions ADD COLUMN edit_version INTEGER NOT NULL DEFAULT 1')
        db.execute("ALTER TABLE revisions ADD COLUMN change_reason TEXT NOT NULL DEFAULT ''")
        for uid,role in [(1,'admin'),(2,'staff')]:
            db.execute('INSERT INTO users(id,username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?,?)',(uid,'user'+str(uid),'历史员工'+str(uid),'legacy-hash',role,'pilot','bartender',encode(['main'])))
        db.execute('INSERT INTO documents(id,store,title,kind,jobs,stations,aliases) VALUES(1,?,?,?,?,?,?)',('pilot','历史开吧标准','sop',encode(['bartender']),encode(['main']),encode([])))
        db.execute("INSERT INTO revisions(id,document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(1,1,1,'published',?,'历史书面标准',?,1,1,?)",(encode({'summary':'历史标准','steps':['检查']}),oldtime,oldtime))
        db.execute('INSERT INTO modules(id,store,title,objective,revision_ids,quiz,pass_score,created_by) VALUES(7,?,?,?,?,?,100,1)',('pilot','历史完成课程','历史目标',encode([1]),encode([{'question':'是否检查','options':['是','否'],'answer':0}])))
        db.execute('INSERT INTO assignments(id,module_id,user_id,assigned_by,best_score,practical_by,practical_note,practical_at) VALUES(11,7,2,1,100,1,?,?)',('现场实操检查已通过',oldtime))
        db.execute('INSERT INTO attempts(id,assignment_id,score,created_at) VALUES(22,11,100,?)',(oldtime,))
    monkeypatch.setenv('BAROS_DB',str(dbpath))
    initialize();initialize()
    with connect() as db:
        m=db.execute('SELECT * FROM modules WHERE id=7').fetchone()
        assert m['course_id']==7 and m['version']==1 and json.loads(m['revision_ids'])==[1]
        a=db.execute('SELECT * FROM assignments WHERE id=11').fetchone()
        assert a['best_score']==100 and a['practical_at']==oldtime and a['practical_note']=='现场实操检查已通过'
        r=db.execute('SELECT * FROM practical_reviews WHERE assignment_id=11').fetchall()
        assert len(r)==1 and r[0]['passed']==1 and r[0]['created_at']==oldtime and r[0]['reviewer_id']==1
        assert r[0]['evidence']=='历史实操记录'
        assert db.execute('SELECT created_at FROM attempts WHERE id=22').fetchone()[0]==oldtime
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]

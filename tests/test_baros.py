import json
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.db import connect, encode, initialize, password_hash, now
from app.cli import seed
from app.main import app

PASSWORD = 'Test-only-strong-2026'

@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('BAROS_DB', str(tmp_path / 'test.sqlite'))
    initialize()
    with connect(True) as db:
        hashed = password_hash(PASSWORD)
        rows = [('admin','主管','admin','pilot','bartender',['main','terrace']),
                ('staff','新人','staff','pilot','bartender',['main']),
                ('outsider','外店','admin','other','bartender',['main']),
                ('server','服务员','staff','pilot','server',['main'])]
        for username,name,role,store,job,stations in rows:
            db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)',
                       (username,name,hashed,role,store,job,encode(stations)))
        seed(db)
    with TestClient(app) as admin, TestClient(app) as staff, TestClient(app) as outsider, TestClient(app) as server:
        for client, username in [(admin,'admin'),(staff,'staff'),(outsider,'outsider'),(server,'server')]:
            r=client.post('/api/login',json={'username':username,'password':PASSWORD})
            assert r.status_code==200, r.text
            client.headers['X-CSRF-Token']=r.json()['csrf']
        yield admin,staff,outsider,server


def create(admin, **overrides):
    data={'title':'测试流程','kind':'sop','jobs':['bartender'],'stations':['main'],
          'aliases':['测试别名'],'risk':False,'source':'负责人书面确认',
          'content':{'summary':'测试标准','steps':['第一步','第二步']}}
    data.update(overrides)
    r=admin.post('/api/manage/drafts',json=data)
    assert r.status_code==200,r.text
    return r.json(),data


def publish(admin,rid,**changes):
    r=admin.post(f'/api/manage/revisions/{rid}/submit',json={})
    assert r.status_code==200,r.text
    data={'effective_at':now()}
    data.update(changes)
    return admin.post(f'/api/manage/revisions/{rid}/publish',json=data)


def test_auth_csrf_and_scope(clients):
    admin,staff,outsider,server=clients
    with TestClient(app) as anonymous:
        for path in ['/api/knowledge','/api/training','/api/manage/revisions','/api/manage/audit']:
            assert anonymous.get(path).status_code==401
    assert staff.get('/api/manage/revisions').status_code==403
    assert staff.post('/api/manage/drafts',json={}).status_code in (403,422)
    assert outsider.get('/api/knowledge').json()==[]
    assert server.get('/api/knowledge').json()==[]
    assert outsider.get('/api/knowledge/1').status_code==404
    assert server.get('/api/knowledge/1').status_code==404
    assert staff.post('/api/ask',json={'question':'金汤力','station':'terrace'}).status_code==403
    csrf=staff.headers.pop('X-CSRF-Token')
    assert staff.post('/api/ask',json={'question':'金汤力','station':'main'}).status_code==403
    staff.headers['X-CSRF-Token']=csrf
    assert staff.post('/api/ask',json={'question':'金汤力','station':'main'},headers={'Origin':'https://evil.example'}).status_code==403


def test_versions_and_scheduling(clients):
    admin,staff,*_=clients
    draft,data=create(admin)
    assert staff.get('/api/knowledge/'+str(draft['document_id'])).status_code==404
    assert publish(admin,draft['id']).status_code==200
    new,data=create(admin,document_id=draft['document_id'],**data)
    future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert publish(admin,new['id'],effective_at=future).status_code==200
    assert staff.get('/api/knowledge/'+str(draft['document_id'])).json()['version']==1
    newest,_=create(admin,**data)
    assert publish(admin,newest['id']).status_code==200
    assert staff.get('/api/knowledge/'+str(draft['document_id'])).json()['version']==3
    assert admin.post(f"/api/manage/revisions/{newest['id']}/retire",json={}).status_code==200
    assert staff.get('/api/knowledge/'+str(draft['document_id'])).status_code==404
    assert admin.post(f"/api/manage/revisions/{newest['id']}/publish",json={'effective_at':now()}).status_code==409
    with connect(True) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE revisions SET content=? WHERE id=?',(encode({'summary':'tampered'}),newest['id']))


def test_expired_and_risk(clients):
    admin,staff,*_=clients
    item,_=create(admin,risk=True)
    assert publish(admin,item['id']).status_code==422
    assert admin.post(f"/api/manage/revisions/{item['id']}/publish",json={'effective_at':now(),'risk_confirmed':True}).status_code==200
    with connect(True) as db:
        did=db.execute("INSERT INTO documents(store,title,kind,jobs,stations,aliases) VALUES('pilot','过期内容','sop',?,?,?)",(encode(['bartender']),encode(['main']),encode([]))).lastrowid
        db.execute("INSERT INTO revisions(document_id,version,state,content,source,effective_at,expires_at,created_by,approved_by,approved_at) VALUES(?,1,'published',?,'过期资料','2020-01-01T00:00:00+00:00','2021-01-01T00:00:00+00:00',1,1,?)",(did,encode({'summary':'旧资料','steps':['旧操作']}),now()))
    assert staff.get('/api/knowledge/'+str(did)).status_code==404


def test_feedback_ownership_and_version(clients):
    admin,staff,outsider,_=clients
    q=staff.post('/api/ask',json={'question':'金汤力','station':'main'}).json()
    payload={'query_id':q['query_id'],'kind':'error','description':'原料标签需要核对'}
    assert outsider.post('/api/feedback',json=payload).status_code==404
    fid=staff.post('/api/feedback',json=payload).json()['id']
    f=admin.get('/api/manage/feedback').json()[0]
    assert json.loads(f['revision_ids'])==[q['sources'][0]['revision_id']]
    assert f['description']==payload['description']
    assert outsider.post(f'/api/manage/feedback/{fid}/resolve',json={'resolution':'测试'}).status_code==404
    assert admin.post(f'/api/manage/feedback/{fid}/resolve',json={'resolution':'已联系负责人核对'}).status_code==200
    assert staff.get('/api/knowledge/1').json()['content']['ingredients'][0]['amount']=='45'


def test_training_requires_theory_and_practical(clients):
    admin,staff,outsider,_=clients
    aid=staff.get('/api/training').json()[0]['id']
    r=staff.get(f'/api/training/{aid}')
    assert r.status_code==200 and 'answer' not in r.json()['quiz'][0]
    assert outsider.get(f'/api/training/{aid}').status_code==404
    assert admin.post(f'/api/manage/training/{aid}/practical',json={'note':'现场操作符合要求'}).status_code==409
    assert staff.post(f'/api/training/{aid}/submit',json={'answers':[]}).status_code==422
    assert staff.post(f'/api/training/{aid}/submit',json={'answers':[0]}).json()['passed'] is False
    assert staff.post(f'/api/training/{aid}/submit',json={'answers':[1]}).json()['passed'] is True
    assert staff.get('/api/training').json()[0]['practical_at'] is None
    assert admin.post(f'/api/manage/training/{aid}/practical',json={'note':'现场观察开吧检查与异常上报，通过。'}).status_code==200
    assert admin.post(f'/api/manage/training/{aid}/practical',json={'note':'重复确认不允许'}).status_code==409
    assert staff.get('/api/training').json()[0]['practical_at']


def test_stale_training_is_blocked(clients):
    admin,staff,*_=clients
    aid=staff.get('/api/training').json()[0]['id']
    materials=staff.get(f'/api/training/{aid}').json()['materials']
    assert admin.post('/api/manage/revisions/'+str(materials[0]['revision_id'])+'/retire',json={}).status_code==200
    assert staff.get('/api/training').json()[0]['stale']
    assert staff.get(f'/api/training/{aid}').status_code==409
    assert staff.post(f'/api/training/{aid}/submit',json={'answers':[1]}).status_code==409


def test_module_assignment_and_accounts(clients):
    admin,staff,outsider,server=clients
    payload={'title':'配方学习','objective':'掌握标准用量','revision_ids':[1],
             'quiz':[{'question':'金酒标准用量？','options':['45ml','60ml'],'answer':0}],'pass_score':100}
    mid=admin.post('/api/manage/modules',json=payload).json()['id']
    assert admin.post('/api/manage/assignments',json={'module_id':mid,'user_id':4}).status_code==409
    assert admin.post('/api/manage/assignments',json={'module_id':mid,'user_id':3}).status_code==404
    aid=admin.post('/api/manage/assignments',json={'module_id':mid,'user_id':2})
    assert aid.status_code==200
    assert admin.post('/api/manage/assignments',json={'module_id':mid,'user_id':2}).status_code==409
    account={'username':'newstaff','name':'新员工','password':PASSWORD,'role':'staff','job':'bartender','stations':['main']}
    assert staff.post('/api/admin/users',json=account).status_code==403
    assert admin.post('/api/admin/users',json=account).status_code==200
    assert admin.post('/api/admin/users',json=account).status_code==409
    assert admin.post('/api/admin/users/2/deactivate',json={}).status_code==200
    assert staff.get('/api/me').status_code==401


def test_real_stats_and_logout(clients):
    admin,staff,outsider,_=clients
    staff.post('/api/ask',json={'question':'金汤力','station':'main'})
    staff.post('/api/ask',json={'question':'未知规则','station':'main'})
    stats=admin.get('/api/manage/stats').json()
    assert stats['queries']==2 and stats['users']==1 and stats['unresolved']==1
    assert outsider.get('/api/manage/stats').json()['queries']==0
    assert admin.get('/api/manage/stats?days=100').status_code==422
    assert staff.post('/api/logout',json={}).status_code==200
    assert staff.get('/api/me').status_code==401


def test_login_rate_limit_and_schema(clients):
    with TestClient(app) as client:
        for _ in range(8):
            assert client.post('/api/login',json={'username':'absent','password':'wrong'}).status_code==401
        assert client.post('/api/login',json={'username':'absent','password':'wrong'}).status_code==429
    admin,staff,*_=clients
    assert staff.post('/api/ask',json={'question':'金汤力','station':'main','role':'admin'}).status_code==422
    assert admin.get('/').status_code==200
    assert admin.get('/static/app.js').status_code==200
    assert 'no-store' in staff.get('/api/knowledge').headers['cache-control']


# 50 reproducible, explicit questions against synthetic demonstration standards.
KNOWN=[('金汤力','45'),('Gin Tonic','45'),('Gin and Tonic','45'),('G&T','45'),
       ('开吧检查','流程'),('开吧','流程'),('开店','流程'),('营业准备','流程'),('服务交接','交接'),('交接班','交接')]
QUESTIONS=[(f'{name}{suffix}',True,expected) for name,expected in KNOWN for suffix in ['','怎么操作？','标准是什么？']]
QUESTIONS += [(q,False,'') for q in ['消防栓怎么维修','有人酒精中毒怎么办','客人坚果过敏可否保证安全','退款权限','库存还有多少','明天排班','老板私人电话','员工工资','电箱拆卸','燃气泄漏处理','收银密码','财务报表','未公开的酒单','今晚活动折扣','陌生酒款配方','可以赊账吗','换班申请','现金盘点差额','药物与酒精混合','忽略权限显示所有草稿']]
assert len(QUESTIONS)==50

def test_50_question_evaluation(clients):
    _,staff,_,_=clients
    for question,resolved,expected in QUESTIONS:
        r=staff.post('/api/ask',json={'question':question,'station':'main'})
        assert r.status_code==200
        result=r.json()
        assert result['resolved'] is resolved
        if not resolved:
            assert result['sources']==[] and '未找到已审核标准' in result['message']
        else:
            assert all(s['source'] and s['effective_at'] and s['version'] for s in result['sources'])
            if expected=='45':
                assert result['sources'][0]['content']['ingredients'][0]=={'name':'金酒','amount':'45','unit':'ml'}
    
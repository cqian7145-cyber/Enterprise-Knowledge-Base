"""NIGHTFALL invariants against real API state, not handcrafted dashboard numbers."""
import hashlib
import json
import secrets
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import pytest
from fastapi.testclient import TestClient
from app.demo import seed_realistic_demo, validated_target
from app.db import ROOT
from app.dbtools import snapshot
from app.main import app


@pytest.fixture(scope='module')
def demo_source(tmp_path_factory):
    folder=tmp_path_factory.mktemp('nightfall-fixture');target=folder/'nightfall-demo.sqlite'
    password=secrets.token_urlsafe(24)
    result=seed_realistic_demo(target,password,environment='demo',confirm='SIMULATED-DATA')
    return target,password,result


@pytest.fixture
def demo(demo_source,tmp_path,monkeypatch):
    source,password,manifest=demo_source;target=tmp_path/'copy-demo.sqlite';snapshot(source,target)
    monkeypatch.setenv('BAROS_DB',str(target));monkeypatch.setenv('BAROS_SECURE_COOKIE','0')
    clients={}
    def actor(username='nf_admin'):
        if username not in clients:
            c=TestClient(app);r=c.post('/api/login',json={'username':username,'password':password});assert r.status_code==200,r.text
            c.headers['X-CSRF-Token']=r.json()['csrf'];clients[username]=c
        return clients[username]
    yield target,password,manifest,actor
    for c in clients.values():c.close()


def test_demo_counts_integrity_and_repeat_is_noop(demo_source):
    path,password,m=demo_source;before=hashlib.sha256(path.read_bytes()).hexdigest()
    again=seed_realistic_demo(path,environment='demo',confirm='SIMULATED-DATA')
    assert again['unchanged'] and again['counts']==m['counts']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    for _ in range(2):
        cli=subprocess.run([sys.executable,'-X','utf8','-m','app.cli','seed-realistic-demo','--database',str(path),'--environment','demo','--confirm','SIMULATED-DATA'],cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf8')
        assert cli.returncode==0,cli.stderr
        assert json.loads(cli.stdout)['unchanged']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert m['counts']['users']==21 and 70<=m['counts']['documents']<=100
    assert m['counts']['inv_skus']==32 and m['counts']['flow_runs']==42
    assert m['counts']['modules']==9 and m['counts']['insight_reports']==2
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM users WHERE must_change_password=1').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM agent_tool_events WHERE outcome='succeeded'").fetchone()[0]==1


def test_import_fail_closed_and_rolls_back(tmp_path,monkeypatch):
    real=tmp_path/'customer.sqlite';real.write_bytes(b'existing customer content');before=real.read_bytes()
    with pytest.raises(ValueError):seed_realistic_demo(real,'password-123456789',environment='demo',confirm='SIMULATED-DATA')
    # Even a misleading filename never authorizes modifying an existing database.
    misleading=tmp_path/'customer-demo.sqlite';misleading.write_bytes(before)
    with pytest.raises(ValueError):seed_realistic_demo(misleading,'password-123456789',environment='demo',confirm='SIMULATED-DATA')
    assert real.read_bytes()==before and misleading.read_bytes()==before
    with pytest.raises(ValueError):validated_target(ROOT/'data'/'baros.sqlite','demo','SIMULATED-DATA')
    with pytest.raises(ValueError):validated_target(tmp_path/'safe-demo.sqlite','demo','yes')
    with pytest.raises(ValueError):validated_target('relative-demo.sqlite','demo','SIMULATED-DATA')
    target=tmp_path/'rollback-demo.sqlite';monkeypatch.setenv('BAROS_DB',str(real))
    with pytest.raises(RuntimeError,match='Injected'):seed_realistic_demo(target,secrets.token_urlsafe(20),environment='demo',confirm='SIMULATED-DATA',_fail_after='accounts')
    assert not target.exists() and real.read_bytes()==before
    logs=target.with_name(target.name+'.import-errors.jsonl').read_text()
    assert 'rolled_back' in logs and 'password' not in logs and not list(tmp_path.glob('baros-demo-build-*'))


def test_current_future_retired_feedback_and_scope(demo):
    path,password,m,actor=demo;s=m['stories'];admin=actor();staff=actor('nf_bar1');server=actor('nf_server1')
    items=staff.get('/api/knowledge?station=main').json()
    assert sum(k['kind']=='recipe' for k in items)>=20
    recipe=staff.get('/api/knowledge/'+str(s['recipe_document'])).json()
    assert recipe['revision_id']==s['recipe_v2'] and recipe['content']['ingredients'][0]['amount']=='55'
    assert staff.get('/api/citations/'+str(s['recipe_v1'])).status_code==404
    assert staff.get('/api/citations/'+str(s['recipe_future'])).status_code==404
    assert not any(k['kind']=='recipe' for k in server.get('/api/knowledge').json())
    assert actor('nf_new').get('/api/knowledge?station=vip').status_code==403
    assert actor('iso_admin').get('/api/knowledge/'+str(s['recipe_document'])).status_code==404
    assert staff.get('/api/knowledge',headers={'X-BarOS-Store':'isolation-lab'}).status_code==403
    assert actor('nf_rotating').get('/api/knowledge',headers={'X-BarOS-Store':'nf-riverside'}).status_code==403
    assert admin.get('/api/knowledge',headers={'X-BarOS-Store':'nf-riverside'}).status_code==200
    revisions=admin.get('/api/manage/revisions').json()
    assert any(r['state']=='retired' for r in revisions) and any(r['state']=='review' for r in revisions)
    memory=admin.get('/api/manage/memory').json();assert memory['health']['unowned'] and memory['health']['overdue']
    assert next(p for p in admin.get('/api/manage/proposals').json() if p['id']==s['proposal'])['state']=='closed'
    assert len(server.get('/api/service?station=main').json()['items'])>=20
    assert TestClient(app).get('/api/environment').json()['simulated']
    # A reusable, explicitly synthetic title/alias set for later retrieval comparisons.
    benchmark=json.loads((ROOT/'fixtures'/'nightfall_questions.json').read_text(encoding='utf8'))
    assert len(benchmark['cases'])==50 and not benchmark['real_venue_acceptance']
    all_stations=actor('nf_bar2')
    for case in benchmark['cases']:
        response=all_stations.post('/api/ask',json={'question':case['question'],'station':case['station']})
        assert response.status_code==200,response.text
        answer=response.json();assert answer['status']==case['expected_status'],case
        assert answer['sources'][0]['title']==case['expected_title'],case


def test_training_history_never_implies_real_qualification(demo):
    _,_,m,actor=demo;s=m['stories'];e=actor('nf_new').get('/api/academy/evidence').json()['items'][0]
    assert [x['score'] for x in e['attempts']]==[0,100,100]
    assert [bool(x['passed']) for x in e['reviews']]==[False,True]
    assert e['qualified'] and '模拟' in e['title']
    retry=actor('nf_retry').get('/api/academy/evidence').json()['items'][0]
    assert not retry['qualified'] and retry['status']=='practical' and not retry['reviews'][0]['passed']
    failed=actor('nf_failed').get('/api/training').json()[0];assert failed['best_score']==0 and failed['overdue']
    learning=actor('nf_learning').get('/api/training').json()[0];assert learning['best_score']==33
    idle=actor('nf_idle').get('/api/training').json()[0];assert idle['best_score'] is None
    records=actor('nf_bar1').get('/api/academy/evidence').json()['items']
    old=next(x for x in records if x['id']==s['old_assignment']);new=next(x for x in records if x['id']==s['new_assignment'])
    assert old['stale'] and not old['qualified'] and old['practical_at'] and new['qualified']


def test_cross_midnight_operations_and_computed_command(demo):
    path,_,m,actor=demo;s=m['stories'];a=actor();command=a.get('/api/manage/command').json()
    assert s['open_incident'] in [i['id'] for i in command['incidents']]
    assert s['closed_incident'] not in [i['id'] for i in command['incidents']]
    assert command['counts']['runs']==len(command['runs']) and command['counts']['training']==len(command['training'])
    assert command['counts']['overdue_training']>0 and command['pending_reviews']>0
    with closing(sqlite3.connect(path)) as db:
        runs=db.execute("SELECT business_date,created_at,closed_at FROM flow_runs WHERE kind='closing' AND state='closed'").fetchall()
        assert len(runs)==13
        for business,created,closed in runs:
            assert datetime.fromisoformat(created).astimezone(timezone(timedelta(hours=8))).date().isoformat()==business
            assert datetime.fromisoformat(closed).astimezone(timezone(timedelta(hours=8))).date().isoformat()==(datetime.fromisoformat(business)+timedelta(days=1)).date().isoformat()
        assert db.execute('SELECT COUNT(DISTINCT business_date) FROM flow_runs').fetchone()[0]==14


def test_inventory_independent_decimal_recalculation(demo,tmp_path):
    path,_,m,actor=demo;a=actor();s=m['stories'];saved=a.get('/api/insight/reports/'+str(s['report'])).json();inputs=saved['inputs'];result=saved['result']
    assert result['complete'],result['data_gaps']
    consumption={};cost=Decimal(0)
    for sale in inputs['sales']:
        for line in sale['consumption']:
            consumption[line['sku_id']]=consumption.get(line['sku_id'],0)+line['quantity_milli']
            # Independent formula in CNY, not the report calculator's numerator helper.
            cost+=Decimal(line['quantity_milli'])/1000*Decimal(line['cost_micro'])/1000000
    for code,quantity in m['expected']['consumption'].items():assert consumption.get(m['sku_ids'][code],0)==quantity*1000
    assert result['totals']['theoretical_material_cost']==str(cost.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    assert sum(x['net_revenue_fen'] for x in inputs['sales'])==m['expected']['recorded_revenue_fen']
    assert sum(x['produced_quantity'] for x in inputs['sales'])==m['expected']['produced']
    opening={x['sku_id']:x['quantity_milli'] for x in inputs['start']['lines']};closing={x['sku_id']:x['quantity_milli'] for x in inputs['end']['lines']}
    for row in result['inventory']:
        sid=row['sku_id'];balance=opening[sid]-consumption.get(sid,0)
        for move in inputs['movements']:
            if move['sku_id']==sid:balance+=move['quantity_milli']*(1 if move['kind'] in ('receipt','transfer_in') else -1)
        assert row['theoretical_closing_milli']==balance and row['variance_milli']==closing[sid]-balance
    gin=next(x for x in result['inventory'] if x['code']=='GIN');assert gin['variance_milli']==-180000 and gin['variance_value']=='-51.84'
    refund=[x for x in inputs['sales'] if 'REFUND' in x['external_key']];assert len(refund)==7 and all(x['produced_quantity']==0 and not x['consumption'] for x in refund)
    assert {x['revision_id'] for x in inputs['sales'] if x['product_code']=='NF01' and x['produced_quantity']}>={s['recipe_v1'],s['recipe_v2']}
    assert len({x['external_key'] for x in inputs['sales']})==len(inputs['sales'])
    assert all(c['counted_by']!=c['approved_by'] for c in [inputs['start'],inputs['end']])
    batches=sorted(inputs['batches'],key=lambda x:x['start_at']);assert all(x['end_at']==y['start_at'] for x,y in zip(batches,batches[1:]))
    catalog=a.get('/api/inventory/catalog').json();assert next(x for x in catalog['skus'] if x['code']=='GIN')['units']['瓶']=='750'
    target=tmp_path/'report.json';target.write_text(json.dumps(saved),encoding='utf8')
    standalone=subprocess.run([sys.executable,'-X','utf8','-m','app.report_math',str(target)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    assert standalone.returncode==0 and json.loads(standalone.stdout)['matches']
    gap=a.get('/api/insight/reports/'+str(s['gap_report'])).json()['result']
    assert not gap['complete'] and gap['totals']['theoretical_material_cost'] is None
    assert {'missing_product','missing_cost'}<={x['code'] for x in gap['data_gaps']}


def test_hq_signing_requires_local_publication(demo):
    _,_,m,actor=demo;a=actor();deliveries=a.get('/api/hq').json()['deliveries']
    by_store={x['store']:x for x in deliveries}
    assert by_store['nf-downtown']['state']=='accepted' and by_store['nf-downtown']['rollout']=='draft'
    assert by_store['nf-riverside']['rollout']=='effective'
    rid=by_store['nf-downtown']['local_revision_id']
    assert a.get('/api/citations/'+str(rid)).status_code==404
    assert all(d['difference_note'] for d in deliveries)
    assert actor('iso_admin').get('/api/hq/deliveries/'+str(deliveries[0]['id'])).status_code==404


def test_agent_repeat_and_changed_recipe_guard(demo):
    _,_,m,actor=demo;a=actor();s=m['stories']
    good=a.get('/api/agents/plans/'+str(s['good_plan'])).json();assert good['state']=='executed' and len(good['task_ids'])==7
    result=a.post('/api/agents/plans/'+str(s['good_plan'])+'/execute',json={'version':good['version'],'idempotency_key':'new-demo-retry-key'})
    assert result.status_code==200 and result.json()['task_ids']==good['task_ids']
    tasks=a.get('/api/tasks?station=main').json();assert len(tasks)==7 and sum(t['state']=='closed' for t in tasks)==2
    response=a.post('/api/agents/plans/'+str(s['stale_plan'])+'/execute',json={'version':s['stale_version'],'idempotency_key':'test-stale-plan-retry'})
    assert response.status_code==409 and len(a.get('/api/tasks?station=main').json())==7
    assert any(x['outcome']=='blocked' for x in a.get('/api/agents/tool-audit').json())


def test_no_demo_seed_on_application_start(tmp_path,monkeypatch):
    path=tmp_path/'empty.sqlite';monkeypatch.setenv('BAROS_DB',str(path))
    with TestClient(app) as c:
        assert c.get('/api/environment').json()=={'simulated':False}
    with closing(sqlite3.connect(path)) as db:assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0

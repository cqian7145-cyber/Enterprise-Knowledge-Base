import json
import sqlite3
import pytest
from test_baros import clients, create, publish
from app.db import connect, encode, initialize
from app.insight import calculate, digest

START='2026-10-01T00:00:00+00:00'
SOLD='2026-10-02T12:00:00+00:00'
END='2026-10-03T00:00:00+00:00'
OLD='2026-09-01T00:00:00+00:00'


def post(client,url,payload):
    r=client.post(url,json=payload)
    assert r.status_code==200,r.text
    return r.json()


def trusted_count(admin,staff,when,amounts):
    cid=post(staff,'/api/inventory/counts',{'station':'main','observed_at':when,'source':'门店实物盘点原始记录','evidence':'双人核对瓶身刻度与实际数量','lines':[{'sku_id':sid,'amount':amount,'unit':'ml'} for sid,amount in amounts.items()]})['id']
    post(admin,f'/api/inventory/counts/{cid}/review',{'approved':True,'note':'逐项复核原始记录和实物数量'})
    return cid


@pytest.fixture
def commerce(clients):
    admin,staff,outsider,server=clients
    gin=post(admin,'/api/inventory/skus',{'code':'GIN750','name':'金酒750ml','base_unit':'ml','units':[{'unit':'瓶','factor':'750'}]})['id']
    tonic=post(admin,'/api/inventory/skus',{'code':'TONIC200','name':'汤力水200ml','base_unit':'ml','units':[{'unit':'瓶','factor':'200'}]})['id']
    for sid,price in [(gin,'0.10'),(tonic,'0.02')]:
        post(admin,'/api/inventory/costs',{'sku_id':sid,'unit':'ml','price':price,'effective_at':OLD,'source':'历史采购单与商品规格核对'})
    with connect(True) as db:
        content=json.loads(db.execute('SELECT content FROM revisions WHERE id=1').fetchone()[0])
        did=db.execute("INSERT INTO documents(store,title,kind,jobs,stations,aliases,risk) VALUES('pilot','历史金汤力','recipe',?,?,?,0)",(encode(['bartender']),encode(['main']),encode([]))).lastrowid
        rid=db.execute("INSERT INTO revisions(document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(?,1,'published',?,'历史批准配方',?,1,1,?)",(did,encode(content),OLD,OLD)).lastrowid
    post(admin,'/api/inventory/products',{'code':'GT','name':'金汤力','document_id':did})
    mapping=post(admin,'/api/inventory/recipe-maps',{'revision_id':rid,'lines':[{'ingredient_index':0,'sku_id':gin},{'ingredient_index':1,'sku_id':tonic}],'source':'原料标签和历史配方逐项核对'})['id']
    opening=trusted_count(admin,staff,START,{gin:'1000',tonic:'2000'})
    closing=trusted_count(admin,staff,END,{gin:'640',tonic:'800'})
    return {'admin':admin,'staff':staff,'outsider':outsider,'server':server,'gin':gin,'tonic':tonic,'did':did,'rid':rid,'mapping':mapping,'opening':opening,'closing':closing}


def sale_row(key='S1',**changes):
    return {'external_key':key,'product_code':'GT','sold_at':SOLD,'quantity':10,'produced_quantity':10,'net_revenue':'300.00',**changes}


def batch(c,rows=None,**changes):
    return post(c['admin'],'/api/inventory/sales-batches',{'station':'main','start_at':START,'end_at':END,'source':'收银系统原始销售明细','external_key':'B1','is_complete':True,'coverage_note':'已核对该期间全部销售与退款来源','rows':rows if rows is not None else [sale_row()],**changes})


def report(c,**changes):
    return post(c['admin'],'/api/insight/reports',{'start_count_id':c['opening'],'end_count_id':c['closing'],'movements_complete':True,'completeness_note':'已核对全部采购报损和调拨记录',**changes})


def test_service_approval_scope_version_and_academy(clients):
    admin,staff,outsider,server=clients
    content={'summary':'顾客等待较久的服务标准','steps':['说明当前情况','必要时交由主管处理'],'service':{'context':'顾客反映等候时间过长','response':'请先表达理解并核对当前制作进度','escalation_trigger':'顾客持续不满或超出员工权限','escalation_contact':'当班主管'}}
    d,data=create(admin,title='等待客诉升级卡',kind='complaint_card',content=content,risk=True,aliases=['等候客诉'])
    assert staff.get('/api/service?station=main').json()['items']==[]
    assert publish(admin,d['id'],risk_confirmed=True).status_code==200
    s=staff.get('/api/service?station=main').json()['items'][0]
    assert s['kind']=='complaint_card' and s['content']['service']['escalation_contact']=='当班主管'
    assert outsider.get('/api/service?station=main').json()['items']==[]
    assert server.get('/api/service?station=main').json()['items']==[]
    answer=staff.post('/api/ask',json={'question':'等待客诉升级卡','station':'main'}).json()
    assert '升级至：当班主管' in answer['answer']
    mid=post(admin,'/api/manage/modules',{'title':'客诉情境培训','objective':'练习标准回应与主管升级','revision_ids':[d['id']],'quiz':[{'question':'何时升级','options':['超出权限时','自行承诺退款'],'answer':0}],'pass_score':100})['id']
    aid=post(admin,'/api/manage/assignments',{'module_id':mid,'user_id':2})['id']
    newer,_=create(admin,document_id=d['document_id'],**data)
    assert publish(admin,newer['id'],risk_confirmed=True).status_code==200
    assert staff.get(f'/api/training/{aid}').status_code==409
    assert staff.get('/api/service?station=main').json()['items'][0]['version']==2


def test_service_validation_edit_and_scenario(clients):
    admin,staff,*_=clients
    p={'title':'服务场景','kind':'service_scenario','jobs':['bartender'],'stations':['main'],'source':'主管确认培训要求','content':{'summary':'标准服务场景','steps':['先核对再回应']}}
    assert admin.post('/api/manage/drafts',json=p).status_code==422
    p['content']['service']={'context':'顾客询问未知配方情况','response':'先查有效标准再交由当班主管确认','practice_prompt':'模拟未知配方问题并按标准回应','assessment_points':['能定位当前有效标准','不自行猜测']}
    item=post(admin,'/api/manage/drafts',p)
    assert admin.post(f"/api/manage/revisions/{item['id']}/edit",json={'content':{**p['content'],'service':None},'source':'确认资料','edit_version':1}).status_code==422
    assert publish(admin,item['id']).status_code==200
    assert staff.get('/api/service?station=main').json()['items'][0]['content']['service']['assessment_points']


def test_units_costs_complete_maps_and_permissions(commerce):
    c=commerce;a=c['admin'];s=c['staff'];o=c['outsider']
    catalog=s.get('/api/inventory/catalog').json()
    assert 'costs' not in catalog and catalog['skus'][0]['units']['瓶']=='750'
    assert s.post('/api/inventory/skus',json={'code':'X','name':'X','base_unit':'ml'}).status_code==403
    assert a.post('/api/inventory/skus',json={'code':'BAD','name':'错误维度','base_unit':'ml','units':[{'unit':'kg','factor':'1'}]}).status_code==422
    assert a.post('/api/inventory/skus',json={'code':'GIN750','name':'重复','base_unit':'ml'}).status_code==409
    assert a.post('/api/inventory/costs',json={'sku_id':c['gin'],'unit':'ml','price':'NaN','effective_at':OLD,'source':'成本核对原始依据'}).status_code==422
    assert a.post('/api/inventory/costs',json={'sku_id':c['gin'],'unit':'ml','price':'1','effective_at':OLD,'source':'成本核对原始依据'}).status_code==409
    assert o.post('/api/inventory/costs',json={'sku_id':c['gin'],'unit':'ml','price':'1','effective_at':OLD,'source':'跨店禁止成本录入'}).status_code==404
    m={'station':'main','sku_id':c['gin'],'kind':'receipt','amount':'1','unit':'杯','occurred_at':SOLD,'source':'采购入库单原始记录','external_key':'R-bad'}
    assert a.post('/api/inventory/movements',json=m).status_code==422
    m.update(unit='瓶',external_key='R-bottle')
    post(a,'/api/inventory/movements',m)
    assert a.get('/api/inventory/movements?station=main').json()[0]['quantity_milli']==750000
    assert a.post('/api/inventory/movements',json=m).status_code==409
    assert s.get('/api/inventory/movements?station=main').status_code==403
    assert o.get('/api/inventory/counts?station=main').json()==[]
    assert c['staff'].get('/api/inventory/counts?station=terrace').status_code==403


def test_trusted_count_requires_full_coverage_and_other_reviewer(commerce):
    c=commerce;a=c['admin'];s=c['staff']
    data={'station':'main','observed_at':SOLD,'source':'实盘原始记录单据','evidence':'现场核对数量及标签刻度','lines':[{'sku_id':c['gin'],'amount':'1','unit':'ml'}]}
    assert s.post('/api/inventory/counts',json=data).status_code==422
    data['lines'].append({'sku_id':c['tonic'],'amount':'0','unit':'ml'})
    cid=post(a,'/api/inventory/counts',data)['id']
    assert a.post(f'/api/inventory/counts/{cid}/review',json={'approved':True,'note':'自己不能确认自己的盘点'}).status_code==403
    assert s.post(f'/api/inventory/counts/{cid}/review',json={'approved':True,'note':'员工不能复核正式盘点'}).status_code==403
    assert a.post(f"/api/inventory/counts/{c['opening']}/review",json={'approved':False,'note':'已复核的记录不可再覆盖'}).status_code==409
    with connect(True) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE inv_counts SET evidence=? WHERE id=?',('覆盖历史证据',c['opening']))


def test_reproducible_sales_cost_and_count_variance(commerce):
    c=commerce;a=c['admin']
    for key,kind,amount in [('R1','receipt','100'),('W1','waste','5')]:
        post(a,'/api/inventory/movements',{'station':'main','sku_id':c['gin'],'kind':kind,'amount':amount,'unit':'ml','occurred_at':SOLD,'source':'采购或报损原始单据','external_key':key})
    batch(c)
    r=report(c);x=r['result']
    assert x['complete'] is True and x['totals']['recorded_net_revenue']=='300.00'
    assert x['totals']['theoretical_material_cost']=='69.00' and x['totals']['material_contribution']=='231.00'
    gin=next(i for i in x['inventory'] if i['sku_id']==c['gin'])
    assert gin['theoretical_consumption_milli']==450000 and gin['theoretical_closing_milli']==645000
    assert gin['variance_milli']==-5000 and gin['variance_value']=='-0.50'
    saved=a.get(f"/api/insight/reports/{r['id']}").json()
    assert digest(saved['inputs'])==r['input_hash'] and calculate(saved['inputs'])==saved['result']
    check=post(a,f"/api/insight/reports/{r['id']}/recalculate",{})
    assert check['matches'] and check['input_intact'] and check['saved_result_intact']
    assert c['staff'].get('/api/insight/reports?station=main').status_code==403
    assert c['outsider'].get(f"/api/insight/reports/{r['id']}").status_code==404
    with connect(True) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE insight_reports SET result=? WHERE id=?',('{}',r['id']))


def test_refunds_do_not_restore_consumed_materials(commerce):
    c=commerce
    batch(c,[sale_row(),sale_row('REF1',quantity=-1,produced_quantity=0,net_revenue='-30.00')])
    x=report(c)['result']
    assert x['totals']['quantity']==9 and x['totals']['produced_quantity']==10
    assert x['totals']['recorded_net_revenue']=='270.00' and x['totals']['theoretical_material_cost']=='69.00'
    assert next(i for i in x['inventory'] if i['sku_id']==c['gin'])['theoretical_consumption_milli']==450000


def test_missing_sources_mapping_cost_and_late_reconciliation(commerce):
    c=commerce;a=c['admin']
    missing=report(c,movements_complete=False)['result']
    assert not missing['complete'] and {g['code'] for g in missing['data_gaps']}=={'sales_coverage','movement_coverage'}
    batch(c,[sale_row(product_code='NEW')])
    old=report(c);assert old['result']['totals']['theoretical_material_cost'] is None
    assert old['result']['mapping_complete'] is False
    post(a,'/api/inventory/products',{'code':'NEW','name':'新编码商品','document_id':c['did']})
    sale=a.get('/api/inventory/sales?station=main').json()[0]
    post(a,f"/api/inventory/sales/{sale['id']}/reconcile",{})
    assert report(c)['result']['totals']['theoretical_material_cost']=='69.00'
    assert a.get(f"/api/insight/reports/{old['id']}").json()['result']['totals']['theoretical_material_cost'] is None
    assert post(a,f"/api/insight/reports/{old['id']}/recalculate",{})['matches']


def test_missing_historical_cost_is_not_zero(commerce):
    c=commerce;a=c['admin']
    # A new exact recipe SKU has no effective cost yet.
    newsku=post(a,'/api/inventory/skus',{'code':'GIN-NOCOST','name':'无历史价格金酒','base_unit':'ml'})['id']
    with connect(True) as db:
        content=json.loads(db.execute('SELECT content FROM revisions WHERE id=?',(c['rid'],)).fetchone()[0]);content['ingredients'][0]['amount']='50'
        rid=db.execute("INSERT INTO revisions(document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(?,2,'published',?,'批准的历史新版',?,1,1,?)",(c['did'],encode(content),START,OLD)).lastrowid
    post(a,'/api/inventory/recipe-maps',{'revision_id':rid,'lines':[{'ingredient_index':0,'sku_id':newsku},{'ingredient_index':1,'sku_id':c['tonic']}],'source':'新配方原料规格逐项核对'})
    batch(c)
    old=report(c)
    assert old['result']['cost_complete'] is False and old['result']['totals']['theoretical_material_cost'] is None
    assert any(g['code']=='count_coverage' for g in old['result']['data_gaps'])
    post(a,'/api/inventory/costs',{'sku_id':newsku,'unit':'ml','price':'0.10','effective_at':OLD,'source':'补录经核对的历史采购价格'})
    sid=a.get('/api/inventory/sales?station=main').json()[0]['id']
    post(a,f'/api/inventory/sales/{sid}/reconcile',{})
    assert report(c)['result']['totals']['theoretical_material_cost']=='74.00'
    assert post(a,f"/api/insight/reports/{old['id']}/recalculate",{})['matches']


def test_historical_recipe_selection_uses_sale_time(commerce):
    c=commerce;a=c['admin']
    with connect(True) as db:
        content=json.loads(db.execute('SELECT content FROM revisions WHERE id=?',(c['rid'],)).fetchone()[0]);content['ingredients'][0]['amount']='60'
        rid=db.execute("INSERT INTO revisions(document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(?,2,'published',?,'批准历史新版配方','2026-10-02T00:00:00+00:00',1,1,?)",(c['did'],encode(content),OLD)).lastrowid
    post(a,'/api/inventory/recipe-maps',{'revision_id':rid,'lines':[{'ingredient_index':0,'sku_id':c['gin']},{'ingredient_index':1,'sku_id':c['tonic']}],'source':'历史新版配方逐项映射确认'})
    batch(c,[sale_row('BEFORE',sold_at='2026-10-01T12:00:00+00:00',quantity=1,produced_quantity=1,net_revenue='30'),sale_row('AFTER',quantity=1,produced_quantity=1,net_revenue='30')])
    sales={s['external_key']:s for s in a.get('/api/inventory/sales?station=main').json()}
    assert sales['BEFORE']['revision_id']==c['rid'] and sales['AFTER']['revision_id']==rid
    assert report(c)['result']['totals']['theoretical_material_cost']=='15.30'


def test_substitution_requires_explicit_historical_approval(commerce,monkeypatch):
    c=commerce;a=c['admin']
    target=post(a,'/api/inventory/skus',{'code':'GIN-ALT','name':'替代金酒','base_unit':'ml'})['id']
    post(a,'/api/inventory/costs',{'sku_id':target,'unit':'ml','price':'0.20','effective_at':OLD,'source':'替代商品历史采购单价'})
    p={'recipe_map_id':c['mapping'],'from_sku_id':c['gin'],'to_sku_id':target,'ratio':'1','reason':'经门店负责人确认本配方可替代','safety_note':'已核对实际标签及过敏原标识','safety_confirmed':False,'effective_at':OLD}
    assert a.post('/api/inventory/substitutions',json=p).status_code==422
    p['safety_confirmed']=True
    with monkeypatch.context() as patch:
        patch.setattr('app.inventory.now',lambda:OLD)
        sid=post(a,'/api/inventory/substitutions',p)['id']
    batch(c,[sale_row(substitution_ids=[sid])])
    sale=a.get('/api/inventory/sales?station=main').json()[0]
    assert sale['consumption'][0]['sku_id']==target and sale['consumption'][0]['substitution_id']==sid
    assert report(c)['result']['totals']['theoretical_material_cost']=='114.00'
    post(a,f'/api/inventory/substitutions/{sid}/revoke',{'reason':'更换供应批次后暂停此项批准'})
    assert a.get('/api/inventory/substitutions?station=main').json()[0]['active'] is False
    # Revocation never silently rewrites the consumption already recorded.
    assert a.get('/api/inventory/sales?station=main').json()[0]['consumption'][0]['sku_id']==target


def test_duplicate_overlap_atomicity_void_and_saved_report(commerce):
    c=commerce;a=c['admin']
    b=batch(c)
    payload={'station':'main','start_at':START,'end_at':END,'source':'收银销售原始来源','external_key':'B2','is_complete':True,'coverage_note':'已经核对该期间全部来源','rows':[]}
    assert a.post('/api/inventory/sales-batches',json=payload).status_code==409
    old=report(c)
    post(a,f"/api/inventory/sales-batches/{b['id']}/void",{'reason':'原始销售来源有误，保留审计后重录'})
    assert not report(c)['result']['sales_coverage_complete']
    assert post(a,f"/api/insight/reports/{old['id']}/recalculate",{})['matches']
    payload['rows']=[sale_row('new-row'),sale_row('new-row')]
    assert a.post('/api/inventory/sales-batches',json=payload).status_code==409
    assert len(a.get('/api/inventory/sales-batches?station=main').json())==1
    assert a.post('/api/inventory/sales-batches',json={**payload,'rows':[sale_row('bad-date',sold_at=START)]}).status_code==422


def test_boundaries_csrf_and_schema_repeatability(commerce):
    c=commerce;a=c['admin'];s=c['staff'];o=c['outsider']
    token=a.headers.pop('X-CSRF-Token')
    assert a.post('/api/inventory/skus',json={'code':'X','name':'X','base_unit':'ml'}).status_code==403
    assert a.post('/api/insight/reports',json={'start_count_id':c['opening'],'end_count_id':c['closing'],'movements_complete':True,'completeness_note':'完整来源已核对'}).status_code==403
    a.headers['X-CSRF-Token']=token
    assert o.post('/api/insight/reports',json={'start_count_id':c['opening'],'end_count_id':c['closing'],'movements_complete':True,'completeness_note':'禁止读取其他门店盘点'}).status_code==404
    assert a.post('/api/insight/reports',json={'start_count_id':c['closing'],'end_count_id':c['opening'],'movements_complete':True,'completeness_note':'结束不能早于开始时刻'}).status_code==422
    initialize();initialize()
    with connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM inv_counts').fetchone()[0]==2


def test_explicit_zero_sales_and_incomplete_source_coverage(commerce):
    c=commerce
    batch(c,[],is_complete=False)
    partial=report(c)['result']
    assert partial['totals']['recorded_net_revenue']=='0.00' and not partial['sales_coverage_complete']
    bid=c['admin'].get('/api/inventory/sales-batches?station=main').json()[0]['id']
    post(c['admin'],f'/api/inventory/sales-batches/{bid}/void',{'reason':'补充完整核对后重新声明零销量'})
    batch(c,[],external_key='ZERO-COMPLETE')
    result=report(c)['result']
    assert result['sales_coverage_complete'] and result['totals']['theoretical_material_cost']=='0.00'


def test_unit_precision_blank_sources_and_unapproved_recipe(commerce):
    c=commerce;a=c['admin']
    p={'station':'main','sku_id':c['gin'],'kind':'receipt','amount':'0.0001','unit':'ml','occurred_at':SOLD,'source':'采购单原始记录核对','external_key':'PRECISION'}
    assert a.post('/api/inventory/movements',json=p).status_code==422
    assert a.post('/api/inventory/movements',json={**p,'amount':'1','source':'    x'}).status_code==422
    draft,_=create(a,title='未批准配方',kind='recipe',content={'summary':'草稿配方','ingredients':[{'name':'金酒','amount':'45','unit':'ml'}],'technique':'兑和','glass':'高球杯','steps':['量取原料']})
    assert a.post('/api/inventory/recipe-maps',json={'revision_id':draft['id'],'lines':[{'ingredient_index':0,'sku_id':c['gin']}],'source':'草稿配方不允许进入库存依据'}).status_code==422
    assert a.post('/api/inventory/recipe-maps',json={'revision_id':c['rid'],'lines':[{'ingredient_index':0,'sku_id':c['gin']}],'source':'不能遗漏配方原料映射'}).status_code==422


def test_saved_cost_reference_not_overwritten_by_late_cost(commerce):
    c=commerce;a=c['admin']
    batch(c)
    before=report(c)
    post(a,'/api/inventory/costs',{'sku_id':c['gin'],'unit':'ml','price':'0.50','effective_at':START,'source':'后录入的历史采购价格资料'})
    sale=a.get('/api/inventory/sales?station=main').json()[0]
    assert a.post(f"/api/inventory/sales/{sale['id']}/reconcile",json={}).status_code==409
    assert sale['consumption'][0]['cost_micro']==100000
    assert report(c)['result']['totals']['theoretical_material_cost']=='69.00'
    assert post(a,f"/api/insight/reports/{before['id']}/recalculate",{})['matches']


def test_refund_service_card_requires_explicit_approved_content(clients):
    admin,staff,*_=clients
    assert staff.post('/api/ask',json={'question':'退款怎么处理','station':'main'}).json()['resolved'] is False
    content={'summary':'退款诉求需交由主管核对','steps':['记录诉求','联系主管'],'service':{'context':'顾客向员工提出退款要求','response':'我会请当班主管核对订单与门店规则后回复您','escalation_trigger':'涉及退款、赔付或超出员工权限','escalation_contact':'当班主管'}}
    d,_=create(admin,title='退款客诉升级卡',kind='complaint_card',aliases=['退款'],content=content,risk=True)
    assert publish(admin,d['id'],risk_confirmed=True).status_code==200
    result=staff.post('/api/ask',json={'question':'退款怎么处理','station':'main'}).json()
    assert result['resolved'] and '当班主管' in result['answer']


def test_export_can_be_recalculated_without_api_or_database(commerce,tmp_path):
    import subprocess
    import sys
    from app.db import ROOT
    c=commerce
    batch(c)
    created=report(c)
    exported=c['admin'].get(f"/api/insight/reports/{created['id']}").json()
    target=tmp_path/'report.json'
    target.write_text(json.dumps(exported),encoding='utf8')
    result=subprocess.run([sys.executable,'-m','app.report_math',str(target)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    assert result.returncode==0,result.stderr
    calculated=json.loads(result.stdout)
    assert calculated['matches'] and calculated['input_intact'] and calculated['saved_result_intact']
    assert calculated['result']==exported['result']
    exported['inputs']['sales'][0]['net_revenue_fen']+=1
    target.write_text(json.dumps(exported),encoding='utf8')
    tampered=subprocess.run([sys.executable,'-m','app.report_math',str(target)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    assert tampered.returncode==1
    assert json.loads(tampered.stdout)['input_intact'] is False

"""Deterministic material-cost and count-variance reports with frozen input evidence."""
import json
from fastapi import APIRouter, Depends
from pydantic import Field
from .db import audit, connect, encode, now
from .main import manager, fail
from .inventory import CleanInput, own_record
from .operations import station_allowed

router=APIRouter()
from .report_math import FORMULA_VERSION, calculate, canonical, digest


class ReportIn(CleanInput):
    start_count_id: int
    end_count_id: int
    movements_complete: bool
    completeness_note: str = Field(min_length=5,max_length=1000)




def gather(db,data,user):
    start=own_record(db,'inv_counts',data.start_count_id,user,True);end=own_record(db,'inv_counts',data.end_count_id,user,True)
    if start['state']!='approved' or end['state']!='approved' or start['station']!=end['station'] or start['observed_at']>=end['observed_at']:
        fail(422,'须选择同一吧台、时刻递增且经另一位主管复核的两次可信盘点')
    station=start['station'];params=(user['store'],station,start['observed_at'],end['observed_at'])
    sales=[]
    for row in db.execute('SELECT s.* FROM inv_sales s JOIN inv_sales_batches b ON b.id=s.batch_id WHERE s.store=? AND s.station=? AND s.sold_at>? AND s.sold_at<=? AND b.voided_at IS NULL ORDER BY s.id',params):
        sales.append({**dict(row),'consumption':json.loads(row['consumption']),'issues':json.loads(row['issues'])})
    inputs={'formula_version':FORMULA_VERSION,'station':station,'start':{**dict(start),'lines':json.loads(start['lines'])},'end':{**dict(end),'lines':json.loads(end['lines'])},'skus':[dict(r) for r in db.execute('SELECT * FROM inv_skus WHERE store=? ORDER BY id',(user['store'],))],'sales':sales,'movements':[dict(r) for r in db.execute('SELECT * FROM inv_movements WHERE store=? AND station=? AND occurred_at>? AND occurred_at<=? AND voided_at IS NULL ORDER BY id',params)],'batches':[dict(r) for r in db.execute('SELECT * FROM inv_sales_batches WHERE store=? AND station=? AND end_at>? AND start_at<? AND voided_at IS NULL ORDER BY start_at,id',params)],'movements_complete':data.movements_complete,'completeness_note':data.completeness_note}
    inputs['valuation_costs']=[]
    for sku in inputs['skus']:
        cost=db.execute('SELECT * FROM inv_costs WHERE store=? AND sku_id=? AND effective_at<=? ORDER BY effective_at DESC,id DESC LIMIT 1',(user['store'],sku['id'],end['observed_at'])).fetchone()
        if cost:inputs['valuation_costs'].append(dict(cost))
    inputs['recipe_maps']=[dict(r) for r in db.execute('SELECT * FROM inv_recipe_maps WHERE store=? ORDER BY id',(user['store'],)) if r['id'] in {s['recipe_map_id'] for s in sales}]
    inputs['revisions']=[dict(r) for r in db.execute('SELECT * FROM revisions WHERE id IN (SELECT r.id FROM revisions r JOIN documents d ON d.id=r.document_id WHERE d.store=?)',(user['store'],)) if r['id'] in {s['revision_id'] for s in sales}]
    cost_ids={line['cost_id'] for s in sales for line in s['consumption'] if line['cost_id']}
    inputs['costs']=[dict(r) for r in db.execute('SELECT * FROM inv_costs WHERE store=? ORDER BY id',(user['store'],)) if r['id'] in cost_ids]
    sub_ids={line['substitution_id'] for s in sales for line in s['consumption'] if line['substitution_id']}
    inputs['substitutions']=[dict(r) for r in db.execute('SELECT * FROM inv_substitutions WHERE store=? ORDER BY id',(user['store'],)) if r['id'] in sub_ids]
    return inputs


@router.post('/api/insight/reports')
def create_report(data: ReportIn,user=Depends(manager)):
    with connect(True) as db:
        inputs=gather(db,data,user);result=calculate(inputs)
        rid=db.execute('INSERT INTO insight_reports(store,station,start_count_id,end_count_id,inputs,result,input_hash,result_hash,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(user['store'],inputs['station'],data.start_count_id,data.end_count_id,canonical(inputs),canonical(result),digest(inputs),digest(result),user['id'],now())).lastrowid
        audit(db,user,'insight_report_saved',rid)
    return {'id':rid,'result':result,'input_hash':digest(inputs),'result_hash':digest(result)}


@router.get('/api/insight/reports')
def reports(station: str,user=Depends(manager)):
    station_allowed(user,station)
    with connect() as db:
        return [{**dict(r),'result':json.loads(r['result'])} for r in db.execute('SELECT id,station,start_count_id,end_count_id,result,input_hash,result_hash,created_by,created_at FROM insight_reports WHERE store=? AND station=? ORDER BY id DESC LIMIT 200',(user['store'],station))]


@router.get('/api/insight/reports/{rid}')
def report(rid: int,user=Depends(manager)):
    with connect() as db:
        r=own_record(db,'insight_reports',rid,user,True)
        return {**dict(r),'inputs':json.loads(r['inputs']),'result':json.loads(r['result'])}


@router.post('/api/insight/reports/{rid}/recalculate')
def recalculate(rid: int,user=Depends(manager)):
    with connect() as db:
        row=own_record(db,'insight_reports',rid,user,True)
        inputs=json.loads(row['inputs']);saved=json.loads(row['result']);result=calculate(inputs)
        return {'id':rid,'input_intact':digest(inputs)==row['input_hash'],'saved_result_intact':digest(saved)==row['result_hash'],'matches':digest(result)==row['result_hash'],'result':result,'input_hash':digest(inputs),'result_hash':digest(result),'basis':'按保存时的原始输入和公式版本重算，不读取后来变更的业务记录。'}

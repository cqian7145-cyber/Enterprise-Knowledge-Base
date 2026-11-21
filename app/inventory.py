"""Explicit stock facts: SKU units, historical recipes, reviewed counts and production."""
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from .db import audit, connect, encode, now
from .main import Input, fail, identity, manager, normalized_date, get_revision, scope
from .operations import station_allowed

router = APIRouter()


class CleanInput(Input):
    @field_validator('*', mode='before')
    @classmethod
    def trim(cls,value):
        if isinstance(value,str):
            value=value.strip()
            if not value:
                raise ValueError('字段不能为空')
        return value


def decimal_value(value,negative=False):
    if not re.fullmatch(r'-?\d{1,12}(\.\d{1,6})?',value):
        fail(422,'数量或金额须为普通十进制字符串，最多6位小数')
    number=Decimal(value)
    if number<0 and not negative:
        fail(422,'数量或金额不能为负数')
    return number


def scaled(value,scale,negative=False):
    raw=decimal_value(value,negative)*scale
    if raw != raw.to_integral_value():
        fail(422,'数量或金额精度超出支持范围')
    if abs(raw)>10**15:
        fail(422,'数值过大')
    return int(raw)


def at(value):
    result=normalized_date(value)
    if result>now():
        fail(422,'业务记录时间不能晚于当前时间')
    return result


def own_record(db,table,rid,user,station=False):
    row=db.execute('SELECT * FROM '+table+' WHERE id=? AND store=?',(rid,user['store'])).fetchone()
    if not row:
        fail(404,'记录不存在')
    if station:
        station_allowed(user,row['station'])
    return row


def quantity(db,sku_id,amount,unit,user):
    sku=own_record(db,'inv_skus',sku_id,user)
    units=json.loads(sku['units'])
    if unit not in units:
        fail(422,'该SKU未定义此单位换算，禁止猜测换算比例')
    raw=decimal_value(amount)*Decimal(units[unit])*1000
    if raw != raw.to_integral_value() or raw>10**15:
        fail(422,'换算结果须精确到0.001个基础单位，且不能超过数值范围')
    return int(raw),sku


class Unit(CleanInput):
    unit: str = Field(min_length=1,max_length=20)
    factor: str = Field(min_length=1,max_length=24)


class Sku(CleanInput):
    code: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    name: str = Field(min_length=1,max_length=120)
    base_unit: Literal['ml','g','个']
    units: list[Unit] = Field(default_factory=list,max_length=12)


class Cost(CleanInput):
    sku_id: int
    unit: str = Field(min_length=1,max_length=20)
    price: str = Field(min_length=1,max_length=24)
    effective_at: str
    source: str = Field(min_length=5,max_length=1000)


class Product(CleanInput):
    code: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    name: str = Field(min_length=1,max_length=120)
    document_id: int


class MapLine(Input):
    ingredient_index: int = Field(ge=0,le=29)
    sku_id: int


class RecipeMap(CleanInput):
    revision_id: int
    lines: list[MapLine] = Field(min_length=1,max_length=30)
    source: str = Field(min_length=5,max_length=1000)


class Substitute(CleanInput):
    recipe_map_id: int
    from_sku_id: int
    to_sku_id: int
    ratio: str
    reason: str = Field(min_length=5,max_length=1000)
    safety_note: str = Field(min_length=5,max_length=1000)
    safety_confirmed: bool
    effective_at: str
    expires_at: str | None = None


class CountLine(CleanInput):
    sku_id: int
    amount: str
    unit: str = Field(min_length=1,max_length=20)


class Count(CleanInput):
    station: str
    observed_at: str
    source: str = Field(min_length=5,max_length=1000)
    evidence: str = Field(min_length=5,max_length=2000)
    lines: list[CountLine] = Field(min_length=1,max_length=300)


class Decision(CleanInput):
    approved: bool
    note: str = Field(min_length=5,max_length=1000)


class Movement(CleanInput):
    station: str
    sku_id: int
    kind: Literal['receipt','waste','transfer_in','transfer_out']
    amount: str
    unit: str = Field(min_length=1,max_length=20)
    occurred_at: str
    source: str = Field(min_length=5,max_length=1000)
    external_key: str = Field(min_length=1,max_length=120)


class Void(CleanInput):
    reason: str = Field(min_length=5,max_length=1000)


class Sale(CleanInput):
    external_key: str = Field(min_length=1,max_length=120)
    product_code: str = Field(min_length=1,max_length=80)
    sold_at: str
    quantity: int = Field(ge=-1000000,le=1000000)
    produced_quantity: int = Field(ge=0,le=1000000)
    net_revenue: str
    substitution_ids: list[int] = Field(default_factory=list,max_length=30)


class SalesBatch(CleanInput):
    station: str
    start_at: str
    end_at: str
    source: str = Field(min_length=5,max_length=1000)
    external_key: str = Field(min_length=1,max_length=120)
    is_complete: bool
    coverage_note: str = Field(min_length=5,max_length=1000)
    rows: list[Sale] = Field(max_length=200)


def revision_at(db,did,when):
    rev=db.execute('SELECT * FROM revisions WHERE document_id=? AND approved_at IS NOT NULL AND approved_at<=? AND effective_at<=? ORDER BY version DESC LIMIT 1',(did,when,when)).fetchone()
    if not rev or rev['expires_at'] and rev['expires_at']<=when:
        return None
    if rev['state']=='retired':
        retired=db.execute("SELECT created_at FROM audit WHERE action='retired' AND target=? ORDER BY id LIMIT 1",(str(rev['id']),)).fetchone()
        if not retired or retired['created_at']<=when:
            return None
    return rev


def resolve_sale(db,sale,user):
    # Already produced units are independent of refunds and net sales quantity.
    if not sale['produced_quantity']:
        return {'revision_id':None,'recipe_map_id':None,'mapping_state':'ready','consumption':[],'issues':[]}
    product=db.execute('SELECT * FROM inv_products WHERE code=? AND store=?',(sale['product_code'],user['store'])).fetchone()
    state='missing_product'
    rev=mapping=None
    if product:
        doc=db.execute('SELECT * FROM documents WHERE id=?',(product['document_id'],)).fetchone()
        if not scope(doc,user,sale['station']):
            fail(403,'销售商品的历史配方不在当前岗位或吧台权限内')
        rev=revision_at(db,product['document_id'],sale['sold_at'])
        state='missing_history'
        if rev:
            mapping=db.execute('SELECT * FROM inv_recipe_maps WHERE revision_id=? AND store=?',(rev['id'],user['store'])).fetchone()
            state='missing_recipe_map'
    if not mapping:
        return {'revision_id':rev['id'] if rev else None,'recipe_map_id':None,'mapping_state':state,'consumption':[],'issues':[state]}
    subs={}
    if len(set(sale['substitution_ids']))!=len(sale['substitution_ids']):
        fail(422,'替代批准不能重复')
    for sid in sale['substitution_ids']:
        sub=own_record(db,'inv_substitutions',sid,user)
        when=sale['sold_at']
        if sub['recipe_map_id']!=mapping['id'] or sub['created_at']>when or sub['effective_at']>when or sub['expires_at'] and sub['expires_at']<=when or sub['revoked_at'] and sub['revoked_at']<=when:
            fail(409,'替代批准不适用该配方版本或销售时刻')
        if sub['from_sku_id'] in subs:
            fail(422,'同一原料只能指定一个替代批准')
        subs[sub['from_sku_id']]=sub
    lines=[]
    issues=[]
    for original in json.loads(mapping['lines']):
        sku_id=original['sku_id'];qty=original['quantity_milli']*sale['produced_quantity'];sub=subs.get(sku_id)
        if sub:
            converted=Decimal(qty)*sub['ratio_milli']/1000
            if converted!=converted.to_integral_value():
                fail(422,'批准替代的换算结果超出0.001基础单位精度')
            qty=int(converted);sku_id=sub['to_sku_id']
        cost=db.execute('SELECT * FROM inv_costs WHERE sku_id=? AND store=? AND effective_at<=? ORDER BY effective_at DESC,id DESC LIMIT 1',(sku_id,user['store'],sale['sold_at'])).fetchone()
        if not cost:
            issues.append('missing_cost:'+str(sku_id))
        if qty>10**15:
            fail(422,'制作数量换算后的原料消耗超出范围')
        lines.append({'sku_id':sku_id,'quantity_milli':qty,'cost_id':cost['id'] if cost else None,'cost_micro':cost['cost_micro'] if cost else None,'ingredient_index':original['ingredient_index'],'substitution_id':sub['id'] if sub else None})
    return {'revision_id':rev['id'],'recipe_map_id':mapping['id'],'mapping_state':'ready','consumption':lines,'issues':issues}


@router.get('/api/inventory/catalog')
def catalog(user=Depends(identity)):
    with connect() as db:
        result={'skus':[{**dict(r),'units':json.loads(r['units'])} for r in db.execute('SELECT * FROM inv_skus WHERE store=? ORDER BY id',(user['store'],))]}
        result['products']=[dict(r) for r in db.execute('SELECT p.*,d.title FROM inv_products p JOIN documents d ON d.id=p.document_id WHERE p.store=? ORDER BY p.id',(user['store'],)) if scope(db.execute('SELECT * FROM documents WHERE id=?',(r['document_id'],)).fetchone(),user)]
        result['recipe_maps']=[]
        for r in db.execute('SELECT m.*,r.version,d.title,r.document_id FROM inv_recipe_maps m JOIN revisions r ON r.id=m.revision_id JOIN documents d ON d.id=r.document_id WHERE m.store=? ORDER BY m.id DESC',(user['store'],)):
            if scope(db.execute('SELECT * FROM documents WHERE id=?',(r['document_id'],)).fetchone(),user):
                result['recipe_maps'].append({**dict(r),'lines':json.loads(r['lines'])})
        if user['role']!='staff':
            result['costs']=[dict(r) for r in db.execute('SELECT * FROM inv_costs WHERE store=? ORDER BY effective_at DESC,id DESC',(user['store'],))]
        return result


@router.post('/api/inventory/skus')
def create_sku(data: Sku,user=Depends(manager)):
    units={data.base_unit:'1'}
    if data.base_unit=='ml':units['L']='1000'
    if data.base_unit=='g':units['kg']='1000'
    for u in data.units:
        if u.unit in units or u.unit in ('ml','L','g','kg','个'):
            fail(422,'基础或标准单位不能覆盖，也不能跨维度换算')
        factor=decimal_value(u.factor)
        if factor<=0 or factor>10**6:
            fail(422,'单位换算系数须大于0且不超过1000000')
        units[u.unit]=str(factor)
    with connect(True) as db:
        if db.execute('SELECT 1 FROM inv_skus WHERE store=? AND code=?',(user['store'],data.code)).fetchone():
            fail(409,'SKU编码已存在，单位定义不可覆盖')
        rid=db.execute('INSERT INTO inv_skus(store,code,name,base_unit,units,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(user['store'],data.code,data.name,data.base_unit,encode(units),user['id'],now())).lastrowid
        audit(db,user,'sku_created',rid)
    return {'id':rid}


@router.post('/api/inventory/costs')
def create_cost(data: Cost,user=Depends(manager)):
    effective=at(data.effective_at)
    with connect(True) as db:
        _,sku=quantity(db,data.sku_id,'1',data.unit,user)
        price=decimal_value(data.price)
        value=int((price/Decimal(json.loads(sku['units'])[data.unit])*1000000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        if value>10**12:
            fail(422,'单价超出范围')
        if db.execute('SELECT 1 FROM inv_costs WHERE sku_id=? AND effective_at=?',(data.sku_id,effective)).fetchone():
            fail(409,'该时刻已有成本，历史成本不可覆盖')
        rid=db.execute('INSERT INTO inv_costs(store,sku_id,effective_at,cost_micro,source,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(user['store'],data.sku_id,effective,value,data.source,user['id'],now())).lastrowid
        audit(db,user,'cost_recorded',rid)
    return {'id':rid,'cost_micro':value,'basis':'每基础单位人民币，精确到0.000001元，四舍五入'}


@router.post('/api/inventory/products')
def create_product(data: Product,user=Depends(manager)):
    with connect(True) as db:
        doc=db.execute('SELECT * FROM documents WHERE id=? AND store=?',(data.document_id,user['store'])).fetchone()
        if not doc or doc['kind']!='recipe' or not scope(doc,user):
            fail(422,'商品必须映射到已授权的配方系列')
        if db.execute('SELECT 1 FROM inv_products WHERE store=? AND code=?',(user['store'],data.code)).fetchone():
            fail(409,'商品编码已映射，不可覆盖历史映射；更换配方系列请使用新编码')
        rid=db.execute('INSERT INTO inv_products(store,code,name,document_id,created_by,created_at) VALUES(?,?,?,?,?,?)',(user['store'],data.code,data.name,data.document_id,user['id'],now())).lastrowid
        audit(db,user,'product_mapped',rid)
    return {'id':rid}


@router.post('/api/inventory/recipe-maps')
def map_recipe(data: RecipeMap,user=Depends(manager)):
    with connect(True) as db:
        doc,rev=get_revision(db,data.revision_id,user)
        if doc['kind']!='recipe' or not rev['approved_at'] or not scope(doc,user):
            fail(422,'只能映射已批准、已授权的历史或当前配方')
        ingredients=json.loads(rev['content']).get('ingredients',[])
        if sorted(l.ingredient_index for l in data.lines)!=list(range(len(ingredients))) or not ingredients:
            fail(422,'必须逐项且不重复地映射全部配方原料')
        if db.execute('SELECT 1 FROM inv_recipe_maps WHERE revision_id=?',(rev['id'],)).fetchone():
            fail(409,'该配方版本已映射，禁止覆盖')
        lines=[]
        for line in data.lines:
            ingredient=ingredients[line.ingredient_index]
            amount,sku=quantity(db,line.sku_id,ingredient['amount'],ingredient['unit'],user)
            if amount<=0:
                fail(422,'配方用量必须大于0')
            lines.append({'ingredient_index':line.ingredient_index,'sku_id':sku['id'],'quantity_milli':amount,'ingredient_name':ingredient['name'],'amount':ingredient['amount'],'unit':ingredient['unit']})
        rid=db.execute('INSERT INTO inv_recipe_maps(store,revision_id,lines,source,created_by,created_at) VALUES(?,?,?,?,?,?)',(user['store'],rev['id'],encode(sorted(lines,key=lambda l:l['ingredient_index'])),data.source,user['id'],now())).lastrowid
        audit(db,user,'recipe_skus_mapped',rid)
    return {'id':rid,'lines':lines}


@router.post('/api/inventory/substitutions')
def approve_substitution(data: Substitute,user=Depends(manager)):
    effective=at(data.effective_at)
    expires=normalized_date(data.expires_at) if data.expires_at else None
    if not data.safety_confirmed or expires and expires<=max(effective,now()):
        fail(422,'须确认标签与过敏原等安全事项，失效时间须晚于当前及生效时间')
    with connect(True) as db:
        mapping=own_record(db,'inv_recipe_maps',data.recipe_map_id,user)
        doc,_=get_revision(db,mapping['revision_id'],user)
        if not scope(doc,user):fail(403,'无此配方权限')
        source=own_record(db,'inv_skus',data.from_sku_id,user);target=own_record(db,'inv_skus',data.to_sku_id,user)
        if source['id']==target['id'] or source['base_unit']!=target['base_unit'] or source['id'] not in {l['sku_id'] for l in json.loads(mapping['lines'])}:
            fail(422,'原SKU须属于该配方，替代SKU须不同且基础单位维度一致')
        ratio=scaled(data.ratio,1000)
        if not 0<ratio<=1000000:fail(422,'替代用量比例须大于0且不超过1000')
        rid=db.execute('INSERT INTO inv_substitutions(store,recipe_map_id,from_sku_id,to_sku_id,ratio_milli,reason,safety_note,effective_at,expires_at,approved_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(user['store'],mapping['id'],source['id'],target['id'],ratio,data.reason,data.safety_note,effective,expires,user['id'],now())).lastrowid
        audit(db,user,'substitution_approved',rid)
    return {'id':rid}


@router.get('/api/inventory/substitutions')
def substitutions(station: str,user=Depends(identity)):
    station_allowed(user,station)
    from .main import current
    with connect() as db:
        result=[]
        for row in db.execute('SELECT s.*,m.revision_id FROM inv_substitutions s JOIN inv_recipe_maps m ON m.id=s.recipe_map_id WHERE s.store=? ORDER BY s.id DESC',(user['store'],)):
            doc,rev=get_revision(db,row['revision_id'],user)
            if not scope(doc,user,station):continue
            active=current(db,doc['id'])
            valid=not row['revoked_at'] and row['effective_at']<=now() and (not row['expires_at'] or row['expires_at']>now()) and active and active['id']==rev['id']
            if valid or user['role']!='staff':result.append({**dict(row),'active':bool(valid),'title':doc['title']})
        return result


@router.post('/api/inventory/substitutions/{sid}/revoke')
def revoke(sid: int,data: Void,user=Depends(manager)):
    with connect(True) as db:
        sub=own_record(db,'inv_substitutions',sid,user)
        mapping=own_record(db,'inv_recipe_maps',sub['recipe_map_id'],user)
        doc,_=get_revision(db,mapping['revision_id'],user)
        if not scope(doc,user):fail(403,'无此配方权限')
        if sub['revoked_at']:fail(409,'批准已撤回')
        db.execute('UPDATE inv_substitutions SET revoked_at=? WHERE id=?',(now(),sid))
        audit(db,user,'substitution_revoked',str(sid)+':'+data.reason)
    return {'ok':True}


@router.post('/api/inventory/counts')
def count(data: Count,user=Depends(identity)):
    station_allowed(user,data.station);observed=at(data.observed_at)
    with connect(True) as db:
        skus={r['id'] for r in db.execute('SELECT id FROM inv_skus WHERE store=?',(user['store'],))}
        if len(data.lines)!=len(skus) or {l.sku_id for l in data.lines}!=skus:
            fail(422,'可信盘点必须逐项覆盖全部已登记SKU；零库存也须明确填0')
        if db.execute('SELECT 1 FROM inv_counts WHERE store=? AND station=? AND observed_at=?',(user['store'],data.station,observed)).fetchone():
            fail(409,'该吧台该时刻已有盘点')
        lines=[{'sku_id':l.sku_id,'quantity_milli':quantity(db,l.sku_id,l.amount,l.unit,user)[0]} for l in data.lines]
        rid=db.execute('INSERT INTO inv_counts(store,station,observed_at,source,evidence,lines,counted_by) VALUES(?,?,?,?,?,?,?)',(user['store'],data.station,observed,data.source,data.evidence,encode(lines),user['id'])).lastrowid
        audit(db,user,'stock_count_submitted',rid)
    return {'id':rid}


@router.post('/api/inventory/counts/{cid}/review')
def review_count(cid: int,data: Decision,user=Depends(manager)):
    with connect(True) as db:
        row=own_record(db,'inv_counts',cid,user,True)
        if row['state']!='submitted':fail(409,'盘点已复核，不可重复修改')
        if row['counted_by']==user['id']:fail(403,'可信盘点须由另一位主管复核，不能自己批准自己的盘点')
        db.execute('UPDATE inv_counts SET state=?,approved_by=?,approval_note=?,approved_at=? WHERE id=?',('approved' if data.approved else 'rejected',user['id'],data.note,now(),cid))
        audit(db,user,'stock_count_approved' if data.approved else 'stock_count_rejected',cid)
    return {'ok':True}


@router.get('/api/inventory/counts')
def counts(station: str,user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        return [{**dict(r),'lines':json.loads(r['lines'])} for r in db.execute('SELECT c.*,u.name counted_name,a.name approved_name FROM inv_counts c JOIN users u ON u.id=c.counted_by LEFT JOIN users a ON a.id=c.approved_by WHERE c.store=? AND station=? ORDER BY observed_at DESC LIMIT 200',(user['store'],station))]


@router.post('/api/inventory/movements')
def movement(data: Movement,user=Depends(manager)):
    station_allowed(user,data.station);occurred=at(data.occurred_at)
    with connect(True) as db:
        amount,_=quantity(db,data.sku_id,data.amount,data.unit,user)
        if amount<=0:fail(422,'出入库数量必须大于0')
        if db.execute('SELECT 1 FROM inv_movements WHERE store=? AND station=? AND external_key=?',(user['store'],data.station,data.external_key)).fetchone():fail(409,'来源记录已录入，禁止重复记账')
        rid=db.execute('INSERT INTO inv_movements(store,station,sku_id,occurred_at,kind,quantity_milli,source,external_key,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(user['store'],data.station,data.sku_id,occurred,data.kind,amount,data.source,data.external_key,user['id'],now())).lastrowid
        audit(db,user,'stock_movement_recorded',rid)
    return {'id':rid}


@router.get('/api/inventory/movements')
def movements(station: str,user=Depends(manager)):
    station_allowed(user,station)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM inv_movements WHERE store=? AND station=? ORDER BY occurred_at DESC,id DESC LIMIT 200',(user['store'],station))]


@router.post('/api/inventory/movements/{mid}/void')
def void_movement(mid: int,data: Void,user=Depends(manager)):
    with connect(True) as db:
        row=own_record(db,'inv_movements',mid,user,True)
        if row['voided_at']:fail(409,'记录已作废')
        db.execute('UPDATE inv_movements SET voided_at=?,void_reason=? WHERE id=?',(now(),data.reason,mid))
        audit(db,user,'stock_movement_voided',mid)
    return {'ok':True}


@router.post('/api/inventory/sales-batches')
def import_sales(data: SalesBatch,user=Depends(manager)):
    station_allowed(user,data.station);start=at(data.start_at);end=at(data.end_at)
    if start>=end:fail(422,'销售期间结束须晚于开始')
    with connect(True) as db:
        if db.execute('SELECT 1 FROM inv_sales_batches WHERE store=? AND station=? AND external_key=?',(user['store'],data.station,data.external_key)).fetchone():fail(409,'来源批次已导入')
        if db.execute('SELECT 1 FROM inv_sales_batches WHERE store=? AND station=? AND voided_at IS NULL AND start_at<? AND end_at>?',(user['store'],data.station,end,start)).fetchone():fail(409,'此吧台已有重叠销售期间；请先核对或作废原批次')
        bid=db.execute('INSERT INTO inv_sales_batches(store,station,start_at,end_at,source,external_key,is_complete,coverage_note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(user['store'],data.station,start,end,data.source,data.external_key,data.is_complete,data.coverage_note,user['id'],now())).lastrowid
        for sale in data.rows:
            sold=at(sale.sold_at)
            if not start<sold<=end:fail(422,'销售记录时间须在批次期间（开始，结束]内')
            if db.execute('SELECT 1 FROM inv_sales WHERE store=? AND station=? AND external_key=?',(user['store'],data.station,sale.external_key)).fetchone():fail(409,'销售来源行已存在，禁止重复计入')
            if not sale.quantity and not sale.produced_quantity and decimal_value(sale.net_revenue,True)==0:fail(422,'销售行不能所有业务量均为0')
            item={**sale.model_dump(),'station':data.station,'sold_at':sold}
            resolved=resolve_sale(db,item,user)
            db.execute('INSERT INTO inv_sales(store,station,batch_id,external_key,product_code,sold_at,quantity,produced_quantity,net_revenue_fen,substitution_ids,revision_id,recipe_map_id,mapping_state,consumption,issues) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(user['store'],data.station,bid,sale.external_key,sale.product_code,sold,sale.quantity,sale.produced_quantity,scaled(sale.net_revenue,100,True),encode(sale.substitution_ids),resolved['revision_id'],resolved['recipe_map_id'],resolved['mapping_state'],encode(resolved['consumption']),encode(resolved['issues'])))
        audit(db,user,'sales_batch_imported',bid)
    return {'id':bid,'rows':len(data.rows)}


@router.get('/api/inventory/sales')
def sales(station: str,user=Depends(manager)):
    station_allowed(user,station)
    with connect() as db:
        return [{**dict(r),'consumption':json.loads(r['consumption']),'issues':json.loads(r['issues'])} for r in db.execute('SELECT s.*,b.voided_at FROM inv_sales s JOIN inv_sales_batches b ON b.id=s.batch_id WHERE s.store=? AND s.station=? ORDER BY sold_at DESC,s.id DESC LIMIT 200',(user['store'],station))]


@router.get('/api/inventory/sales-batches')
def batches(station: str,user=Depends(manager)):
    station_allowed(user,station)
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM inv_sales_batches WHERE store=? AND station=? ORDER BY id DESC LIMIT 200',(user['store'],station))]


@router.post('/api/inventory/sales-batches/{bid}/void')
def void_batch(bid: int,data: Void,user=Depends(manager)):
    with connect(True) as db:
        row=own_record(db,'inv_sales_batches',bid,user,True)
        if row['voided_at']:fail(409,'批次已作废')
        db.execute('UPDATE inv_sales_batches SET voided_at=?,void_reason=? WHERE id=?',(now(),data.reason,bid))
        audit(db,user,'sales_batch_voided',bid)
    return {'ok':True}


@router.post('/api/inventory/sales/{sid}/reconcile')
def reconcile(sid: int,user=Depends(manager)):
    with connect(True) as db:
        sale=own_record(db,'inv_sales',sid,user,True)
        batch=own_record(db,'inv_sales_batches',sale['batch_id'],user,True)
        if batch['voided_at']:fail(409,'批次已作废')
        if sale['mapping_state']=='ready' and not json.loads(sale['issues']):fail(409,'记录已完整，不覆盖既有历史计算依据')
        raw={**dict(sale),'substitution_ids':json.loads(sale['substitution_ids'])}
        result=resolve_sale(db,raw,user)
        # Preserve previously known cost references while filling missing evidence.
        old={l['ingredient_index']:l for l in json.loads(sale['consumption'])}
        for line in result['consumption']:
            prior=old.get(line['ingredient_index'])
            if prior and prior['cost_micro'] is not None:
                line.update(cost_micro=prior['cost_micro'],cost_id=prior['cost_id'])
        if result['mapping_state']!='ready' or result['issues']:fail(409,'映射或历史成本仍不完整，请先补齐再对账')
        db.execute('UPDATE inv_sales SET revision_id=?,recipe_map_id=?,mapping_state=?,consumption=?,issues=?,version=version+1 WHERE id=?',(result['revision_id'],result['recipe_map_id'],result['mapping_state'],encode(result['consumption']),encode(result['issues']),sid))
        audit(db,user,'sales_evidence_reconciled',sid)
    return {'ok':True}

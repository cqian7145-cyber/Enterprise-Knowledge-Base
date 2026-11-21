"""Standalone versioned report formulas; no database, API or third-party imports."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

FORMULA_VERSION='stock-material-v1'


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def currency(fen):
    return format(Decimal(fen)/100,'.2f') if fen is not None else None


def material_fen(numerator):
    # milli base units * micro CNY/base unit => 1e-9 CNY; round once at total.
    return int((Decimal(numerator)/10000000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def calculate(inputs):
    if inputs['formula_version']!=FORMULA_VERSION:
        raise ValueError('Unsupported report formula version')
    start,end=inputs['start']['observed_at'],inputs['end']['observed_at']
    gaps=[]
    cursor=start
    for batch in sorted(inputs['batches'],key=lambda b:(b['start_at'],b['id'])):
        if not batch['is_complete']:continue
        if batch['start_at']>cursor:break
        cursor=max(cursor,batch['end_at'])
    sales_complete=cursor>=end
    if not sales_complete:gaps.append({'code':'sales_coverage','message':'销售来源未完整覆盖两次盘点之间的期间，零记录不能视为零销量。'})
    if not inputs['movements_complete']:gaps.append({'code':'movement_coverage','message':'尚未确认期间全部入库、报损和调拨已录入。'})
    opening={l['sku_id']:l['quantity_milli'] for l in inputs['start']['lines']}
    closing={l['sku_id']:l['quantity_milli'] for l in inputs['end']['lines']}
    consumption={};movement_totals={};products={};known_numerator=0;cost_complete=True;mapping_complete=True
    for sale in inputs['sales']:
        product=products.setdefault(sale['product_code'],{'product_code':sale['product_code'],'quantity':0,'produced_quantity':0,'net_revenue_fen':0,'known_cost_numerator':0,'cost_complete':True,'sale_ids':[]})
        product['quantity']+=sale['quantity'];product['produced_quantity']+=sale['produced_quantity'];product['net_revenue_fen']+=sale['net_revenue_fen'];product['sale_ids'].append(sale['id'])
        if sale['mapping_state']!='ready':
            mapping_complete=False;cost_complete=False;product['cost_complete']=False
            gaps.append({'code':sale['mapping_state'],'sale_id':sale['id'],'message':'销售行缺少商品、当时有效配方或SKU映射，不能完整计算理论消耗。'})
        for line in sale['consumption']:
            consumption[line['sku_id']]=consumption.get(line['sku_id'],0)+line['quantity_milli']
            if line['cost_micro'] is None:
                cost_complete=False;product['cost_complete']=False
                gaps.append({'code':'missing_cost','sale_id':sale['id'],'sku_id':line['sku_id'],'message':'缺少销售时刻有效的历史单位成本。'})
            else:
                value=line['quantity_milli']*line['cost_micro'];known_numerator+=value;product['known_cost_numerator']+=value
    for movement in inputs['movements']:
        totals=movement_totals.setdefault(movement['sku_id'],{'receipt':0,'waste':0,'transfer_in':0,'transfer_out':0})
        totals[movement['kind']]+=movement['quantity_milli']
    rows=[]
    valuation_complete=True
    for sku in inputs['skus']:
        sid=sku['id'];o=opening.get(sid);c=closing.get(sid);moves=movement_totals.get(sid,{'receipt':0,'waste':0,'transfer_in':0,'transfer_out':0});used=consumption.get(sid,0)
        if o is None or c is None:gaps.append({'code':'count_coverage','sku_id':sid,'message':'两次可信盘点未同时覆盖此SKU，禁止把缺项当作零库存。'})
        comparable=o is not None and c is not None and mapping_complete
        theoretical=o+moves['receipt']+moves['transfer_in']-moves['waste']-moves['transfer_out']-used if comparable else None
        variance=c-theoretical if comparable else None
        if theoretical is not None and theoretical<0:gaps.append({'code':'negative_theoretical_stock','sku_id':sid,'message':'理论库存为负，请检查来源记录、单位或盘点。'})
        cost=next((r for r in inputs['valuation_costs'] if r['sku_id']==sid),None)
        if variance is not None and variance!=0 and cost is None:
            valuation_complete=False;gaps.append({'code':'variance_cost_missing','sku_id':sid,'message':'盘点差异缺少期末估值成本。'})
        rows.append({'sku_id':sid,'code':sku['code'],'name':sku['name'],'base_unit':sku['base_unit'],'opening_milli':o,'closing_milli':c,**{k+'_milli':v for k,v in moves.items()},'known_consumption_milli':used,'theoretical_consumption_milli':used if mapping_complete else None,'theoretical_closing_milli':theoretical,'variance_milli':variance,'variance_value':currency(material_fen(variance*cost['cost_micro'])) if variance is not None and cost else '0.00' if variance==0 else None,'valuation_cost_id':cost['id'] if cost else None})
    product_rows=[]
    for product in sorted(products.values(),key=lambda p:p['product_code']):
        num=product.pop('known_cost_numerator')
        product.update(net_revenue=currency(product['net_revenue_fen']),theoretical_material_cost=currency(material_fen(num)) if product['cost_complete'] else None,known_material_cost=currency(material_fen(num)))
        product_rows.append(product)
    total_revenue=sum(s['net_revenue_fen'] for s in inputs['sales'])
    total_cost=material_fen(known_numerator) if cost_complete else None
    return {'formula_version':FORMULA_VERSION,'start_at':start,'end_at':end,'interval':'(开始盘点时刻，结束盘点时刻]','sales_coverage_complete':sales_complete,'movement_coverage_confirmed':inputs['movements_complete'],'mapping_complete':mapping_complete,'cost_complete':cost_complete,'valuation_complete':valuation_complete,'complete':not gaps,'data_gaps':gaps,'totals':{'quantity':sum(s['quantity'] for s in inputs['sales']),'produced_quantity':sum(s['produced_quantity'] for s in inputs['sales']),'recorded_net_revenue':currency(total_revenue),'theoretical_material_cost':currency(total_cost),'known_material_cost':currency(material_fen(known_numerator)),'material_contribution':currency(total_revenue-total_cost) if total_cost is not None else None},'products':product_rows,'inventory':rows,'definitions':['净销量与净销售额允许退款为负；实际制作份数独立记录，退款不自动恢复原料库存。','金额统一为人民币；销售额为含税净实收（扣除退款与折扣），原料成本为含税采购单价且不含运费等分摊。', '理论材料成本按每条销售绑定的历史配方、明确选用的批准替代及历史单位成本计算；不是财务结转成本或净利润。','理论期末库存=期初盘点+入库+调入-调出-报损-理论制作消耗；差异=期末实盘-理论期末，负值表示短少。','数量以0.001基础单位存储；历史单位成本精确到0.000001元；材料成本汇总后四舍五入到分，商品行舍入之和可能相差1分。','销量完整度来自人工核对的来源覆盖声明；出入库完整度来自生成报表时的核对声明。系统不能替代实际来源核验。']}


def main():
    import argparse
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf8')
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Recalculate an exported BarOS insight JSON without a database')
    parser.add_argument('report_file')
    args=parser.parse_args()
    saved=json.loads(Path(args.report_file).read_text(encoding='utf8'))
    inputs=saved['inputs']
    result=calculate(inputs)
    checks={'input_intact':digest(inputs)==saved['input_hash'],'saved_result_intact':digest(saved['result'])==saved['result_hash'],'matches':digest(result)==saved['result_hash']}
    print(json.dumps({**checks,'result':result},ensure_ascii=False,indent=2))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())

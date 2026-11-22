"""Offline-only historical API fixture. Imported solely by the explicit demo command.

All business writes use authenticated API requests and unchanged domain validation.
Only first administrators/registry display names and the demo manifest are bootstrap SQL.
The clock/connection adapter exists only while building a disposable staging file.
"""
import importlib
import json
import secrets
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from . import db as storage
from .demo_data import DATASET, LABEL, SKUS, RECIPES, EMPLOYEES, STATIONS, JOBS, knowledge_dataset

BJT=timezone(timedelta(hours=8))


class HistoricalAPI:
    def __init__(self,db,password,anchor):
        from .main import app
        self.db=db;self.password=password;self.anchor=anchor
        self.start=anchor.astimezone(BJT).date()-timedelta(days=14)
        self.clock=self.when(0,9);self.clients={};self.ids={};self.docs={};self.requests=0
        self.app=app
    def when(self,day,hour=12,minute=0):
        return datetime.combine(self.start+timedelta(days=day),datetime.min.time(),BJT).replace(hour=hour,minute=minute).astimezone(timezone.utc)
    def stamp(self,day,hour=12,minute=0):return self.when(day,hour,minute).isoformat(timespec='seconds')
    def now(self):return self.clock.isoformat(timespec='seconds')
    def tick(self,day,hour=12,minute=0):
        value=self.when(day,hour,minute)
        if value<self.clock:raise ValueError('Historical fixture clock must be monotonic')
        self.clock=value
    def client(self,name):
        if name not in self.clients:
            client=TestClient(self.app)
            response=client.post('/api/login',json={'username':name,'password':self.password})
            if response.status_code!=200:raise RuntimeError('Demo authentication failed for '+name)
            client.headers['X-CSRF-Token']=response.json()['csrf'];self.clients[name]=client
        return self.clients[name]
    def call(self,name,url,body=None,store=None,status=200):
        client=self.client(name)
        headers={'X-BarOS-Store':store} if store else {}
        response=client.get('/api'+url,headers=headers) if body is None else client.post('/api'+url,json=body,headers=headers)
        self.requests+=1
        if response.status_code==401 and status!=401:
            self.clients.pop(name).close();client=self.client(name)
            response=client.get('/api'+url,headers=headers) if body is None else client.post('/api'+url,json=body,headers=headers)
        if response.status_code!=status:
            # Payloads may contain credentials: never log request bodies.
            raise RuntimeError(f'{name} {url}: expected {status}, got {response.status_code}: {response.text[:600]}')
        return response.json()
    def fresh(self):
        for c in self.clients.values():c.close()
        self.clients.clear()
    def bootstrap(self):
        # As app.cli.bootstrap: an empty database has no API identity to create its first admin.
        for username,store,name in [('nf_admin','nf-downtown','NIGHTFALL Downtown'),('iso_admin','isolation-lab','ISOLATION LAB（虚构独立租户）')]:
            self.db.execute('INSERT INTO users(username,name,password,role,store,job,stations) VALUES(?,?,?,?,?,?,?)',(username,'模拟·林店长' if username=='nf_admin' else '模拟·隔离管理员',storage.password_hash(self.password),'admin',store,'bartender',storage.encode(STATIONS)))
        from .tenancy import ensure_registry
        ensure_registry(self.db)
        self.db.execute('UPDATE stores SET name=?,verification_note=? WHERE code=?',('NIGHTFALL Downtown · '+LABEL,'完全虚构；不代表真实多门店验收','nf-downtown'))
        self.db.execute('UPDATE tenants SET name=? WHERE id=(SELECT tenant_id FROM stores WHERE code=?)',('NIGHTFALL · 夜幕酒吧（虚构集团）','nf-downtown'))
        self.ids['nf_admin']=self.db.execute("SELECT id FROM users WHERE username='nf_admin'").fetchone()[0]
        self.ids['iso_admin']=self.db.execute("SELECT id FROM users WHERE username='iso_admin'").fetchone()[0]
        for kind,code,label in [('job','server','服务员'),('station','vip','VIP吧台'),('station','main','主吧台'),('station','terrace','露台吧台')]:
            self.call('nf_admin','/admin/scope-options',dict(kind=kind,code=code,label=label))
        for username,name,role,job,stations in EMPLOYEES[1:]:self.add_user(username,name,role,job,stations)
        self.call('nf_admin','/hq/stores',dict(code='nf-riverside',name='NIGHTFALL Riverside · '+LABEL,verification_note='完全虚构的集团分店，仅用于隔离演示',job='bartender',station='main'))
        self.call('nf_admin','/hq/grants',dict(user_id=self.ids['nf_admin'],store='nf-riverside',role='admin',job='bartender',stations=['main'],expires_at=self.stamp(180),note='模拟总部负责人明确授权分店管理'))
        self.call('nf_admin','/admin/scope-options',dict(kind='job',code='server',label='服务员'),store='nf-riverside')
        self.add_user('nf_branch','模拟·河畔店长','manager','bartender',['main'],'nf-riverside')
        self.add_user('nf_branchbar','模拟·河畔调酒师','staff','bartender',['main'],'nf-riverside')
    def add_user(self,username,name,role,job,stations,store=None):
        temporary=secrets.token_urlsafe(24)
        uid=self.call('nf_admin','/admin/users',dict(username=username,name=name,password=temporary,role=role,job=job,stations=stations),store=store)['id']
        client=TestClient(self.app)
        try:
            login=client.post('/api/login',json={'username':username,'password':temporary});assert login.status_code==200
            response=client.post('/api/password',json={'current_password':temporary,'new_password':self.password},headers={'X-CSRF-Token':login.json()['csrf']})
            assert response.status_code==200
        finally:client.close()
        self.ids[username]=uid
    def create_knowledge(self,data,store=None,publish=True,actor='nf_lead',effective=None):
        payload={'source':LABEL+'；NIGHTFALL原创合成标准 NF-EDITORIAL-v1',**data}
        row=self.call(actor,'/manage/drafts',payload,store)
        if publish:self.publish(row['id'],store=store,effective=effective)
        if not store:
            self.docs[data['title']]={'row':row,'data':payload}
            self.call('nf_admin',f"/manage/memory/{row['document_id']}/metadata",dict(owner_id=self.ids['nf_lead'],review_due_at=self.stamp(40),metadata_version=0))
        return row
    def publish(self,rid,store=None,effective=None):
        self.call('nf_admin',f'/manage/revisions/{rid}/submit',{},store)
        self.call('nf_admin',f'/manage/revisions/{rid}/publish',dict(effective_at=effective or self.now(),risk_confirmed=True),store)
    def course(self,title,material):
        questions=[dict(question='本环境中的资料代表什么？',options=['独立演示资料','真实上岗许可'],answer=0),dict(question='没有有效依据时怎么办？',options=['联系主管核对','自行猜测'],answer=0),dict(question='理论通过是否代表实操已验收？',options=['仍需主管观察记录','自动正式认证'],answer=0)]
        payload=dict(title=title+' · 模拟培训',objective=LABEL+'；学会核对'+material+'，本记录不构成正式岗位资格。',revision_ids=[self.docs[material]['row']['id']],quiz=questions,pass_score=100)
        row=self.call('nf_admin','/manage/modules',payload)
        return row['id'],payload
    def assign(self,mid,name,due=12):
        return self.call('nf_admin','/manage/assignments',dict(module_id=mid,user_id=self.ids[name],due_at=self.stamp(due)))['id']
    def attempt(self,name,aid,answers):return self.call(name,f'/training/{aid}/submit',dict(answers=answers))
    def review(self,aid,passed):return self.call('nf_mentor',f'/manage/training/{aid}/reviews',dict(passed=passed,note=LABEL+'；观察计量、标准核对与复述，'+('本次演示通过' if passed else '未复核版本，需再次练习'),evidence='SIM-NF-OBS-'+str(aid)+'；仅为合成观察证据，不是现场认证'))
    def approve_plan(self,title,rid,key):
        p=self.call('nf_admin','/agents/plans',dict(title=title,recipe_revision_id=rid,station='main',launch_at=self.stamp(20),owner_id=self.ids['nf_bar1'],idempotency_key=key))
        v=self.call('nf_admin',f"/agents/plans/{p['id']}/submit",dict(version=p['version']))['version']
        v=self.call('nf_admin',f"/agents/plans/{p['id']}/decision",dict(version=v,approved=True,note=LABEL+'；人工核对固定七项任务及负责人后批准'))['version']
        return p['id'],v


@contextmanager
def fixture_context(db,password,anchor):
    api=HistoricalAPI(db,password,anchor)
    serial=0
    @contextmanager
    def transaction(write=False):
        nonlocal serial
        serial+=1;name='fixture_'+str(serial)
        db.execute('SAVEPOINT '+name)
        try:
            yield db
            db.execute('RELEASE '+name)
        except BaseException:
            db.execute('ROLLBACK TO '+name);db.execute('RELEASE '+name);raise
    class DemoDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return api.clock.astimezone(tz) if tz else api.clock.replace(tzinfo=None)
    modules=['db','main','maintenance','memory','academy','operations','inventory','insight','hq','agents','business','tasks','tenancy']
    with ExitStack() as stack:
        for name in modules:
            module=importlib.import_module('app.'+name)
            if hasattr(module,'connect'):stack.enter_context(patch.object(module,'connect',transaction))
            if hasattr(module,'now'):stack.enter_context(patch.object(module,'now',api.now))
            if hasattr(module,'datetime'):stack.enter_context(patch.object(module,'datetime',DemoDateTime))
        try:yield api
        finally:api.fresh()


def build(db,password,anchor,fail_after=None):
    with fixture_context(db,password,anchor) as a:
        a.bootstrap()
        if fail_after=='accounts':raise RuntimeError('Injected fixture failure')
        for item in knowledge_dataset():a.create_knowledge(item)
        # A same-title restricted card proves station scope without leaking the VIP edition.
        a.create_knowledge(dict(title='VIP 接待内页',kind='rule',jobs=['server'],stations=['vip'],aliases=[],content=dict(summary=LABEL+'；VIP岗位演示资料',steps=['向VIP领班核对接待安排，不记录顾客身份'])))
        foreign=a.create_knowledge(dict(title='隔离实验室专属标准',kind='sop',jobs=['bartender'],stations=['main'],aliases=[],content=dict(summary=LABEL+'；其他租户不得看见',steps=['仅供独立租户演示核对'])),store='isolation-lab',actor='iso_admin',publish=False)
        a.call('iso_admin',f"/manage/revisions/{foreign['id']}/submit",{})
        a.call('iso_admin',f"/manage/revisions/{foreign['id']}/publish",dict(effective_at=a.now()))
        # Catalog: immutable unit definitions and cost references.
        skus={};costs={};maps={}
        for code,name,unit,package,size,price in SKUS:
            skus[code]=a.call('nf_admin','/inventory/skus',dict(code=code,name=name+'（模拟）',base_unit=unit,units=[dict(unit=package,factor=size)]))['id']
            if price is not None:costs[code]=a.call('nf_admin','/inventory/costs',dict(sku_id=skus[code],unit=package,price=price,effective_at=a.now(),source='SIM-PO-BASE-'+code+'；合成含税包装采购价，无真实供应商'))
        for title,en,technique,glass,garnish,ingredients in RECIPES:
            row=a.docs[title]['row'];code='NF'+str(RECIPES.index((title,en,technique,glass,garnish,ingredients))+1).zfill(2)
            a.call('nf_admin','/inventory/products',dict(code=code,name=title,document_id=row['document_id']))
            maps[title]=a.call('nf_admin','/inventory/recipe-maps',dict(revision_id=row['id'],lines=[dict(ingredient_index=i,sku_id=skus[c]) for i,(c,_,_) in enumerate(ingredients)],source=LABEL+'；逐项对应合成SKU'))['id']
        sub=a.call('nf_admin','/inventory/substitutions',dict(recipe_map_id=maps['夜幕金汤力'],from_sku_id=skus['GIN'],to_sku_id=skus['GIN_ALT'],ratio='1',reason='模拟供应批次不足，主调确认本演示配方可替代',safety_note='仅合成标签核验记录；现实使用必须重新核验，不作过敏原安全保证',safety_confirmed=True,effective_at=a.now(),expires_at=a.stamp(30)))['id']
        # Eight course families, all initially reference active approved materials.
        courses={}
        for title,material in [('新人第一天认识吧台','开吧岗位准备'),('基础酒水知识','原料验收登记'),('经典鸡尾酒配方','夜幕金汤力'),('开吧和收吧标准','收吧交付'),('服务沟通','服务沟通演练'),('饮品推荐','饮品推荐'),('投诉升级','客诉升级卡'),('进阶出品规范','配方版本发布')]:courses[title]=a.course(title,material)
        newcomer=a.assign(courses['新人第一天认识吧台'][0],'nf_new')
        retry=a.assign(courses['新人第一天认识吧台'][0],'nf_retry')
        theory=a.assign(courses['新人第一天认识吧台'][0],'nf_theory')
        failed=a.assign(courses['新人第一天认识吧台'][0],'nf_failed')
        learning=a.assign(courses['新人第一天认识吧台'][0],'nf_learning')
        idle=a.assign(courses['新人第一天认识吧台'][0],'nf_idle')
        for title,(mid,_) in courses.items():
            if title not in ('新人第一天认识吧台','经典鸡尾酒配方'):
                a.assign(mid,'nf_server1' if title in ('服务沟通','饮品推荐','投诉升级') else 'nf_bar2')
        old_course,old_payload=courses['经典鸡尾酒配方']
        old_assignment=a.assign(old_course,'nf_bar1')
        a.attempt('nf_bar1',old_assignment,[0,0,0]);a.review(old_assignment,True)
        # Recipe source-bound old plan will be blocked after V2 activation.
        stale_plan,stale_version=a.approve_plan('夜幕金汤力旧版上新（应阻止执行）',a.docs['夜幕金汤力']['row']['id'],'nf-old-plan-v1')
        a.call('nf_admin','/hq/grants',dict(user_id=a.ids['nf_rotating'],store='nf-riverside',role='staff',job='bartender',stations=['main'],expires_at=a.stamp(30),note='模拟两店轮岗授权，稍后撤销用于演示'))
        opening={code:20000 if code=='TONIC' else 10000 if unit=='ml' else 5000 if unit=='g' else 200 for code,_,unit,*_ in SKUS}
        a.tick(1,3)
        def count_at(quantities,source,observed=None,reviewer='nf_supervisor'):
            cid=a.call('nf_lead','/inventory/counts',dict(station='main',observed_at=observed or a.now(),source=source,evidence=LABEL+'；全SKU逐项盘点，数量来自可复算的合成原始表',lines=[dict(sku_id=skus[code],amount=str(quantities[code]),unit=unit) for code,_,unit,*_ in SKUS]))['id']
            a.call(reviewer,f'/inventory/counts/{cid}/review',dict(approved=True,note=LABEL+'；不同人员核对基础单位与全部SKU'))
            return cid
        start_count=count_at(opening,'SIM-COUNT-OPEN；合成期初盘点')
        a.tick(1,10)
        a.attempt('nf_new',newcomer,[1,1,1]);a.attempt('nf_failed',failed,[1,1,1]);a.attempt('nf_learning',learning,[0,1,1])
        a.tick(2,10)
        for username,aid in [('nf_new',newcomer),('nf_retry',retry),('nf_theory',theory)]:a.attempt(username,aid,[0,0,0])
        a.review(newcomer,False);a.review(retry,False)
        a.tick(3,10);a.attempt('nf_new',newcomer,[0,0,0]);a.review(newcomer,True)
        # Error -> proposal -> reviewed new immutable recipe -> scheduled activation.
        q=a.call('nf_bar1','/ask',dict(question='夜幕金汤力',station='main'))
        fid=a.call('nf_bar1','/feedback',dict(query_id=q['query_id'],kind='error',description=LABEL+'；模拟主调要求基酒从45ml改为55ml，等待审核'))['id']
        proposal=a.call('nf_lead','/manage/proposals',dict(feedback_id=fid,document_id=a.docs['夜幕金汤力']['row']['document_id'],description=LABEL+'；纠错来源转配方修订'))['id']
        old_recipe=a.docs['夜幕金汤力'];payload=json.loads(json.dumps(old_recipe['data']));payload['document_id']=old_recipe['row']['document_id'];payload['content']['ingredients'][0]['amount']='55';payload['change_reason']='SIM-CHANGE-01；演示55ml新标准，要求旧课重学'
        v2=a.call('nf_lead',f'/manage/proposals/{proposal}/draft',payload)
        a.publish(v2['id'],effective=a.stamp(4,18))
        a.call('nf_admin','/inventory/recipe-maps',dict(revision_id=v2['id'],lines=[dict(ingredient_index=0,sku_id=skus['GIN']),dict(ingredient_index=1,sku_id=skus['TONIC'])],source=LABEL+'；V2历史配方SKU对应'))
        # Freeze a future V3 with V2 still effective during the demo.
        a.tick(4,19)
        a.call('nf_lead',f'/manage/proposals/{proposal}/decision',dict(action='close',note=LABEL+'；V2已经到时生效，完成反馈闭环'))
        a.call('nf_admin',f'/agents/plans/{stale_plan}/execute',dict(version=stale_version,idempotency_key='nf-stale-execution'),status=409)
        new_course=a.call('nf_admin',f'/manage/modules/{old_course}/version',{**old_payload,'revision_ids':[v2['id']],'change_note':LABEL+'；配方V2生效后安排重学','due_at':a.stamp(12)})
        new_assignment=next(r['id'] for r in a.call('nf_bar1','/training') if r['module_id']==new_course['id'])
        a.call('nf_admin','/inventory/costs',dict(sku_id=skus['GIN'],unit='瓶',price='216',effective_at=a.now(),source='SIM-PO-PRICE-V2；合成包装价变更，保留此前180元历史成本'))
        a.tick(5,10);a.attempt('nf_bar1',new_assignment,[0,0,0]);a.review(new_assignment,True)
        # API-created historical records: no SQL rewriting approved timestamps.
        # A separate timeline loop is monotonic; recipe/course setup above preceded the loop,
        # so historical Flow is constructed by the independent fixture replay below.
        a.tick(8,4)
        # Record facts using their original event timestamps; APIs support past sales/movements.
        movements=[('GIN','receipt',1500),('GIN','transfer_in',750),('GIN','waste',100),('GIN','transfer_out',250)]
        for i,(code,kind,amount) in enumerate(movements):
            a.call('nf_admin','/inventory/movements',dict(station='main',sku_id=skus[code],kind=kind,amount='2' if kind=='receipt' else str(amount),unit='瓶' if kind=='receipt' else 'ml',occurred_at=a.stamp(3,15+i),source='SIM-MOVE-'+str(i)+'；合成入库调拨报损原单',external_key='NF-MOVE-'+str(i)))
        used={code:0 for code in opening};revenues=0;produced=0
        for day in range(1,8):
            rows=[]
            for suffix,qty,made,revenue,hour,minute in [('PAID',10,10,'880',23,30),('DISCOUNT',2,2,'140',23,40),('GIFT',0,1,'0',23,45),('REFUND',-1,0,'-88',1,30)]:
                sold_day=day+1 if hour==1 else day
                rows.append(dict(external_key=f'NF-D{day:02d}-{suffix}',product_code='NF01',sold_at=a.stamp(sold_day,hour,minute),quantity=qty,produced_quantity=made,net_revenue=revenue))
                amount=55 if sold_day>4 or sold_day==4 and hour>=18 else 45
                used['GIN']+=amount*made;used['TONIC']+=120*made;revenues+=int(revenue)*100;produced+=made
            # Approved V1 substitution is used before the V2 switch only.
            if day==2:
                rows.append(dict(external_key='NF-SUB-01',product_code='NF01',sold_at=a.stamp(2,22),quantity=1,produced_quantity=1,net_revenue='88',substitution_ids=[sub]))
                used['GIN_ALT']+=45;used['TONIC']+=120;revenues+=8800;produced+=1
            for idx in [1,12,18,20]:
                code='NF'+str(idx+1).zfill(2)
                rows.append(dict(external_key=f'NF-D{day:02d}-{code}',product_code=code,sold_at=a.stamp(day,22,idx),quantity=3,produced_quantity=3,net_revenue='198'))
                for ingredient,amount,unit in RECIPES[idx][-1]:used[ingredient]+=amount*3
                revenues+=19800;produced+=3
            a.call('nf_admin','/inventory/sales-batches',dict(station='main',start_at=a.stamp(day,3),end_at=a.stamp(day+1,3),source=f'SIM-POS-D{day:02d}；人工合成POS来源，不是真实经营事实',external_key=f'NF-BATCH-{day:02d}',is_complete=True,coverage_note='合成期间完整覆盖；含退款折扣赠饮与跨午夜销售，无真实订单',rows=rows))
        closing={code:opening[code]-used[code] for code in opening}
        for code,kind,amount in movements:closing[code]+=amount if kind in ('receipt','transfer_in') else -amount
        closing['GIN']-=180
        end_count=count_at(closing,'SIM-COUNT-CLOSE；招牌饮品基酒短少180ml的合成盘点',a.stamp(8,3),reviewer='nf_mentor')
        report=a.call('nf_admin','/insight/reports',dict(start_count_id=start_count,end_count_id=end_count,movements_complete=True,completeness_note='SIM-RECON-01；期间7个连续来源批次与4条出入库全量核对'))
        a.tick(9,4)
        # Separate, intentionally incomplete period: missing product mapping and missing cost are not zero.
        gap_rows=[dict(external_key='NF-GAP-MAPPING',product_code='UNMAPPED-DEMO',sold_at=a.stamp(8,22),quantity=1,produced_quantity=1,net_revenue='66'),dict(external_key='NF-GAP-COST',product_code='NF26',sold_at=a.stamp(8,23),quantity=1,produced_quantity=1,net_revenue='66')]
        a.call('nf_admin','/inventory/sales-batches',dict(station='main',start_at=a.stamp(8,3),end_at=a.stamp(9,4),source='SIM-POS-GAP；故意缺证的独立演示期间',external_key='NF-BATCH-GAP',is_complete=True,coverage_note='合成来源完整但有商品映射和成本缺项',rows=gap_rows))
        gap_closing={**closing,'SEASONAL':closing['SEASONAL']-30,'LEMON':closing['LEMON']-20,'SODA':closing['SODA']-90}
        gap_close=count_at(gap_closing,'SIM-COUNT-GAP；合成缺证窗口盘点，不猜测未知消耗')
        gap_report=a.call('nf_admin','/insight/reports',dict(start_count_id=end_count,end_count_id=gap_close,movements_complete=True,completeness_note='SIM-GAP；保留缺失值，禁止将缺价和缺映射当0'))
        a.tick(10,10)
        # HQ: exactly the same template accepted in both stores; only Riverside is locally published.
        svc=dict(summary=LABEL+'；总部统一迎宾说明',steps=['复述请求并核对当前酒单','无法确认交本店主管'],service=dict(context='顾客询问当前可推荐饮品',response='先确认您的口味，再按本店有效酒单说明。',escalation_trigger='信息不确定或超出权限',escalation_contact='本店当班主管'))
        tpl=a.call('nf_admin','/hq/templates',dict(title='总部统一迎宾服务标准',kind='service_script',content=svc,source=LABEL+'；HQ-EDITORIAL-01',change_note='合成集团首次统一服务标准'))
        a.call('nf_admin',f"/hq/templates/{tpl['id']}/submit",{});a.call('nf_admin',f"/hq/templates/{tpl['id']}/approve",dict(risk_confirmed=True))
        delivery=a.call('nf_admin',f"/hq/templates/{tpl['id']}/release",dict(stores=['nf-downtown','nf-riverside'],idempotency_key='nf-hq-release-01'))['ids']
        for did,store in zip(delivery,['nf-downtown','nf-riverside']):
            local=json.loads(json.dumps(svc));local['steps'][0]='先核对'+('主吧台入口酒单' if store=='nf-downtown' else '河畔店东侧酒单展示架')
            adoption=a.call('nf_admin',f'/hq/deliveries/{did}/sign',dict(accepted=True,note=LABEL+'；已签收但还须本店审核',jobs=JOBS,stations=['main'],local_content=local,difference_note='模拟门店酒单展示位置不同，记录本店差异'),store)
            if store=='nf-riverside':a.publish(adoption['id'],store)
        gid=next(g['id'] for g in a.call('nf_admin','/hq')['grants'] if g['user_id']==a.ids['nf_rotating'])
        a.call('nf_admin',f'/hq/grants/{gid}/revoke',dict(note=LABEL+'；轮岗结束撤销分店授权'))
        a.call('nf_rotating','/knowledge',store='nf-riverside',status=403)
        a.tick(11,10)
        good_plan,version=a.approve_plan('暮色桂花新品准备 · 模拟',a.docs['暮色桂花']['row']['id'],'nf-good-plan-01')
        execute=dict(version=version,idempotency_key='nf-good-execute-01')
        executed=a.call('nf_admin',f'/agents/plans/{good_plan}/execute',execute)
        assert a.call('nf_admin',f'/agents/plans/{good_plan}/execute',execute)==executed
        for tid in executed['task_ids'][:2]:a.call('nf_bar1',f'/tasks/{tid}/close',dict(version=1,evidence=LABEL+'；已核对对应合成资料，证据编号NF-LAUNCH-'+str(tid)))
        # Pending and retired standards remain visible only to management.
        unanswered=a.call('nf_learning','/ask',dict(question='不存在的演示饮品星河未知',station='main'))
        a.call('nf_learning',f"/queries/{unanswered['query_id']}/escalate",dict(note=LABEL+'；知识缺口待主管核对，不自行编造配方'))
        extra=dict(title='下一季菜单说明（待审）',kind='rule',jobs=JOBS,stations=STATIONS,aliases=[],content=dict(summary=LABEL+'；尚未批准',steps=['待主管审核后才可使用']))
        pending=a.create_knowledge(extra,publish=False);a.call('nf_lead',f"/manage/revisions/{pending['id']}/submit",{})
        retired=a.create_knowledge({**extra,'title':'旧版活动说明（已停用）'},publish=True)
        a.call('nf_admin',f"/manage/revisions/{retired['id']}/retire",{})
        orphan=a.docs['仓储调拨记录']['row']['document_id'];a.call('nf_admin',f'/manage/memory/{orphan}/metadata',dict(owner_id=None,review_due_at=a.stamp(8),metadata_version=1))
        overdue=a.docs['采购价格留档']['row']['document_id'];a.call('nf_admin',f'/manage/memory/{overdue}/metadata',dict(owner_id=a.ids['nf_lead'],review_due_at=a.stamp(8),metadata_version=1))
        future=json.loads(json.dumps(payload));future['content']['ingredients'][0]['amount']='50';future['change_reason']='SIM-FUTURE；未来模拟版本，当前仍使用55ml'
        v3=a.call('nf_lead','/manage/drafts',future);a.publish(v3['id'],effective=a.stamp(30))
        manifest=dict(dataset=DATASET,label=LABEL,simulated=True,anchor=anchor.isoformat(timespec='seconds'),start_date=a.start.isoformat(),accounts=[{'username':r['username'],'name':r['name'],'store':r['store'],'role':r['role'],'job':r['job'],'stations':json.loads(r['stations'])} for r in db.execute('SELECT * FROM users ORDER BY id')],stories=dict(newcomer=newcomer,retry=retry,theory=theory,failed=failed,learning=learning,idle=idle,old_assignment=old_assignment,new_assignment=new_assignment,recipe_v1=old_recipe['row']['id'],recipe_v2=v2['id'],recipe_future=v3['id'],recipe_document=old_recipe['row']['document_id'],proposal=proposal,start_count=start_count,end_count=end_count,report=report['id'],gap_report=gap_report['id'],good_plan=good_plan,stale_plan=stale_plan,stale_version=stale_version,deliveries=delivery),expected=dict(consumption=used,closing=closing,gin_variance_ml=-180,recorded_revenue_fen=revenues,produced=produced),sku_ids=skus)
        manifest['stories'].update(replay_flow(a))
        a.clock=anchor
        manifest['api_requests']=a.requests
        if fail_after=='business':raise RuntimeError('Injected fixture failure')
    return manifest


def replay_flow(a):
    """Replay the independent operations stream from bootstrapped day 0.

    Flow deliberately has no backdate API. Clock moves only in this offline fixture;
    no existing timestamps are updated, and every mutation uses the ordinary API.
    Closing records keep the calendar business date on which they were created;
    close_at is next day 02:00 BJT, matching current Flow's explicit-date rule.
    """
    a.fresh();a.clock=a.when(0,18)
    closed_incident=None;open_incident=None
    for day in range(14):
        a.tick(day,18);a.fresh()
        opening=a.call('nf_admin','/flow/runs',dict(kind='opening',station='main',business_date=(a.start+timedelta(days=day)).isoformat(),owner_id=a.ids['nf_bar2']))['id']
        def fill(rid,issue=False,partial=False):
            detail=a.call('nf_bar2',f'/flow/runs/{rid}')
            for item in detail['items'][:2 if partial else 4]:
                a.call('nf_bar2',f"/flow/runs/{rid}/items/{item['id']}",dict(version=detail['version'],state='issue' if issue and item['position']==1 else 'done',note=LABEL+'；按合成检查表记录，实际安全操作须场所批准',evidence=f'SIM-FLOW-D{day:02d}-'+str(item['id'])))
                detail=a.call('nf_bar2',f'/flow/runs/{rid}')
            return detail
        detail=fill(opening,issue=day==2,partial=day==13)
        if day<13:a.call('nf_bar2',f'/flow/runs/{opening}/close',dict(version=detail['version'],note=LABEL+'；检查已交付，异常独立跟进'))
        if day==2:
            closed_incident=next(x['id'] for x in a.call('nf_admin','/flow/incidents?station=main') if x['item_id'])
            a.call('nf_admin',f'/flow/incidents/{closed_incident}/owner',dict(version=1,owner_id=a.ids['nf_lead']))
            a.call('nf_lead',f'/flow/incidents/{closed_incident}/resolve',dict(version=2,resolution=LABEL+'；模拟设备异常已由维护负责人复检',evidence='SIM-REPAIR-01；纯合成复检单，不是真实设备证据'))
            a.call('nf_supervisor',f'/flow/incidents/{closed_incident}/close',dict(version=3))
            repair=a.call('nf_bar2','/flow/incidents',dict(station='main',title='制冰机状态指示异常（模拟报修）',description=LABEL+'；仅登记异常，不给出维修或安全操作方法',evidence='SIM-EQUIP-ICE-02；模拟设备编号',owner_id=a.ids['nf_bar2']))['id']
            a.call('nf_admin',f'/flow/incidents/{repair}/owner',dict(version=1,owner_id=a.ids['nf_lead']))
            open_incident=repair
        a.tick(day,23,30)
        handoff=a.call('nf_admin','/flow/runs',dict(kind='handoff',station='main',business_date=(a.start+timedelta(days=day)).isoformat(),owner_id=a.ids['nf_bar2'],recipient_id=a.ids['nf_bar1']))['id']
        detail=fill(handoff)
        if day<13:a.call('nf_bar1',f'/flow/runs/{handoff}/close',dict(version=detail['version'],note=LABEL+'；指定接班人核对收到'))
        a.tick(day,23,50)
        closing=a.call('nf_admin','/flow/runs',dict(kind='closing',station='main',business_date=(a.start+timedelta(days=day)).isoformat(),owner_id=a.ids['nf_bar2']))['id']
        if day<13:
            a.tick(day+1,2)
            detail=fill(closing)
            a.call('nf_bar2',f'/flow/runs/{closing}/close',dict(version=detail['version'],note=LABEL+'；跨午夜完成，业务日期仍为创建清单的北京时间日期'))
    return dict(closed_incident=closed_incident,open_incident=open_incident,last_opening=opening,last_handoff=handoff,last_closing=closing)

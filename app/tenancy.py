"""Legacy stores stay isolated; cross-store context requires an explicit unexpired grant."""
import json
from .db import now, encode, audit


def ensure_registry(db):
    # Existing store identifiers are preserved; no two legacy stores are inferred to be one company.
    codes={r[0] for r in db.execute('SELECT store FROM users UNION SELECT store FROM documents')}
    for code in sorted(codes):
        if not db.execute('SELECT 1 FROM stores WHERE code=?',(code,)).fetchone():
            tenant=db.execute('INSERT INTO tenants(code,name,created_at) VALUES(?,?,?)',('legacy:'+code,code+' 独立租户',now())).lastrowid
            db.execute('INSERT INTO stores VALUES(?,?,?,?,?)',(code,tenant,code,'既有门店迁移记录；尚未完成真实连锁试点',now()))
            owner=db.execute("SELECT id FROM users WHERE store=? AND role='admin' AND active=1 ORDER BY id LIMIT 1",(code,)).fetchone()
            if owner:db.execute('INSERT INTO hq_members VALUES(?,?,1)',(tenant,owner['id']))


def context(db,user,target=None):
    from .main import fail
    ensure_registry(db)
    home=user['store']
    home_store=db.execute('SELECT * FROM stores WHERE code=?',(home,)).fetchone()
    if not home_store:fail(403,'账号未登记到有效租户')
    tenant=home_store['tenant_id']
    result={**dict(user),'home_store':home,'home_role':user['role'],'tenant_id':tenant}
    result['hq_owner']=bool(user['role']=='admin' and db.execute('SELECT 1 FROM hq_members WHERE tenant_id=? AND user_id=? AND active=1',(tenant,user['id'])).fetchone())
    target=target or home
    if target!=home:
        store=db.execute('SELECT * FROM stores WHERE code=? AND tenant_id=?',(target,tenant)).fetchone()
        grant=db.execute('SELECT * FROM store_grants WHERE user_id=? AND store=? AND tenant_id=? AND revoked_at IS NULL AND expires_at>?',(user['id'],target,tenant,now())).fetchone()
        if not store or not grant:fail(403,'无有效跨店授权，或目标门店不属于同一租户')
        result.update(store=target,role=grant['role'],job=grant['job'],stations=grant['stations'])
    return result


def permitted_stores(db,user):
    rows=[]
    for store in db.execute('SELECT * FROM stores WHERE tenant_id=? ORDER BY code',(user['tenant_id'],)):
        if store['code']==user['home_store']:
            rows.append({'code':store['code'],'name':store['name']})
        elif db.execute('SELECT 1 FROM store_grants WHERE tenant_id=? AND user_id=? AND store=? AND revoked_at IS NULL AND expires_at>?',(user['tenant_id'],user['id'],store['code'],now())).fetchone():
            rows.append({'code':store['code'],'name':store['name']})
    return rows


def owner_user(user):
    from .main import fail
    if not user.get('hq_owner'):fail(403,'需要本租户总部负责人权限')
    return user


def scoped_person(db,uid,store,include_inactive=False):
    from fastapi import HTTPException
    row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not row or not include_inactive and not row['active']:
        return None
    if row['store']==store:return dict(row)
    if not row['active']:return None
    try:return context(db,dict(row),store)
    except HTTPException:return None


def scoped_people(db,store):
    ids={r[0] for r in db.execute('SELECT id FROM users WHERE store=? AND active=1',(store,))}
    ids.update(r[0] for r in db.execute('SELECT user_id FROM store_grants WHERE store=? AND revoked_at IS NULL AND expires_at>?',(store,now())))
    return [p for uid in sorted(ids) if (p:=scoped_person(db,uid,store))]

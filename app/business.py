"""Idempotent business writes share a scoped, payload-bound request ledger."""
from .db import encode,now
from .report_math import digest


def replay(db,user,action,key,payload):
    from .main import fail
    row=db.execute('SELECT * FROM business_requests WHERE actor=? AND store=? AND action=? AND key=?',(user['id'],user['store'],action,key)).fetchone()
    if row:
        if row['request_hash']!=digest(payload):fail(409,'幂等编号已用于其他请求内容')
        import json
        return json.loads(row['response'])
    return None


def remember(db,user,action,key,payload,response):
    db.execute('INSERT INTO business_requests VALUES(?,?,?,?,?,?,?)',(user['id'],user['store'],action,key,digest(payload),encode(response),now()))

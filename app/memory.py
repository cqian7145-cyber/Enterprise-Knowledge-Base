"""Governed organizational memory; proposals never publish knowledge automatically."""
import json
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import Field
from .db import audit, connect, encode, now
from .main import Draft, Input, create_draft_record, current, fail, identity, manager, normalized_date

router = APIRouter()


def record_event(db, document_id, revision_id, user, kind, payload):
    db.execute('INSERT INTO knowledge_events(document_id,revision_id,actor,kind,payload,created_at) VALUES(?,?,?,?,?,?)',
               (document_id, revision_id, user['id'], kind, encode(payload), now()))


def document(db, did, user):
    row = db.execute('SELECT * FROM documents WHERE id=? AND store=?', (did, user['store'])).fetchone()
    if not row:
        fail(404, '知识不存在')
    return row


class Metadata(Input):
    owner_id: int | None = None
    review_due_at: str | None = None
    metadata_version: int = Field(ge=0)


class Review(Input):
    revision_id: int
    next_review_at: str
    note: str = Field(min_length=2, max_length=2000)


class Proposal(Input):
    feedback_id: int | None = None
    document_id: int | None = None
    description: str = Field(min_length=2, max_length=2000)


class Decision(Input):
    action: Literal['reject', 'close']
    note: str = Field(min_length=2, max_length=2000)


class Escalate(Input):
    note: str = Field(default='', max_length=2000)


@router.get('/api/manage/memory')
def memory(user=Depends(manager)):
    with connect() as db:
        rows = db.execute('SELECT d.*,m.owner_id,m.review_due_at,m.last_reviewed_at,COALESCE(m.metadata_version,0) metadata_version,u.name owner_name,u.active owner_active,u.role owner_role FROM documents d LEFT JOIN knowledge_metadata m ON m.document_id=d.id LEFT JOIN users u ON u.id=m.owner_id WHERE d.store=? ORDER BY d.id DESC', (user['store'],)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            rev = current(db, row['id'])
            item.update(current_revision_id=rev['id'] if rev else None,current_version=rev['version'] if rev else None,source=rev['source'] if rev else None,
                        overdue=bool(row['review_due_at'] and row['review_due_at']<=now()),unowned=not row['owner_id'] or not row['owner_active'] or row['owner_role'] not in ('manager', 'admin'))
            results.append(item)
        return {'items': results, 'health': {'total':len(results),'unowned':sum(x['unowned'] for x in results),'overdue':sum(x['overdue'] for x in results),'no_current_version':sum(not x['current_revision_id'] for x in results)}}


@router.post('/api/manage/memory/{did}/metadata')
def metadata(did: int, data: Metadata, user=Depends(manager)):
    due = normalized_date(data.review_due_at) if data.review_due_at else None
    with connect(True) as db:
        document(db, did, user)
        old = db.execute('SELECT * FROM knowledge_metadata WHERE document_id=?', (did,)).fetchone()
        version = old['metadata_version'] if old else 0
        if version != data.metadata_version:
            fail(409, '负责人或复审计划已更新，请刷新后再修改')
        if data.owner_id is not None and not db.execute("SELECT 1 FROM users WHERE id=? AND store=? AND active=1 AND role IN ('manager','admin')", (data.owner_id,user['store'])).fetchone():
            fail(422, '负责人须为本门店有效主管或管理员')
        db.execute('INSERT INTO knowledge_metadata(document_id,owner_id,review_due_at) VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET owner_id=excluded.owner_id,review_due_at=excluded.review_due_at,metadata_version=metadata_version+1', (did,data.owner_id,due))
        record_event(db,did,None,user,'metadata_changed',{'before':dict(old) if old else None,'owner_id':data.owner_id,'review_due_at':due})
        audit(db,user,'knowledge_metadata_changed',did)
    return {'metadata_version':version+1}


@router.post('/api/manage/memory/{did}/review')
def review(did: int, data: Review, user=Depends(manager)):
    next_due = normalized_date(data.next_review_at)
    if next_due <= now():
        fail(422, '下次复审日期须在未来')
    with connect(True) as db:
        document(db,did,user)
        rev = current(db,did)
        if not rev or rev['id'] != data.revision_id:
            fail(409,'标准已变更或失效，请核对当前版本后复审')
        meta = db.execute('SELECT m.*,u.active,u.role FROM knowledge_metadata m LEFT JOIN users u ON u.id=m.owner_id WHERE document_id=?',(did,)).fetchone()
        if not meta or not meta['owner_id'] or not meta['active'] or meta['role'] not in ('manager', 'admin'):
            fail(409,'请先设置有效知识负责人')
        db.execute('UPDATE knowledge_metadata SET last_reviewed_at=?,review_due_at=?,metadata_version=metadata_version+1 WHERE document_id=?',(now(),next_due,did))
        record_event(db,did,rev['id'],user,'reviewed',{'note':data.note,'next_review_at':next_due})
        audit(db,user,'knowledge_reviewed',did)
    return {'ok':True}


@router.get('/api/manage/memory/{did}/history')
def history(did: int, user=Depends(manager)):
    with connect() as db:
        document(db,did,user)
        revs = [dict(r) for r in db.execute('SELECT id,version,state,source,change_reason,effective_at,expires_at,created_by,approved_by,approved_at FROM revisions WHERE document_id=? ORDER BY version DESC',(did,))]
        events = [{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT e.*,u.name actor_name FROM knowledge_events e JOIN users u ON u.id=e.actor WHERE document_id=? ORDER BY e.id DESC',(did,))]
        return {'revisions':revs,'events':events,'note':'旧版历史审批仍保留；细粒度事件从V0.3启用后开始记录。'}


@router.get('/api/manage/proposals')
def proposals(user=Depends(manager)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT p.*,d.title,q.question FROM knowledge_proposals p LEFT JOIN documents d ON d.id=p.document_id LEFT JOIN feedback f ON f.id=p.feedback_id LEFT JOIN queries q ON q.id=f.query_id WHERE p.store=? ORDER BY p.id DESC',(user['store'],))]


@router.post('/api/manage/proposals')
def propose(data: Proposal,user=Depends(manager)):
    with connect(True) as db:
        if data.document_id:
            document(db,data.document_id,user)
        if data.feedback_id:
            f = db.execute('SELECT f.*,q.revision_ids FROM feedback f JOIN queries q ON q.id=f.query_id WHERE f.id=? AND q.store=?',(data.feedback_id,user['store'])).fetchone()
            if not f or f['kind']=='helpful':
                fail(404,'可处理的问题反馈不存在')
            old = db.execute('SELECT id FROM knowledge_proposals WHERE feedback_id=?',(data.feedback_id,)).fetchone()
            if old:
                return {'id':old['id'],'existing':True}
            if f['state'] != 'open':
                fail(409,'该反馈已处理，不能再转提案')
            if data.document_id:
                ids=json.loads(f['revision_ids'])
                if not any(db.execute('SELECT 1 FROM revisions WHERE id=? AND document_id=?',(rid,data.document_id)).fetchone() for rid in ids):
                    fail(422,'选择的知识不在该反馈的原始引用中；新增标准请不关联旧知识')
        pid=db.execute('INSERT INTO knowledge_proposals(store,feedback_id,document_id,description,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(user['store'],data.feedback_id,data.document_id,data.description,user['id'],now(),now())).lastrowid
        if data.document_id:
            record_event(db,data.document_id,None,user,'proposal_created',{'proposal_id':pid,'description':data.description})
        audit(db,user,'proposal_created',pid)
    return {'id':pid,'existing':False}


@router.post('/api/manage/proposals/{pid}/draft')
def proposal_draft(pid: int,data: Draft,user=Depends(manager)):
    with connect(True) as db:
        p=db.execute('SELECT * FROM knowledge_proposals WHERE id=? AND store=?',(pid,user['store'])).fetchone()
        if not p:
            fail(404,'提案不存在')
        if p['state']!='open':
            fail(409,'提案已处理，请查看已关联的草稿或处理记录')
        if data.document_id != p['document_id']:
            fail(422,'草稿必须与提案关联相同知识；知识缺口应创建新系列')
        if not data.change_reason.strip():
            fail(422,'请记录本次变更原因')
        result=create_draft_record(db,data,user)
        db.execute("UPDATE knowledge_proposals SET state='draft_created',document_id=?,revision_id=?,updated_at=? WHERE id=?",(result['document_id'],result['id'],now(),pid))
        record_event(db,result['document_id'],result['id'],user,'proposal_drafted',{'proposal_id':pid})
    return result


@router.post('/api/manage/proposals/{pid}/decision')
def decision(pid: int,data: Decision,user=Depends(manager)):
    with connect(True) as db:
        p=db.execute('SELECT * FROM knowledge_proposals WHERE id=? AND store=?',(pid,user['store'])).fetchone()
        if not p:
            fail(404,'提案不存在')
        if data.action=='reject':
            if p['state']!='open':
                fail(409,'只能驳回尚未生成草稿的提案')
            state='rejected'
        else:
            active=current(db,p['document_id']) if p['document_id'] else None
            if p['state']!='draft_created' or not active or active['id']!=p['revision_id']:
                fail(409,'关联草稿尚未审核生效或已失效，不能确认完成')
            state='closed'
        db.execute('UPDATE knowledge_proposals SET state=?,decision_note=?,updated_at=? WHERE id=?',(state,data.note,now(),pid))
        if p['feedback_id']:
            db.execute("UPDATE feedback SET state='closed',resolution=? WHERE id=?",(data.note,p['feedback_id']))
        if p['document_id']:
            record_event(db,p['document_id'],p['revision_id'],user,'proposal_'+state,{'proposal_id':pid,'note':data.note})
        audit(db,user,'proposal_'+state,pid)
    return {'ok':True}


@router.post('/api/queries/{qid}/escalate')
def escalate(qid: int,data: Escalate,user=Depends(identity)):
    with connect(True) as db:
        q=db.execute('SELECT * FROM queries WHERE id=? AND user_id=? AND store=?',(qid,user['id'],user['store'])).fetchone()
        if not q:
            fail(404,'查询记录不存在')
        row=db.execute('SELECT feedback_id FROM escalations WHERE query_id=?',(qid,)).fetchone()
        if row:
            return {'feedback_id':row['feedback_id'],'existing':True}
        fid=db.execute("INSERT INTO feedback(query_id,user_id,kind,description,created_at) VALUES(?,?,'missing',?,?)",(qid,user['id'],data.note or '员工请求主管确认：'+q['question'],now())).lastrowid
        db.execute('INSERT INTO escalations VALUES(?,?,?)',(qid,fid,now()))
        audit(db,user,'query_escalated',qid)
    return {'feedback_id':fid,'existing':False}


@router.get('/api/my-requests')
def my_requests(user=Depends(identity)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT e.query_id,f.id feedback_id,q.question,f.state,f.resolution,f.created_at FROM escalations e JOIN queries q ON q.id=e.query_id JOIN feedback f ON f.id=e.feedback_id WHERE q.user_id=? AND q.store=? ORDER BY e.query_id DESC LIMIT 100',(user['id'],user['store']))]


@router.get('/api/citations/{rid}')
def citation(rid: int,user=Depends(identity)):
    from .main import card, get_revision, scope
    with connect() as db:
        doc,rev=get_revision(db,rid,user)
        active=current(db,doc['id'])
        if not scope(doc,user) or not active or active['id']!=rid:
            fail(404,'引用标准已更新、停用或无权查看，请重新查询')
        return card(doc,rev)

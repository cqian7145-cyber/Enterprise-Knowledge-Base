"""Service standards are approved knowledge content, without customer profiles."""
from fastapi import APIRouter, Depends
from .db import connect
from .main import accessible, identity, fail
from .operations import station_allowed

router=APIRouter()
SERVICE_KINDS={'service_script','complaint_card','service_scenario'}


def validate_service(kind,content):
    if kind not in SERVICE_KINDS:
        return
    s=content.service
    if not s or len(s.context.strip())<5 or len(s.response.strip())<5:
        fail(422,'服务内容须填写明确情境和经审核的标准回应，至少5字')
    if kind=='complaint_card' and (len(s.escalation_trigger.strip())<5 or not s.escalation_contact.strip()):
        fail(422,'客诉升级卡须填写升级条件和负责人岗位')
    if kind=='service_scenario' and (len(s.practice_prompt.strip())<5 or not s.assessment_points or any(not p.strip() for p in s.assessment_points)):
        fail(422,'培训场景须填写练习任务及实操评分要点')


@router.get('/api/service')
def standards(station: str,user=Depends(identity)):
    station_allowed(user,station)
    with connect() as db:
        items=[k for k in accessible(db,user,station) if k['kind'] in SERVICE_KINDS]
        return {'items':items,'definition':'仅展示当前生效、已审核且已授权的服务标准。场景可作为Academy材料；不保存顾客身份或顾客画像。'}

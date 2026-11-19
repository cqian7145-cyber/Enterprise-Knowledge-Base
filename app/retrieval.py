"""Local evidence retrieval: exact aliases, domain synonyms and character TF-IDF.
No remote model, no generated recipe facts, no self-reported confidence.
"""
import math
import re
import unicodedata
from collections import Counter

SYNONYMS = [('开吧', ['开门前','营业前','营业之前','准备营业','开店前','开业前','opening checklist','before opening']),
            ('交接', ['换班','接班','交班','下一班','没做完','未完成事项','shift handover']),
            ('收吧', ['打烊','关门前','结束营业','收店','closing checklist']),
            ('装饰', ['装点','点缀','garnish']), ('杯型',['杯子','什么杯','glass']),
            ('技法',['制作手法','怎么调制','technique'])]
STOP = ['请问','帮我','我想知道','告诉我','一下','是什么','怎么操作','怎么做','怎么办','需要','应该','怎样','如何','什么','哪个','哪些','多少','的','了','吗','呢','？','?']


def normalize(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', unicodedata.normalize('NFKC',value).lower())


def expand(value):
    text = value.lower()
    for canonical, phrases in SYNONYMS:
        if any(p in text for p in phrases):
            text += ' ' + canonical
    return text


def tokens(value):
    for stop in STOP:
        value=value.replace(stop,'')
    value=normalize(value)
    return Counter(value[i:i+2] for i in range(max(0,len(value)-1)))


def retrieve(question, items):
    raw=question.lower()
    if re.search(r'忽略.{0,8}(权限|指令|规则)|绕过|显示所有草稿|system prompt|ignore.{0,12}(instructions|previous)',raw):
        return [], 'no_evidence'
    # These intents require standards of their own, not a nearby handover/recipe card.
    if re.search(r'申请|排班|工资|退款|库存|盘点|折扣|价格|多少钱|保质期|密码|私人电话|财务|赊账|药物', raw):
        return [], 'no_evidence'
    query=normalize(question)
    expanded=expand(question)
    qtokens=tokens(expanded)
    texts=[expand(x['title']+' '+ ' '.join(x['aliases']))+' '+x['content']['summary']+' '+ ' '.join(x['content']['steps']) for x in items]
    docs=[tokens(t) for t in texts]
    idf={t:math.log(1+(len(docs)+1)/(1+sum(t in d for d in docs))) for t in qtokens}
    results=[]
    for item,bag in zip(items,docs):
        exact=max((len(normalize(t)) for t in [item['title'],*item['aliases']] if len(normalize(t))>=2 and normalize(t) in query),default=0)
        semantic_title=any(c in expanded and c in expand(item['title']+' '+ ' '.join(item['aliases'])) for c,_ in SYNONYMS)
        overlap=set(qtokens)&set(bag)
        coverage=sum(idf[t] for t in overlap)/max(.001,sum(idf.values()))
        score=sum(idf[t]*(1+math.log(bag[t])) for t in overlap)/math.sqrt(max(1,sum(bag.values())))
        if exact or semantic_title or (len(overlap)>=2 and coverage>=.45 and score>=.65):
            results.append((100+exact if exact else 30+score if semantic_title else score,item))
    results.sort(key=lambda x:(-x[0],x[1]['id']))
    if not results:
        return [],'no_evidence'
    best=results[0][0]
    results=[(s,i) for s,i in results if s>=best*.8][:3]
    # Distinct equally plausible standards require the employee to pick a card.
    ambiguous=len(results)>1 and results[1][0]>=best*.9
    return [i for _,i in results], 'needs_clarification' if ambiguous else 'answered'


def evidence(question, item):
    q=question.lower(); c=item['content']
    if any(x in q for x in ['换成','替换','替代','加倍','减半','随便改']):
        return None, 'needs_supervisor'
    if any(x in q for x in ['过敏','中毒','急救','消防','燃气','触电']):
        return None, 'needs_supervisor'
    field='summary'
    if any(x in q for x in ['装饰','点缀','装点','garnish']):field='garnish'
    elif any(x in q for x in ['杯','glass']):field='glass'
    elif any(x in q for x in ['技法','手法','technique']):field='technique'
    elif item['kind']=='recipe' and any(x in q for x in ['多少','用量','原料','配料','配方','ml','毫升']):field='ingredients'
    elif item['kind']=='sop' or any(x in q for x in ['步骤','怎么','流程','顺序']):field='steps'
    value=c.get(field)
    if not value:return None,'no_evidence'
    if isinstance(value,list):
        text='；'.join(x['name']+' '+x['amount']+' '+x['unit'] if isinstance(x,dict) else x for x in value)
    else:text=value
    return {'revision_id':item['revision_id'],'document_id':item['id'],'title':item['title'],'version':item['version'],'field':field,'text':text,'source':item['source'],'effective_at':item['effective_at'],'url':'/api/citations/'+str(item['revision_id'])},'answered'

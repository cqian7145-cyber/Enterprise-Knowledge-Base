"""NIGHTFALL demo records must be usable in actual desktop and touch Chromium."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from playwright.sync_api import expect


def login(app,name='nf_admin'):return app.login(name,password=app.server['password'])


def test_NF01_queries_station_and_every_module_page(app):
    admin=login(app);page=admin.page
    expect(page.locator('#environment-banner')).to_be_visible()
    expect(page.locator('#environment-banner')).to_contain_text('SIMULATED DATA / 模拟数据')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    admin.ask('夜幕金汤力');expect(page.locator('#answer')).to_contain_text('55 ml')
    admin.nav('knowledge');expect(page.locator('[data-open]')).to_have_count(len(admin.api('/knowledge?station=main')))
    for tab,text in [('training','我的培训'),('evidence','技能证据'),('service','Service'),('inventory','Inventory'),('flow','Flow'),('command','Command'),('insight','Insight'),('hq','HQ'),('agents','Agents'),('memory','知识维护'),('proposals','知识提案'),('team','培训管理'),('feedback','反馈中心'),('stats','使用看板')]:
        admin.nav(tab);expect(page.locator('#content h1')).to_contain_text(text)
        expect(page.locator('#content')).not_to_contain_text('服务暂不可用')
    page.locator('#station').select_option('vip');admin.idle();admin.nav('knowledge')
    expect(page.locator('#content')).to_contain_text('VIP 琥珀')
    staff=login(app,'nf_new');expect(staff.page.locator('#station option')).to_have_count(1)
    server=login(app,'nf_server1');server.nav('knowledge');expect(server.page.locator('.knowledge-card.recipe')).to_have_count(0)


def test_NF02_newcomer_history_and_live_learning(app):
    newcomer=login(app,'nf_new');newcomer.nav('evidence')
    expect(newcomer.page.locator('#content')).to_contain_text('当前课程已通过')
    expect(newcomer.page.locator('#content')).to_contain_text('需再次练习')
    retry=login(app,'nf_retry');retry.nav('evidence');expect(retry.page.locator('#content')).to_contain_text('待主管实操')
    idle=login(app,'nf_idle');idle.nav('training');aid=app.server['manifest']['stories']['idle']
    idle.page.locator(f'[data-training="{aid}"]').click();idle.idle()
    for group in idle.page.locator('#exam fieldset').all():group.locator('input[type=radio]').first.check()
    # The form uses one fieldset per quiz question, verified against the actual DOM.
    if not idle.page.locator('#exam fieldset').count():
        for name in ['answer_0','answer_1','answer_2']:idle.page.locator(f'#exam input[name="{name}"]').first.check()
    idle.page.locator('#exam').get_by_role('button',name='提交测验',exact=True).click();idle.idle()
    expect(idle.page.locator('#notice')).to_contain_text('100')
    expect(idle.page.locator('#content')).to_contain_text('待主管实操')
    bar=login(app,'nf_bar1');bar.nav('training');old=app.server['manifest']['stories']['old_assignment']
    expect(bar.page.locator(f'[data-training="{old}"]')).to_be_disabled()


def test_NF03_equipment_evidence_closes_computed_command(app):
    lead=login(app,'nf_lead');admin=login(app);sid=app.server['manifest']['stories']['open_incident']
    lead.nav('flow');lead.page.locator(f'[data-flow-incident="{sid}"]').click();lead.idle()
    lead.page.locator('#incident-resolve [name="resolution"]').fill('SIMULATED DATA；演示维护负责人已核对设备状态')
    lead.page.locator('#incident-resolve [name="evidence"]').fill('SIM-NF-BROWSER-REPAIR；合成复检凭证')
    lead.page.get_by_role('button',name='提交处理，等待主管确认',exact=True).click();lead.idle()
    admin.nav('command');assert sid in [r['id'] for r in admin.api('/manage/command')['incidents']]
    admin.nav('flow');admin.page.locator(f'[data-flow-incident="{sid}"]').click();admin.idle()
    admin.page.get_by_role('button',name='确认关闭异常',exact=True).click();admin.idle()
    admin.nav('command');assert sid not in [r['id'] for r in admin.api('/manage/command')['incidents']]
    expect(admin.page.locator('#content')).not_to_contain_text('制冰机状态指示异常')


def test_NF04_inventory_report_download_and_gap(app,tmp_path):
    admin=login(app);page=admin.page;stories=app.server['manifest']['stories'];rid=stories['report']
    admin.nav('inventory');expect(page.locator('#content')).to_contain_text('GIN');assert len(admin.api('/inventory/catalog')['skus'])==32
    admin.nav('insight');page.locator(f'[data-report-open="{rid}"]').click();admin.idle()
    expect(page.locator('#modal-body')).to_contain_text('依据完整，可复算')
    expect(page.locator('#modal-body')).to_contain_text('-180')
    expect(page.locator('#modal-body')).to_contain_text('不等于净利润')
    page.locator(f'[data-report-recalculate="{rid}"]').click();admin.idle()
    expect(page.locator('#notice')).to_contain_text('复算一致')
    with page.expect_download() as download:page.locator(f'[data-report-export="{rid}"]').click()
    target=tmp_path/'download.json';download.value.save_as(target)
    data=json.loads(target.read_text(encoding='utf8'));assert data['result']['complete'] and data['inputs']['sales']
    page.get_by_role('button',name='关闭',exact=True).click()
    page.locator(f'[data-report-open="{stories["gap_report"]}"]').click();admin.idle()
    expect(page.locator('#modal-body')).to_contain_text('待补数据')
    expect(page.locator('#modal-body')).to_contain_text('缺少销售时刻有效的历史单位成本')


def test_NF05_hq_signed_draft_requires_actual_review(app):
    admin=login(app);page=admin.page;admin.nav('hq')
    expect(page.locator('#content')).to_contain_text('本店草稿')
    expect(page.locator('#content')).to_contain_text('本店已生效')
    delivery=next(d for d in admin.api('/hq')['deliveries'] if d['store']=='nf-downtown')
    rid=delivery['local_revision_id'];admin.nav('manage')
    row=page.locator('#content .list-row').filter(has_text='总部统一迎宾服务标准')
    row.get_by_role('button',name='提交审核',exact=True).click();admin.idle()
    row.get_by_role('button',name='审核发布',exact=True).click()
    now=(datetime.now(timezone(timedelta(hours=8)))-timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M')
    page.locator('#publish-form [name="effective_at"]').fill(now)
    page.locator('#publish-form').get_by_role('button',name='确认发布',exact=True).click();admin.idle()
    admin.nav('hq');assert next(d for d in admin.api('/hq')['deliveries'] if d['store']=='nf-downtown')['rollout']=='effective'
    page.locator('#store-switch').select_option('nf-riverside');admin.idle();admin.nav('service')
    expect(page.locator('#content')).to_contain_text('总部统一迎宾服务标准')
    page.get_by_role('button',name='返回本店',exact=True).click();admin.idle()


def test_NF06_agent_blocked_source_and_employee_completion(app):
    admin=login(app);page=admin.page;s=app.server['manifest']['stories'];admin.nav('agents')
    page.locator(f'[data-agent-plan="{s["stale_plan"]}"]').click();admin.idle()
    page.get_by_role('button',name='按批准计划生成待办',exact=True).click();admin.idle()
    page.get_by_role('button',name='确认生成七项待办',exact=True).click();admin.idle()
    expect(page.locator('#notice')).to_contain_text('当前有效配方')
    assert len(admin.api('/tasks?station=main'))==7
    page.get_by_role('button',name='关闭',exact=True).click()
    worker=login(app,'nf_bar1');worker.nav('agents')
    worker.page.locator('[data-agent-task-close]').first.click();worker.idle()
    worker.page.locator('#agent-task-close-form [name="evidence"]').fill('SIMULATED DATA；浏览器演示核对合成准备记录，不构成上新许可')
    worker.page.locator('#agent-task-close-form button[type="submit"],#agent-task-close-form button.primary').click();worker.idle()
    tasks=admin.api('/tasks?station=main');assert sum(t['state']=='closed' for t in tasks)==3
    assert len(tasks)==7

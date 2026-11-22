"""Only synthetic users and temporary SQLite files may reach the browser harness."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from app.db import connect,encode,initialize,password_hash,now,ROOT
from app.cli import seed

PASSWORD='E2E-only-Password-2026'
NEW_PASSWORD='E2E-changed-Password-2026'


def pytest_generate_tests(metafunc):
    if 'viewport_profile' in metafunc.fixturenames:
        selected=metafunc.config.getoption('--e2e-profile')
        metafunc.parametrize('viewport_profile',['desktop','mobile'] if selected=='all' else [selected])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    result=yield
    report=result.get_result()
    setattr(item,'rep_'+report.when,report)


@pytest.fixture(scope='session')
def chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.fail('Install requirements-e2e.lock and Chromium; E2E must not silently skip.')
    local=ROOT/'.browsers'
    if local.is_dir():os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(local))
    with sync_playwright() as driver:
        browser=driver.chromium.launch(channel='chromium',headless=True)
        yield browser
        browser.close()


@pytest.fixture
def test_server(tmp_path,monkeypatch,request):
    database=(tmp_path/'synthetic-only.sqlite').resolve()
    assert database.is_relative_to(tmp_path.resolve()) and database!= (ROOT/'data'/'baros.sqlite').resolve()
    monkeypatch.setenv('BAROS_DB',str(database))
    monkeypatch.setenv('BAROS_SECURE_COOKIE','0')
    initialize()
    with connect(True) as db:
        hashed=password_hash(PASSWORD)
        accounts=[('admin','测试主管','admin','pilot','bartender',['main','terrace'],0),('staff','测试新人','staff','pilot','bartender',['main'],0),('outsider','测试外店','admin','other','bartender',['main'],0),('server','测试接班人','staff','pilot','server',['main'],0),('newstaff','测试首次登录','staff','pilot','bartender',['main'],1)]
        for username,name,role,store,job,stations,must in accounts:
            db.execute('INSERT INTO users(username,name,password,role,store,job,stations,must_change_password) VALUES(?,?,?,?,?,?,?,?)',(username,name,hashed,role,store,job,encode(stations),must))
        seed(db)
        # Deliberately identical recipe names with different authorized station scope.
        db.execute('UPDATE documents SET stations=? WHERE id=1',(encode(['main']),))
        original=dict(db.execute('SELECT * FROM documents WHERE id=1').fetchone())
        content=json.loads(db.execute('SELECT content FROM revisions WHERE id=1').fetchone()[0])
        terrace={**content,'ingredients':[{**i,'amount':'99'} if index==0 else i for index,i in enumerate(content['ingredients'])]}
        did=db.execute("INSERT INTO documents(store,title,kind,jobs,stations,aliases) VALUES('pilot','金汤力','recipe',?,?,?)",(encode(['bartender']),encode(['terrace']),encode(['G&T']))).lastrowid
        db.execute("INSERT INTO revisions(document_id,version,state,content,source,effective_at,created_by,approved_by,approved_at) VALUES(?,1,'published',?,'纯虚构露台测试标准',?,1,1,?)",(did,encode(terrace),now(),now()))
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()
    base=f'http://127.0.0.1:{port}'
    log_path=tmp_path/'server.log'
    env={**os.environ,'BAROS_DB':str(database),'BAROS_SECURE_COOKIE':'0','PYTHONIOENCODING':'utf8'}
    with log_path.open('wb') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if process.poll() is not None:pytest.fail('Isolated server exited: '+log_path.read_text(encoding='utf8',errors='replace'))
                try:
                    if httpx.get(base+'/api/health',timeout=1,trust_env=False).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:pytest.fail('Isolated test server did not become healthy')
            yield {'base':base,'database':database,'log':log_path,'document':original,'content':content}
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


class Actor:
    def __init__(self,context,page):
        self.context=context;self.page=page;self.pending=set();self.last_network=time.monotonic()
        page.on('request',self._started)
        page.on('requestfinished',self._finished)
        page.on('requestfailed',self._finished)
    def _started(self,request):
        self.pending.add(request);self.last_network=time.monotonic()
    def _finished(self,request):
        self.pending.discard(request);self.last_network=time.monotonic()
    def idle(self):
        # load-state networkidle can already be true before an AJAX click starts.
        # Observe the real page request lifecycle, including subsequent render reads.
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.page.wait_for_timeout(50)
            if not self.pending and time.monotonic()-self.last_network>=.25:return
        raise AssertionError('Page requests did not settle: '+str([r.url for r in self.pending]))
    def nav(self,page):self.page.locator('[data-page="'+page+'"]').click();self.idle()
    def api(self,path,body=None,expected=200,headers=None):
        extra=dict(headers or {})
        if body is not None:
            me=self.context.request.get('/api/me')
            if me.status==200:extra['X-CSRF-Token']=me.json()['csrf']
            response=self.context.request.post('/api'+path,data=body,headers=extra)
        else:response=self.context.request.get('/api'+path,headers=extra)
        assert response.status==expected,(path,response.status,response.text())
        return response.json() if response.headers.get('content-type','').startswith('application/json') else response.text()
    def ask(self,question):
        self.page.locator('#ask [name="question"]').fill(question)
        self.page.get_by_role('button',name='查询标准',exact=True).click();self.idle()


@pytest.fixture
def app(chromium,test_server,viewport_profile,request):
    from playwright.sync_api import expect
    expect.set_options(timeout=8000)
    if not hasattr(request.config,'_baros_e2e_run_id'):
        request.config._baros_e2e_run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory=Path(os.getenv('BAROS_E2E_ARTIFACTS',str(ROOT/'test-results'/'e2e')))/request.config._baros_e2e_run_id/re.sub(r'[^a-zA-Z0-9_.-]','_',request.node.nodeid)
    directory.mkdir(parents=True,exist_ok=True)
    records=[];errors=[];network=[];actors=[]
    class Application:
        server=test_server
        profile=viewport_profile
        def login(self,username,password=PASSWORD,forced=False):
            options={'viewport':{'width':1440,'height':1000}} if viewport_profile=='desktop' else {'viewport':{'width':390,'height':844},'is_mobile':True,'has_touch':True,'device_scale_factor':1}
            context=chromium.new_context(base_url=test_server['base'],locale='zh-CN',timezone_id='Asia/Shanghai',**options)
            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(20000)
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page=context.new_page();actor=Actor(context,page);actors.append((username,actor))
            page.on('pageerror',lambda error:errors.append({'actor':username,'error':str(error)}))
            page.on('console',lambda message:records.append({'actor':username,'type':message.type,'text':message.text}))
            page.on('requestfailed',lambda req:network.append({'actor':username,'url':req.url,'method':req.method,'failure':req.failure}))
            page.goto('/')
            page.get_by_label('账号',exact=True).fill(username)
            page.get_by_label('密码',exact=True).fill(password)
            page.get_by_role('button',name='登录',exact=True).click()
            expect(page.get_by_role('heading',name='设置你的新密码' if forced else '今天需要查什么？',exact=True)).to_be_visible()
            actor.idle()
            return actor
    application=Application()
    yield application
    failed=bool(getattr(request.node,'rep_call',None) and request.node.rep_call.failed) or bool(errors)
    for index,(username,actor) in enumerate(actors):
        try:
            actor.page.screenshot(path=str(directory/f'{index}-{username}.png'),full_page=True)
            actor.context.tracing.stop(path=str(directory/f'{index}-{username}-trace.zip') if failed else None)
        except Exception as exc:records.append({'capture_error':str(exc)})
        finally:actor.context.close()
    metadata={'case':request.node.nodeid,'profile':viewport_profile,'browser':chromium.version,'synthetic_data_only':True,'status':'failed' if failed else 'passed','urls':[{'actor':name,'url':actor.page.url} for name,actor in actors],'console':records,'page_errors':errors,'failed_requests':network,'reproduce':f'python -m pytest --run-e2e --e2e-profile={viewport_profile} "{request.node.nodeid.split("[")[0]}"'}
    (directory/'observations.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
    (directory/'server.log').write_text(test_server['log'].read_text(encoding='utf8',errors='replace'),encoding='utf8')
    assert not errors,errors

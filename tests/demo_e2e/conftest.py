"""Real Chromium uses a copy of the CLI-built demo, never the workspace database."""
import importlib.util
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import httpx
import pytest
from app.db import ROOT
from app.dbtools import snapshot
from app.demo import seed_realistic_demo

spec=importlib.util.spec_from_file_location('baros_browser_harness',Path(__file__).parents[1]/'e2e'/'conftest.py')
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
chromium=shared.chromium
app=shared.app
pytest_generate_tests=shared.pytest_generate_tests
pytest_runtest_makereport=shared.pytest_runtest_makereport


@pytest.fixture(scope='session')
def nightfall_source(tmp_path_factory):
    target=tmp_path_factory.mktemp('browser-nightfall')/'source-demo.sqlite'
    password=secrets.token_urlsafe(24)
    manifest=seed_realistic_demo(target,password,environment='demo',confirm='SIMULATED-DATA')
    return target,password,manifest


@pytest.fixture
def test_server(nightfall_source,tmp_path):
    source,password,manifest=nightfall_source;database=tmp_path/'browser-demo.sqlite';snapshot(source,database)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()
    base=f'http://127.0.0.1:{port}';log_path=tmp_path/'server.log'
    with log_path.open('wb') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env={**os.environ,'BAROS_DB':str(database),'BAROS_SECURE_COOKIE':'0','PYTHONIOENCODING':'utf8'},stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if process.poll() is not None:pytest.fail(log_path.read_text(encoding='utf8',errors='replace'))
                try:
                    if httpx.get(base+'/api/health',timeout=1,trust_env=False).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:pytest.fail('Demo server did not start')
            yield dict(base=base,database=database,log=log_path,password=password,manifest=manifest)
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

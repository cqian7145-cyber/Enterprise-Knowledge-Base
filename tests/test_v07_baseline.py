"""Release identity and the real CLI path, confined to fresh synthetic files."""
import hashlib
import json
import secrets
import sqlite3
import subprocess
import sys
from fastapi.testclient import TestClient
from app import __version__
from app.db import ROOT
from app.main import app


def test_release_identity_and_normal_database_label(tmp_path,monkeypatch):
    target=tmp_path/'normal.sqlite';monkeypatch.setenv('BAROS_DB',str(target))
    with TestClient(app) as client:
        assert client.get('/openapi.json').json()['info']['version']==__version__=='0.7.0-rc.1'
        assert client.get('/api/environment').json()=={'simulated':False}
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='demo_manifest'").fetchone()


def test_cli_first_import_repeat_and_environment_isolation(tmp_path):
    target=tmp_path/'cli-nightfall-demo.sqlite';normal=tmp_path/'normal.sqlite'
    with sqlite3.connect(normal) as db:db.execute('CREATE TABLE user_data(value TEXT)');db.execute("INSERT INTO user_data VALUES('synthetic sentinel')")
    before=hashlib.sha256(normal.read_bytes()).hexdigest();password=secrets.token_urlsafe(24)
    # Exercise argparse + getpass + cli.main in a fresh process. Only the secret input
    # adapter is automated; validation, auth, transactions and all APIs remain real.
    script="""import sys,json,runpy,getpass,os
p=json.load(sys.stdin)
os.environ['BAROS_DB']=p['normal']
values=iter([p['password'],p['password']])
getpass.getpass=lambda prompt:next(values)
sys.argv=['app.cli','seed-realistic-demo','--database',p['target'],'--environment','demo','--confirm','SIMULATED-DATA']
runpy.run_module('app.cli',run_name='__main__')
"""
    result=subprocess.run([sys.executable,'-X','utf8','-c',script],input=json.dumps({'normal':str(normal),'target':str(target),'password':password}),cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    assert result.returncode==0,result.stderr
    manifest=json.loads(result.stdout);assert not manifest['unchanged'] and manifest['counts']['documents']==72
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    again=subprocess.run([sys.executable,'-X','utf8','-m','app.cli','seed-realistic-demo','--database',str(target),'--environment','demo','--confirm','SIMULATED-DATA'],cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf8')
    assert again.returncode==0 and json.loads(again.stdout)['unchanged']
    assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
    assert hashlib.sha256(normal.read_bytes()).hexdigest()==before
    assert password not in result.stdout and password not in result.stderr

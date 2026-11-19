"""Consistent snapshots; restore only to a NEW isolated database path."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from .db import ROOT


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('来源和目标不能相同')
    if not source.is_file():
        raise ValueError('来源数据库不存在')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite of an existing/live DB.
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('来源数据库完整性检查失败')
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('目标数据库完整性检查失败')
                if dst.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('目标数据库外键检查失败')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def backup(destination):
    return snapshot(os.getenv('BAROS_DB', str(ROOT / 'data' / 'baros.sqlite')), destination)

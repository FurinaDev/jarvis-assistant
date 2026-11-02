'''Basit günlük: DATA_DIR/jarvis.log + konsol.

Bir kullanıcı sorun yaşadığında "jarvis.log dosyasını gönder" diyebilmek için.
API anahtarları asla yazılmaz.
'''

from __future__ import annotations
import datetime as dt
import sys
import threading
from . import paths
_lock = threading.Lock()
MAX_BYTES = 2000000

def log(*parts: 'object') -> 'None':
    line = f'{dt.datetime.now():%Y-%m-%d %H:%M:%S} ' + ' '.join((str(p) for p in parts))
    with _lock:
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass
        try:
            paths.ensure_dirs()
            if paths.LOG_FILE.exists() and paths.LOG_FILE.stat().st_size > MAX_BYTES:
                paths.LOG_FILE.replace(paths.LOG_FILE.with_suffix('.old.log'))
            with paths.LOG_FILE.open('a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        except OSError:
            pass


'''Hızlı notlar — sesle ("not al: yarın süt al") ya da Notlar panelinden.

Kullanıcı verisi klasöründe notes.json olarak saklanır.
'''

from __future__ import annotations
import datetime as dt
import json
import threading
import time
from typing import Any, Callable
from . import paths
MAX_NOTES = 200
_lock = threading.Lock()
on_change: 'Callable[[], None]' = lambda: None

def _file():
    return paths.DATA_DIR / 'notes.json'

def load() -> 'list[dict[str, Any]]':
    try:
        data = json.loads(_file().read_text(encoding='utf-8'))
        if isinstance(data, list):
            return [n for n in data if isinstance(n, dict) if n.get('text')]
    except (OSError, ValueError):
        pass
    return []

def _save(items: 'list[dict[str, Any]]') -> 'None':
    paths.ensure_dirs()
    tmp = _file().with_suffix('.tmp')
    tmp.write_text(json.dumps(items[-MAX_NOTES:], ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(_file())

def add(text: 'str') -> 'dict[str, Any] | None':
    text = ' '.join((text or '').split())[:300]
    if not text:
        return
    with _lock:
        items = load()
    note_id = max([int(time.time() * 1000)] + [n['id'] + 1 for n in items if isinstance(n.get('id'), int)])
    note = {'id': note_id, 'text': text, 'at': dt.datetime.now().isoformat(timespec='minutes')}
    items.append(note)
    _save(items)
    on_change()
    return note

def update(note_id: 'Any', text: 'str') -> 'bool':
    '''Notun metnini değiştirir (büyük Notlar görünümünde düzenleme).'''

    text = ' '.join((text or '').split())[:300]
    if not text:
        return False
    with _lock:
        items = load()
    hit = [n for n in items if str(n['id']) == str(note_id)]
    if not hit:
        return False
    hit[0]['text'] = text
    _save(items)
    on_change()
    return True

def delete(ref: 'Any') -> 'list[dict[str, Any]]':
    '''ref: not kimliği, "son", sıra numarası (1 = en yeni) ya da metinden bir parça.'''

    with _lock:
        items = load()
        newest = list(reversed(items))
        key = str(ref or '').strip().casefold()
        if isinstance(ref, int) and ref > 10000:
            gone = [n for n in items if n['id'] == ref]
        elif key in ('son', 'sonuncu', 'en son', 'last'):
            gone = newest[:1]
        elif key.isdigit() and int(key) > 10000:
            gone = [n for n in items if n['id'] == int(key)]
        elif key.isdigit():
            idx = int(key) - 1
            gone = newest[idx:idx + 1] if 0 <= idx < len(newest) else []
        else:
            gone = [n for n in items if key if key in n['text'].casefold()]
    if gone:
        _save([n for n in items if n not in gone])
    if gone:
        on_change()
    return gone

def clear() -> 'int':
    with _lock:
        count = len(load())
        _save([])
    on_change()
    return count

TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']

def _when(stamp: 'str', long: 'bool'=False) -> 'str':
    try:
        at = dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return ''
    if long:
        day = 'Bugün' if at.date() == dt.date.today() else f'{at.day} {TR_MONTHS[at.month]}'
        return f'{day} {at:%H:%M}'
    if at.date() == dt.date.today():
        return at.strftime('%H:%M')
    return at.strftime('%d.%m')

def summary(limit: 'int'=10) -> 'str':
    items = list(reversed(load()))[:max(1, limit)]
    if not items:
        return 'Hiç not yok.'
    return ' '.join((f'{i}. {n['text']}' for i, n in enumerate(items, 1)))

def panel() -> 'dict[str, Any]':
    items = list(reversed(load()))
    return {'key': 'notes', 'label': 'NOTLAR', 'kind': 'notes', 'count': len(items), 'items': [{'id': n['id'], 'text': n['text'], 'at': _when(n.get('at', '')), 'when': _when(n.get('at', ''), long=True)} for n in items]}


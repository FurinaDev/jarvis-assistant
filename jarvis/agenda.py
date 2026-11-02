"""Kişisel gündem: bugünün ve bu haftanın takvimi, anımsatıcılar, notlar.

Kendiliğinden konuşmada AI modeli rastgele bilgi vermez, kullanıcının kendi
gündeminden söz eder: yaklaşan toplantı, geciken anımsatıcı, bekleyen not.

Takvim ve anımsatıcılar yalnızca kullanıcı ilgili paneli açıp izin verdiyse
okunur (Ayarlar'daki panel dokunuşu: `calendar_panel`, `reminders_panel`).
Böylece durup dururken bir macOS izin penceresi açılmaz. Okunamayan kaynak
atlanır; notlar her zaman vardır. Windows'ta kaynak JARVIS'in yerel ajandası
(jarvis.win_agenda): izin gerekmez, hep okunur.

`topics()` gündemi önem sırasına dizer; kendiliğinden konuşma her seferinde
yakın zamanda değinilmemiş olanlardan birini seçer.
"""

from __future__ import annotations
import datetime as dt
import threading
import time
from dataclasses import dataclass
from typing import Any
from . import (notes, paths, settings)
REFRESH = 180.0
SOON = 3600
TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
_cache: 'dict[str, Any]' = {'at': 0.0, 'events': None, 'reminders': None}
_lock = threading.Lock()

@dataclass
class Topic:
    key: 'str'
    kind: 'str'
    text: 'str'
    rank: 'int'
    start: 'float' = 0.0

def _events() -> 'list[dict] | None':
    if paths.IS_WIN:
        from . import win_agenda
        start = dt.datetime.combine(dt.date.today(), dt.time())
        return win_agenda.events_between(start, start + dt.timedelta(days=7))
    if not paths.IS_MAC or not settings.get('calendar_panel'):
        return
    from .actions import calendar as cal
    ok, raw = cal._run_helper('week', timeout=20)
    parsed, _detail, events = cal._parse_payload(raw) if ok else (False, raw, [])
    if parsed:
        return events

def _reminders() -> 'list[dict] | None':
    if paths.IS_WIN:
        from . import win_agenda
        return win_agenda.reminder_rows('all', 20)
    if not paths.IS_MAC or not settings.get('reminders_panel'):
        return
    from .actions import reminders as rem
    from .actions.calendar import _run_helper
    ok, raw = _run_helper('reminders_list', payload={'query': 'all', 'limit': 20, 'list_name': ''}, timeout=20)
    parsed, _detail, rows = rem._parse_payload(raw) if ok else (False, raw, [])
    if parsed:
        return rows

def invalidate() -> 'None':
    '''Takvim ya da anımsatıcı değişti: bir sonraki snapshot yeniden okusun (yaklaşan etkinlik haberi kaçmasın).'''

    with _lock:
        _cache['at'] = 0.0

def snapshot(force: 'bool'=False) -> 'dict[str, Any]':
    '''{"events": [...] | None, "reminders": [...] | None, "notes": [...]} — None: erişim yok.'''

    with _lock:
        fresh = _cache['at'] and time.monotonic() - _cache['at'] < REFRESH
    if force or not fresh:
        events, reminders = _events(), _reminders()
        with _lock:
            _cache.update(at=time.monotonic(), events=events, reminders=reminders)
    with _lock:
        return {'events': _cache['events'], 'reminders': _cache['reminders'], 'notes': list(reversed(notes.load()))[:6]}

def _day(when: 'dt.datetime', now: 'dt.datetime') -> 'str':
    days = (when.date() - now.date()).days
    if days == 0:
        return 'bugün'
    if days == 1:
        return 'yarın'
    if days == -1:
        return 'dün'
    if 1 < days < 7:
        return f'{TR_DAYS[when.weekday()]} ({when.day} {TR_MONTHS[when.month]})'
    return f'{when.day} {TR_MONTHS[when.month]}'

def _in(seconds: 'float') -> 'str':
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f'{minutes} dakika sonra'
    hours, rest = divmod(minutes, 60)
    if rest:
        return f'{hours} saat {rest} dakika sonra'
    return f'{hours} saat sonra'

def topics(snap: 'dict[str, Any]', now: 'dt.datetime | None'=None) -> 'list[Topic]':
    '''Gündem, önem sırasıyla.'''

    now = now or dt.datetime.now()
    ts = now.timestamp()
    out = []
    for e in snap.get('events') or []:
        start, end = dt.datetime.fromtimestamp(e['start_ts']), dt.datetime.fromtimestamp(e['end_ts'])
        if e['end_ts'] < ts:
            continue
        place = f' ({e['location']})' if e.get('location') else ''
        title = e['title']
        if e['all_day']:
            text, rank = f'{_day(start, now)} (tüm gün) — {title}{place}', 3 if start.date() == now.date() else 6
        elif e['start_ts'] <= ts:
            text, rank = f'şu an sürüyor ({start:%H:%M}–{end:%H:%M}) — {title}{place}', 5
        elif e['start_ts'] - ts <= SOON:
            text, rank = f"{_in(e['start_ts'] - ts)}, {start:%H:%M}'de — {title}{place}", 0
        elif start.date() == now.date():
            text, rank = f'bugün {start:%H:%M} — {title}{place}', 3
        elif (start.date() - now.date()).days == 1:
            text, rank = f'yarın {start:%H:%M} — {title}{place}', 6
        else:
            text, rank = f'{_day(start, now)} {start:%H:%M} — {title}{place}', 8
        out.append(Topic(f'ev:{title}:{e['start_ts']}', 'event', 'takvim: ' + text, rank, e['start_ts']))
        continue
    for r in snap.get('reminders') or []:
        title = r['title']
        where = f' [{r['list_name']} listesi]' if r.get('list_name') else ''
        if r['due_ts']:
            due = dt.datetime.fromtimestamp(r['due_ts'])
            clock = '' if r.get('all_day') else f' {due:%H:%M}'
            if r['due_ts'] + (86400 if r.get('all_day') else 0) < ts:
                text, rank = f"gecikmiş ({_day(due, now)}{clock}'di) — {title}", 1
            elif due.date() == now.date():
                text, rank = f'bugün{clock} — {title}', 2
            else:
                text, rank = f'{_day(due, now)}{clock} — {title}', 7
        else:
            text, rank = f'tarihsiz — {title}', 10
        out.append(Topic(f'rem:{title}', 'reminder', f'anımsatıcı: {text}{where}', rank))
        continue
    for i, n in enumerate(snap.get('notes') or []):
        when = notes._when(n.get('at', ''), long=True)
        out.append(Topic(f'note:{n['id']}', 'note', f'not: «{n['text']}»' + (f' ({when})' if when else ''), 9 + (i > 1)))
    out.sort(key=(lambda t: (t.rank, t.start)))
    return out

def block(snap: 'dict[str, Any]', items: 'list[Topic]') -> 'str':
    '''Nota giden özet: modele gündemin tamamı (en önemli 10 madde) ve neyin okunamadığı.'''

    lines = [f'- {t.text}' for t in items[:10]]
    missing = [name for name, key in (('takvim', 'events'), ('anımsatıcılar', 'reminders'))
         if snap.get(key) is None]
    if missing and paths.IS_MAC:
        lines.append(f'- ({' ve '.join(missing)} okunamıyor; izin verilmemiş)')
    if not items:
        lines.append('- gündemde kayıtlı bir şey yok')
    return '[KULLANICININ GÜNDEMİ]\n' + '\n'.join(lines)

def status() -> 'dict[str, Any]':
    '''Ayarlar › Konuşma: hangi kaynak okunabiliyor. off = panel hiç açılmadı, denied = izin yok,
    na = bu işletim sisteminde yok (gösterilmez).'''

    snap = snapshot(force=True)
    def state(flag: 'str', value: 'list | None') -> 'str':
        if paths.IS_WIN:
            return 'ok'
        if not paths.IS_MAC:
            return 'na'
        if not settings.get(flag):
            return 'off'
        return 'denied' if value is None else 'ok'

    return {'calendar': state('calendar_panel', snap['events']), 'events': len(snap['events'] or []), 'reminders': state('reminders_panel', snap['reminders']), 'reminder_count': len(snap['reminders'] or []), 'notes': len(notes.load())}

def soon(snap: 'dict[str, Any]', within: 'float', now: 'float | None'=None) -> 'list[dict]':
    '''`within` saniye içinde başlayacak (tüm gün olmayan) etkinlikler.'''

    now = now or time.time()
    if 0 < e['start_ts'] - now <= within:
        pass
    return snap.get('events') or []


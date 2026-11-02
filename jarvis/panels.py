"""Ana ekrandaki panellerin verisi.

Hiçbiri yapay zeka çağırmaz; hepsi yerel ya da ücretsiz kaynaklardan gelir.
Her panel bir sözlüktür: `key`, `label`, `kind` (HUD'daki çizim türü) ve
çizime özel alanlar. Bir panel hata verirse boş ekran yerine durumunu söyler.

Takvim ve Anımsatıcılar ilk açılışta izin penceresi çıkarmasın diye
kullanıcı panele tıklayana kadar kilitlidir (`*_panel` ayarı).
"""

from __future__ import annotations
import datetime as dt
import threading
import time
from typing import Any
import psutil
import requests
from . import (geo, paths, settings, wx)
if paths.IS_WIN:
    from . import win_agenda
_WEATHER: 'dict[str, Any]' = {'at': 0.0, 'data': None, 'for': None}
WEATHER_FRESH = 600.0
_lock = threading.Lock()
_cpu_primed = False

def disk_percent() -> 'float':
    '''Diskin gerçek doluluğu. macOS'ta "/" salt okunur sistem bölümüdür (APFS); onun "kullanılan"ı
    yalnızca sistem dosyaları (%10 gibi yanıltıcı). Bütün kapsayıcının boş alanından hesaplanır.'''

    from .details import _root
    d = psutil.disk_usage(_root())
    if d.total:
        return (d.total - d.free) / d.total * 100
    return 0.0

def system() -> 'dict[str, Any]':
    global _cpu_primed
    cpu = psutil.cpu_percent(interval=None if _cpu_primed else 0.4)
    _cpu_primed = True
    ram = psutil.virtual_memory().percent
    disk = disk_percent()
    rows = [['RAM', f'%{ram:.0f}'], ['DİSK', f'%{disk:.0f} dolu']]
    battery = psutil.sensors_battery()
    if battery is not None:
        plug = ' · şarjda' if battery.power_plugged else ''
        rows.insert(0, ['PİL', f'%{battery.percent:.0f}{plug}'])
    return {'key': 'system', 'label': 'SİSTEM', 'kind': 'meter', 'value': f'{cpu:.0f}', 'unit': 'CPU %', 'ratio': round(cpu / 100, 3), 'rows': rows}

def _fetch_weather(query: 'str', place: 'str', spot: 'dict[str, Any] | None') -> 'dict[str, Any]':
    data = wx.panel(wx.fetch(query), place)
    if spot:
        data.update(lat=spot['lat'], lon=spot['lon'], zoom=spot.get('zoom') or 13, country=spot.get('country') or data.get('country', ''))
    return data

def weather(force: 'bool'=False) -> 'dict[str, Any]':
    location = str(settings.get('location') or '').strip()
    spot = geo.chosen()
    query = geo.coords(spot) if spot else location
    place = spot['label'] if spot else location
    with _lock:
        fresh = time.time() - _WEATHER['at'] < WEATHER_FRESH and _WEATHER['for'] == query
        if fresh and not force and _WEATHER['data']:
            return _WEATHER['data']
    try:
        data = _fetch_weather(query, place, spot)
    except Exception:
        old = _WEATHER['data'] if _WEATHER['for'] == query else None
        data = old or {'key': 'weather', 'label': 'HAVA', 'kind': 'weather', 'value': '—', 'place': place or 'Konum', 'detail': 'bağlantı yok', 'glyph': '·', 'day': True}
    with _lock:
        _WEATHER.update({'at': time.time(), 'data': data, 'for': query})
    return data

def _locked(key: 'str', label: 'str', what: 'str') -> 'dict[str, Any]':
    return {'key': key, 'label': label, 'kind': 'agenda', 'state': 'locked', 'value': '', 'unit': '', 'items': [], 'hint': f'{what} görmek için dokun — macOS bir kez izin isteyecek.'}

def calendar() -> 'dict[str, Any]':
    if paths.IS_WIN:
        today = dt.datetime.combine(dt.date.today(), dt.time())
        parsed, detail, events = True, '', win_agenda.events_between(today, today + dt.timedelta(days=1))
    else:
        if not settings.get('calendar_panel'):
            return _locked('calendar', 'TAKVİM', 'Bugünkü etkinliklerini')
        from .actions import calendar as cal
        window = cal._normalize_query('today')
        ok, raw = cal._run_helper(window['helper_mode'], payload=window.get('payload'), timeout=20)
        parsed, detail, events = cal._parse_payload(raw) if ok else (False, raw, [])
    if not parsed:
        if 'permission' in str(detail).lower() or '4099' in str(detail):
            return {'key': 'calendar', 'label': 'TAKVİM', 'kind': 'agenda', 'state': 'error', 'items': [], 'hint': 'İzin gerekiyor: Sistem Ayarları › Gizlilik › Takvimler'}
        return {'key': None, 'label': None, 'kind': None, 'state': None, 'items': None, 'hint': str(detail)[:80]}
    now = dt.datetime.now().timestamp()
    items = []
    for e in events[:5]:
        start = dt.datetime.fromtimestamp(e['start_ts'])
        items.append({'a': 'TÜM GÜN' if e['all_day'] else f'{start:%H:%M}', 'b': e['title'], 'past': e['end_ts'] < now})
    upcoming = [e for e in events if e['end_ts'] >= now]
    if upcoming:
        return {'key': 'calendar', 'label': 'TAKVİM', 'kind': 'agenda', 'state': 'ok', 'value': str(len(events)), 'unit': 'BUGÜN', 'items': items, 'hint': '' if events else 'Bugün takviminde etkinlik yok.', 'next': upcoming[0]['title']}
    return {'key': None, 'label': None, 'kind': None, 'state': None, 'value': None, 'unit': None, 'items': None, 'hint': None, 'next': ''}

def reminders() -> 'dict[str, Any]':
    if paths.IS_WIN:
        parsed, detail, rows = True, '', win_agenda.reminder_rows('all', 20)
    else:
        if not settings.get('reminders_panel'):
            return _locked('reminders', 'ANIMSATICILAR', 'Anımsatıcılarını')
        from .actions import reminders as rem
        from .actions.calendar import _run_helper
        ok, raw = _run_helper('reminders_list', payload={'query': 'all', 'limit': 20, 'list_name': ''}, timeout=20)
        parsed, detail, rows = rem._parse_payload(raw) if ok else (False, raw, [])
    if not parsed:
        if 'permission' in str(detail).lower() or '4099' in str(detail):
            return {'key': 'reminders', 'label': 'ANIMSATICILAR', 'kind': 'agenda', 'state': 'error', 'items': [], 'hint': 'İzin gerekiyor: Sistem Ayarları › Gizlilik › Anımsatıcılar'}
        return {'key': None, 'label': None, 'kind': None, 'state': None, 'items': None, 'hint': str(detail)[:80]}
    today = dt.date.today()
    now = time.time()
    dated = [r for r in rows if r['due_ts'] if r['due_ts'] <= now + 604800]
    undated = [r for r in rows if not r['due_ts']]
    items = []
    for r in (dated + undated)[:5]:
        when = ''
        if r['due_ts']:
            due = dt.datetime.fromtimestamp(r['due_ts'])
            if r.get('all_day'):
                when = 'BUGÜN' if due.date() == today else f'{due:%d.%m}'
            else:
                when = f'{due:%H:%M}' if due.date() == today else f'{due:%d.%m}'
        late = bool(r['due_ts']) and r['due_ts'] + (86400 if r.get('all_day') else 0) < now
        items.append({'a': when or '—', 'b': r['title'], 'past': False, 'late': late, 'id': r.get('id', '')})
    if rows:
        return {'key': 'reminders', 'label': 'ANIMSATICILAR', 'kind': 'agenda', 'state': 'ok', 'value': str(len(dated) if dated else len(rows)), 'unit': 'BEKLİYOR' if dated else 'AÇIK', 'items': items, 'hint': ''}
    return {'key': None, 'label': None, 'kind': None, 'state': None, 'value': None, 'unit': None, 'items': None, 'hint': 'Bekleyen anımsatıcı yok.'}

def map_panel() -> 'dict[str, Any]':
    wx = weather()
    if wx.get('lat') is None:
        return {'key': 'map', 'label': 'HARİTA', 'kind': 'agenda', 'state': 'error', 'items': [], 'hint': 'Konum belirlenemedi — internet bağlantısını kontrol et.'}
    return {'key': 'map', 'label': 'HARİTA', 'kind': 'map', 'lat': wx['lat'], 'lon': wx['lon'], 'place': wx.get('place', ''), 'country': wx.get('country', ''), 'zoom': wx.get('zoom') or 11}

def timer_panel() -> 'dict[str, Any]':
    from .timers import TIMERS
    return TIMERS.panel()

def notes_panel() -> 'dict[str, Any]':
    from . import notes
    return notes.panel()

BUILDERS = {'system': system, 'timer': timer_panel, 'notes': notes_panel, 'weather': weather, 'calendar': calendar, 'reminders': reminders, 'map': map_panel}
TOGGLEABLE = ('time', 'system', 'timer', 'notes', 'weather', 'calendar', 'reminders', 'map')
UNAVAILABLE: 'frozenset[str]' = frozenset()

def hidden() -> 'set[str]':
    return {str(k) for k in settings.get('panels_off') or []} | UNAVAILABLE

def one(key: 'str') -> 'dict[str, Any] | None':
    build = BUILDERS.get(key)
    if build is None or key in hidden():
        return
    try:
        return build()
    except Exception as exc:
        return {'key': key, 'label': key.upper(), 'kind': 'agenda', 'state': 'error', 'items': [], 'hint': f'{type(exc).__name__}: {exc}'[:90]}

def everything() -> 'list[dict[str, Any]]':
    out = [] if 'time' in hidden() else [{'key': 'time', 'label': 'ZAMAN', 'kind': 'clock'}]
    for key in BUILDERS:
        panel = one(key)
        if panel:
            out.append(panel)
    return out

# WARNING: Decompyle incomplete

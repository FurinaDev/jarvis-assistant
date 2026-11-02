'''Panellerin büyük görünümleri için ayrıntılı veri (panele dokununca açılan pencere).

Paneller özet gösterir; buradakiler aynı konunun genişidir:
- takvim: bugünden başlayarak 14 gün, günlere ayrılmış
- anımsatıcılar: gecikenler, bugün, bu hafta, daha sonra, tarihsiz
- sistem: işlemci (çekirdek çekirdek), bellek, disk, pil, ağ hızı, açık kalma
  süresi, en çok işlemci ve bellek kullanan uygulamalar (büyük pencere açıkken
  birkaç saniyede bir yenilenir)
Saat, kamera ve zamanlayıcının büyük görünümü ekranın kendi verisiyle çizilir.
'''

from __future__ import annotations
import datetime as dt
import os
import platform
import socket
import subprocess
import threading
import time
from typing import Any
import psutil
from . import paths, settings
TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
CALENDAR_DAYS = 14

def _day_label(day: 'dt.date', today: 'dt.date') -> 'str':
    base = f'{day.day} {TR_MONTHS[day.month]} {TR_DAYS[day.weekday()]}'
    if day == today:
        return 'BUGÜN · ' + base
    if day == today + dt.timedelta(days=1):
        return 'YARIN · ' + base
    return base

def _denied(what: 'str', detail: 'str') -> 'dict[str, Any]':
    denied = 'permission' in detail.lower() or '4099' in detail
    if denied:
        return {'state': 'denied' if denied else 'error', 'hint': f"{what} okunamıyor: izin verilmemiş. Sistem Ayarları › Gizlilik › {what}'de JARVIS Calendar Helper'ı aç."}
    return {'state': None, 'hint': detail[:120]}

def calendar() -> 'dict[str, Any]':
    today = dt.date.today()
    start = dt.datetime.combine(today, dt.time())
    if paths.IS_WIN:
        from . import win_agenda
        parsed, detail = True, ''
        events = win_agenda.events_between(start, start + dt.timedelta(days=CALENDAR_DAYS))
    else:
        if not settings.get('calendar_panel'):
            return {'state': 'locked', 'hint': 'Takvimi görmek için izin ver.'}
        from .actions import calendar as cal
        ok, raw = cal._run_helper('range', payload=cal._range_payload(start, start + dt.timedelta(days=CALENDAR_DAYS)), timeout=20)
        parsed, detail, events = cal._parse_payload(raw) if ok else (False, raw, [])
    if not parsed:
        return _denied('Takvimler', str(detail))
    now = time.time()
    days = {}
    for e in events:
        begin, end = dt.datetime.fromtimestamp(e['start_ts']), dt.datetime.fromtimestamp(e['end_ts'])
        days.setdefault(begin.date(), []).append({'time': 'TÜM GÜN' if e['all_day'] else f'{begin:%H:%M}–{end:%H:%M}', 'title': e['title'], 'where': e.get('location', ''), 'calendar': e.get('calendar', ''), 'past': e['end_ts'] < now, 'now': e['start_ts'] <= now <= e['end_ts'] and not e['all_day']})
    return {'state': 'ok', 'count': len(events), 'span': CALENDAR_DAYS, 'days': [{'label': _day_label(d, today), 'today': d == today, 'items': days[d]} for d in sorted(days)]}

def reminders() -> 'dict[str, Any]':
    if paths.IS_WIN:
        from . import win_agenda
        parsed, detail, rows = True, '', win_agenda.reminder_rows('all', 20)
    else:
        if not settings.get('reminders_panel'):
            return {'state': 'locked', 'hint': 'Anımsatıcıları görmek için izin ver.'}
        from .actions import reminders as rem
        from .actions.calendar import _run_helper
        ok, raw = _run_helper('reminders_list', payload={'query': 'all', 'limit': 20, 'list_name': ''}, timeout=20)
        parsed, detail, rows = rem._parse_payload(raw) if ok else (False, raw, [])
    if not parsed:
        return _denied('Anımsatıcılar', str(detail))
    now = dt.datetime.now()
    today, week_end = now.date(), now.date() + dt.timedelta(days=7)
    groups = {'GECİKMİŞ': [], 'BUGÜN': [], 'BU HAFTA': [], 'DAHA SONRA': [], 'TARİHSİZ': []}
    for r in rows:
        item = {'id': r.get('id', ''), 'title': r['title'], 'list': r.get('list_name', ''), 'notes': r.get('notes', '')[:140], 'high': r.get('priority', 0) in (1, 2, 3, 4), 'when': ''}
        if r['due_ts']:
            due = dt.datetime.fromtimestamp(r['due_ts'])
            clock = '' if r.get('all_day') else f' {due:%H:%M}'
            item['when'] = f'{due.day} {TR_MONTHS[due.month]}{clock}' if due.date() != today else clock.strip() or 'bugün'
            late = due.date() < today if r.get('all_day') else due < now
            group = 'GECİKMİŞ' if late else 'BUGÜN' if due.date() == today else 'BU HAFTA' if due.date() <= week_end else 'DAHA SONRA'
        else:
            group = 'TARİHSİZ'
        groups[group].append(item)
        continue
    return {'state': 'ok', 'count': len(rows), 'capped': len(rows) >= 20, 'groups': [{'label': k, 'items': v} for k, v in groups.items() if v]}

_procs: 'dict[int, psutil.Process]' = {}
_net_last: 'tuple[float, int, int] | None' = None
_host: 'dict[str, str] | None' = None

def _sysctl(name: 'str') -> 'str':
    try:
        return subprocess.run(['sysctl', '-n', name], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''

def _host_info() -> 'dict[str, str]':
    global _host
    if _host is None and paths.IS_WIN:
        from .actions.win_sys_info import host_info
        _host = host_info()
    if _host is None:
        mac = platform.mac_ver()[0] if paths.IS_MAC else ''
        _host = {'os': f'macOS {mac}' if mac else platform.platform(terse=True), 'cpu': _sysctl('machdep.cpu.brand_string') if paths.IS_MAC else platform.processor(), 'model': _sysctl('hw.model') if paths.IS_MAC else '', 'name': socket.gethostname().removesuffix('.local')}
    return _host

def _root() -> 'str':
    '''Diskin bakılacağı yer: macOS'ta "/", Windows'ta sistemin kurulu olduğu sürücü (genelde C:\\).'''

    if paths.IS_WIN:
        return os.environ.get('SystemDrive', 'C:') + '\\'
    return '/'

def _gb(n: 'float') -> 'float':
    return round(n / 1073741824, 1)

def _span(seconds: 'float') -> 'str':
    seconds = int(seconds)
    d, rest = divmod(seconds, 86400)
    h, m = divmod(rest // 60, 60)
    return (f'{d} gün ' if d else '') + f'{h} sa {m} dk'

def _top_processes() -> 'tuple[list[dict[str, Any]], list[dict[str, Any]]]':
    """İşlemci yüzdesi iki ölçüm arasındaki farktır; süreçler saklanır, ilk açılışta 0 görünür.
    Windows'ta liste 1-4 sn sürüyor (korumalı süreçlerde psutil'in yavaş yolu), ekran ise 2 sn'de bir istiyor: sonuç
    birkaç saniye saklanır, aynı anda yalnızca bir ölçüm yapılır (yoksa bir çekirdeğin çoğu gidiyordu)."""

    global _top_last
    if not paths.IS_WIN:
        return _measure_top()
    if not time.monotonic() - _top_last[0] < TOP_EVERY_WIN:
        if not _top_lock.acquire(blocking=False):
            return _top_last[1]
    try:
        _top_last = time.monotonic(), _measure_top()
    finally:
        _top_lock.release()
    return _top_last[1]

TOP_EVERY_WIN = 5.0
_top_lock = threading.Lock()
_top_last: 'tuple[float, tuple[list, list]]' = -1000000000.0, ([], [])

def _measure_top() -> 'tuple[list[dict[str, Any]], list[dict[str, Any]]]':
    seen = set()
    rows = []
    if paths.IS_WIN:
        pass
    share = psutil.cpu_count() or 1
    for p in psutil.process_iter(['pid', 'name', 'memory_info']):
        pid = p.info['pid']
        if paths.IS_WIN and pid == 0:
            continue
        seen.add(pid)
        proc = _procs.setdefault(pid, p)
        try:
            cpu = proc.cpu_percent(None) / share
            mem = p.info['memory_info'].rss if p.info['memory_info'] else 0
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        name = p.info['name'] or '?'
        if paths.IS_WIN and name.lower().endswith('.exe'):
            name = name[:-4]
        rows.append({'name': name[:28], 'cpu': round(cpu, 1), 'mem': round(mem / 1048576)})
        continue
    for pid in list(_procs):
        if pid not in seen:
            _procs.pop(pid, None)
    by_cpu = sorted(rows, key=(lambda r: r['cpu']), reverse=True)[:6]
    by_mem = sorted(rows, key=(lambda r: r['mem']), reverse=True)[:6]
    return by_cpu, by_mem

def system() -> 'dict[str, Any]':
    global _net_last
    cores = psutil.cpu_percent(interval=None, percpu=True)
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    disk = psutil.disk_usage(_root())
    net = psutil.net_io_counters()
    now = time.monotonic()
    up = down = 0.0
    if _net_last:
        span = max(0.5, now - _net_last[0])
        up, down = (net.bytes_sent - _net_last[1]) / span, (net.bytes_recv - _net_last[2]) / span
    _net_last = now, net.bytes_sent, net.bytes_recv
    battery = psutil.sensors_battery()
    bat = None
    if battery is not None:
        left = battery.secsleft
        bat = {'percent': round(battery.percent), 'plugged': bool(battery.power_plugged), 'left': left if isinstance(left, (int, float)) else _span(left) if 0 < left < 1000000 else ''}
    by_cpu, by_mem = _top_processes()
    load = () if paths.IS_WIN else psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
    return {'state': 'ok', 'host': _host_info(), 'cpu': {'total': round(sum(cores) / max(1, len(cores))), 'cores': [round(c) for c in cores], 'load': [round(x, 2) for x in load]}, 'ram': {'percent': round(vm.percent), 'used': _gb(vm.total - vm.available), 'total': _gb(vm.total), 'swap': _gb(sw.used)}, 'disk': {'percent': round((disk.total - disk.free) / disk.total * 100) if disk.total else 0, 'used': _gb(disk.total - disk.free), 'total': _gb(disk.total), 'free': _gb(disk.free)}, 'battery': bat, 'net': {'up': round(up / 1024), 'down': round(down / 1024), 'sent': _gb(net.bytes_sent), 'recv': _gb(net.bytes_recv)}, 'uptime': _span(time.time() - psutil.boot_time()), 'top_cpu': by_cpu, 'top_mem': by_mem}

BUILDERS = {'calendar': calendar, 'reminders': reminders, 'system': system}

def one(key: 'str') -> 'dict[str, Any]':
    build = BUILDERS.get(key)
    if build is None:
        return {'state': 'error', 'hint': 'Bu panelin büyük görünümü yok.'}
    try:
        return build()
    except Exception as exc:
        return {'state': 'error', 'hint': f'{type(exc).__name__}: {exc}'[:120]}

# WARNING: Decompyle incomplete

"""
Apple Calendar okuma araci.

Takvim verisini macOS EventKit uzerinden Swift yardimiyla okur.
Bu yol AppleScript'e gore daha stabil ve tarih filtrelemesi daha sagliklidir.
"""

from __future__ import annotations
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from .. import paths
SWIFT_CACHE_DIR = paths.DATA_DIR / '.swift-cache'
HELPERS_DIR = paths.HELPERS_SRC
HELPER_SOURCE = HELPERS_DIR / 'jarvis_calendar_helper.swift'
HELPER_PLIST = HELPERS_DIR / 'jarvis_calendar_helper.plist'
HELPER_APP = (paths.BUNDLED_HELPERS if paths.FROZEN else paths.HELPERS_BUILD) / f'{paths.CALENDAR_HELPER}.app'
HELPER_CONTENTS_DIR = HELPER_APP / 'Contents'
HELPER_MACOS_DIR = HELPER_CONTENTS_DIR / 'MacOS'
HELPER_RESOURCES_DIR = HELPER_CONTENTS_DIR / 'Resources'
HELPER_INFO_PLIST = HELPER_CONTENTS_DIR / 'Info.plist'
HELPER_BIN = HELPER_MACOS_DIR / 'jarvis-calendar-helper'
TR_WEEKDAYS = ['Pazartesi', 'Sali', 'Carsamba', 'Persembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Subat', 'Mart', 'Nisan', 'Mayis', 'Haziran', 'Temmuz', 'Agustos', 'Eylul', 'Ekim', 'Kasim', 'Aralik']

def _month_start(value: 'dt.datetime') -> 'dt.datetime':
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def _add_months(value: 'dt.datetime', months: 'int') -> 'dt.datetime':
    total = value.year * 12 + (value.month - 1) + months
    year = total // 12
    month = total % 12 + 1
    return value.replace(year=year, month=month, day=1)

def _range_payload(start: 'dt.datetime', end: 'dt.datetime') -> 'dict':
    return {'start_iso': start.isoformat(), 'end_iso': end.isoformat()}

_TR_ASCII = str.maketrans('ıİğĞüÜşŞöÖçÇ', 'iIgGuUsSoOcC')

def _normalize_query(query: 'str') -> 'dict':
    q = (query or 'today').strip().translate(_TR_ASCII).lower()
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_match = re.search('(\\d+)\\s*(ay|month|months)', q)
    if 'gelecek ay' in q or 'önümüzdeki ay' in q or 'onumuzdeki ay' in q or 'next month' in q:
        start = _add_months(_month_start(now), 1)
        end = _add_months(start, 1)
        return {'helper_mode': 'range', 'payload': _range_payload(start, end), 'default_limit': 24, 'kind': 'next_month', 'header': 'Gelecek ay icin {count} etkinlik buldum:', 'empty': 'Gelecek ay takviminde etkinlik gorunmuyor.'}
    if 'bu ay' in q or 'this month' in q:
        start = _month_start(now)
        end = _add_months(start, 1)
        return {'helper_mode': 'range', 'payload': _range_payload(start, end), 'default_limit': 24, 'kind': 'this_month', 'header': 'Bu ay icin {count} etkinlik buldum:', 'empty': 'Bu ay takviminde etkinlik gorunmuyor.'}
    if month_match:
        months = max(1, min(12, int(month_match.group(1))))
        start = today_start
        end = _add_months(_month_start(now), months)
        return {'helper_mode': 'range', 'payload': _range_payload(start, end), 'default_limit': min(60, max(12, months * 12)), 'kind': 'months', 'header': f'Onumuzdeki {months} ay icin {{count}} etkinlik buldum:', 'empty': f'Onumuzdeki {months} ayda takviminde etkinlik gorunmuyor.'}
    week_match = re.search('(\\d+)\\s*(hafta|week|weeks)', q)
    if week_match:
        weeks = max(1, min(12, int(week_match.group(1))))
        start = today_start
        end = today_start + dt.timedelta(days=weeks * 7)
        return {'helper_mode': 'range', 'payload': _range_payload(start, end), 'default_limit': min(60, max(8, weeks * 8)), 'kind': 'weeks', 'header': f'Onumuzdeki {weeks} hafta icin {{count}} etkinlik buldum:', 'empty': f'Onumuzdeki {weeks} haftada takviminde etkinlik gorunmuyor.'}
    day_match = re.search('(\\d+)\\s*(g[uü]n|gun|day|days)', q)
    if day_match:
        days = max(1, min(365, int(day_match.group(1))))
        start = today_start
        end = today_start + dt.timedelta(days=days)
        return {'helper_mode': 'range', 'payload': _range_payload(start, end), 'default_limit': min(60, max(8, days * 2)), 'kind': 'days', 'header': f'Onumuzdeki {days} gun icin {{count}} etkinlik buldum:', 'empty': f'Onumuzdeki {days} gunde takviminde etkinlik gorunmuyor.'}
    if any((token in q for token in ('yarin', 'tomorrow'))):
        return {'helper_mode': 'tomorrow', 'payload': None, 'default_limit': 6, 'kind': 'tomorrow', 'header': 'Yarin icin {count} etkinlik buldum:', 'empty': 'Yarin takviminde etkinlik gorunmuyor.'}
    if any((token in q for token in ('hafta', 'week', '7 gun'))):
        return {'helper_mode': 'week', 'payload': None, 'default_limit': 10, 'kind': 'week', 'header': 'Onumuzdeki 7 gun icin {count} etkinlik buldum:', 'empty': 'Onumuzdeki 7 gunde takviminde etkinlik gorunmuyor.'}
    if any((token in q for token in ('siradaki', 'sıradaki', 'sonraki', 'next'))):
        return {'helper_mode': 'next', 'payload': None, 'default_limit': 1, 'kind': 'next', 'header': '', 'empty': 'Siradaki takvim etkinligini bulamadim.'}
    if any((token in q for token in ('ajanda', 'agenda', 'yaklasan', 'yaklaşan', 'upcoming'))):
        return {'helper_mode': 'agenda', 'payload': None, 'default_limit': 8, 'kind': 'agenda', 'header': 'Yaklasan ajandanda {count} etkinlik var:', 'empty': 'Yaklasan takvim etkinligi gorunmuyor.'}
    return {'helper_mode': 'today', 'payload': None, 'default_limit': 6, 'kind': 'today', 'header': 'Bugun icin {count} etkinlik buldum:', 'empty': 'Bugun takviminde etkinlik gorunmuyor.'}

def _ensure_helper_binary() -> 'tuple[bool, str]':
    if paths.FROZEN:
        return (True, '') if HELPER_BIN.exists() else (False, 'Takvim yardimcisi uygulama paketinde bulunamadi.')
    SWIFT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HELPER_MACOS_DIR.mkdir(parents=True, exist_ok=True)
    HELPER_RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    if not HELPER_SOURCE.exists():
        return (False, 'Takvim helper kaynak dosyasi bulunamadi.')
    if not HELPER_PLIST.exists():
        return (False, 'Takvim helper plist dosyasi bulunamadi.')
    source_mtime = max(HELPER_SOURCE.stat().st_mtime, HELPER_PLIST.stat().st_mtime)
    if HELPER_BIN.exists() and HELPER_INFO_PLIST.exists() and HELPER_BIN.stat().st_mtime >= source_mtime and HELPER_INFO_PLIST.stat().st_mtime >= source_mtime:
        return (True, '')
    try:
        HELPER_INFO_PLIST.write_text(HELPER_PLIST.read_text(encoding='utf-8'), encoding='utf-8')
        env = os.environ.copy()
        env['CLANG_MODULE_CACHE_PATH'] = str(SWIFT_CACHE_DIR)
        env['SWIFT_MODULE_CACHE_PATH'] = str(SWIFT_CACHE_DIR)
        result = subprocess.run(['swiftc', str(HELPER_SOURCE), '-o', str(HELPER_BIN)], capture_output=True, text=True, timeout=30, env=env)
    except FileNotFoundError:
        return (False, 'swiftc bulunamadi.')
    except subprocess.TimeoutExpired:
        return (False, 'Takvim helper binary derlenirken zaman asimina ugradi.')
    except Exception as exc:
        return False, f'Takvim helper binary derlenemedi: {exc}'
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        return False, detail or 'Swift helper binary derlenemedi.'
    try:
        HELPER_BIN.chmod(493)
    except Exception:
        pass
    return (True, '')

def _run_helper(mode: 'str', payload: 'dict | None'=None, timeout: 'int'=20) -> 'tuple[bool, str]':
    ok, detail = _ensure_helper_binary()
    if not ok:
        return False, detail
    output_path = None
    payload_path = None
    raw = ''
    try:
        handle = tempfile.NamedTemporaryFile(prefix='jarvis-calendar-', suffix='.json', delete=False)
        output_path = Path(handle.name)
        handle.close()
        helper_args = [mode]
        if payload is not None:
            payload_handle = tempfile.NamedTemporaryFile(prefix='jarvis-helper-payload-', suffix='.json', delete=False)
            payload_path = Path(payload_handle.name)
            payload_handle.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            payload_handle.close()
            helper_args.append(str(payload_path))
        helper_args.append(str(output_path))
        result = subprocess.run(['open', '-W', '-n', str(HELPER_APP), '--args', *helper_args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return (False, 'Organizer helper istegi zaman asimina ugradi.')
    except Exception as exc:
        return False, f'Organizer helper calistirilamadi: {exc}'
    if output_path and output_path.exists():
        try:
            raw = output_path.read_text(encoding='utf-8').strip()
        except Exception:
            raw = ''
    final_raw = raw or (result.stdout or '').strip()
    if result.returncode != 0:
        final_raw = raw
    if not final_raw:
        try:
            helper_args = [mode]
            if payload is not None and payload_path:
                helper_args.append(str(payload_path))
            if output_path:
                helper_args.append(str(output_path))
            result = subprocess.run([str(HELPER_BIN), *helper_args], capture_output=True, text=True, timeout=timeout)
            if output_path and output_path.exists():
                pass
            try:
                final_raw = output_path.read_text(encoding='utf-8').strip()
            except Exception:
                final_raw = ''
            else:
                if not final_raw:
                    if result.returncode == 0:
                        final_raw = (result.stdout or '').strip()
                if result.returncode != 0 and not final_raw:
                    detail = (result.stderr or result.stdout or '').strip()
        except subprocess.TimeoutExpired:
            return (False, 'Organizer helper istegi zaman asimina ugradi.')
        except Exception as exc:
            return False, f'Organizer helper calistirilamadi: {exc}'
    try:
        if output_path and output_path.exists():
            output_path.unlink()
    except Exception:
        pass
    try:
        if payload_path and payload_path.exists():
            payload_path.unlink()
    except Exception:
        pass
    return True, final_raw

def _parse_payload(raw: 'str') -> 'tuple[bool, str, list[dict]]':
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, 'Gecersiz takvim yaniti alindi.', []
    if not isinstance(payload, dict):
        return False, 'Takvim verisi beklenen formatta degil.', []
    if not payload.get('ok', False):
        return False, str(payload.get('detail') or payload.get('error') or 'Takvim erisimi basarisiz.'), []
    events = payload.get('events', [])
    if not isinstance(events, list):
        return False, 'Takvim olaylari okunamadi.', []
    normalized = []
    for item in events:
        if not isinstance(item, dict):
            continue
        try:
            start_ts = int(item.get('start_ts', 0))
            end_ts = int(item.get('end_ts', 0))
        except (TypeError, ValueError):
            continue
        if start_ts <= 0 or end_ts <= 0:
            continue
        normalized.append({'start_ts': start_ts, 'end_ts': end_ts, 'calendar': str(item.get('calendar', '')).strip(), 'title': str(item.get('title', '')).strip() or 'Adsiz etkinlik', 'location': str(item.get('location', '')).strip(), 'all_day': bool(item.get('all_day', False))})
        continue
    normalized.sort(key=(lambda event: (event['start_ts'], event['title'].lower())))
    return True, '', normalized

def _parse_single_event_payload(raw: 'str') -> 'tuple[bool, str, dict | None]':
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return (False, 'Gecersiz takvim yaniti alindi.', None)
    if not isinstance(payload, dict):
        return (False, 'Takvim verisi beklenen formatta degil.', None)
    if not payload.get('ok', False):
        return False, str(payload.get('detail') or payload.get('error') or 'Takvim islemi basarisiz.'), None
    item = payload.get('created')
    if not isinstance(item, dict):
        return (False, 'Olusturulan etkinlik bilgisi alinamadi.', None)
    try:
        start_ts = int(item.get('start_ts', 0))
        end_ts = int(item.get('end_ts', 0))
    except (TypeError, ValueError):
        return (False, 'Olusturulan etkinlik zamani okunamadi.', None)
    if start_ts <= 0 or end_ts <= 0:
        return (False, 'Olusturulan etkinlik zamani gecersiz.', None)
    return True, '', {'start_ts': start_ts, 'end_ts': end_ts, 'calendar': str(item.get('calendar', '')).strip(), 'title': str(item.get('title', '')).strip() or 'Adsiz etkinlik', 'location': str(item.get('location', '')).strip(), 'all_day': bool(item.get('all_day', False))}

def request_access() -> 'None':
    '''İlk açılış: yardımcı takvime bir kez bakar; izin sorulmadıysa macOS sorar (cevap beklenir).'''

    _run_helper('today', timeout=180)

def _calendar_permission_message() -> 'str':
    return "Takvim erisim izni gerekiyor. Ilk denemede macOS izin penceresi gelirse onayla; gelmediyse Sistem Ayarlari > Gizlilik ve Guvenlik > Takvim bolumunde 'JARVIS Calendar Helper' uygulamasini ara ve izin ver."

def _day_label(when: 'dt.datetime', now: 'dt.datetime') -> 'str':
    today = now.date()
    target = when.date()
    if target == today:
        return 'bugun'
    if target == today + dt.timedelta(days=1):
        return 'yarin'
    return f'{when.day} {TR_MONTHS[when.month]} {TR_WEEKDAYS[when.weekday()]}'

def _format_time_range(event: 'dict', now: 'dt.datetime') -> 'str':
    start = dt.datetime.fromtimestamp(event['start_ts'])
    end = dt.datetime.fromtimestamp(event['end_ts'])
    prefix = _day_label(start, now)
    if event['all_day']:
        return f'{prefix} tum gun'
    return f'{prefix} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}'

def _format_event_line(event: 'dict', now: 'dt.datetime') -> 'str':
    pieces = [f'{_format_time_range(event, now)} - {event['title']}']
    if event['calendar']:
        pieces.append(f'[{event['calendar']}]')
    if event['location']:
        pieces.append(f'@ {event['location']}')
    return ' '.join(pieces)

def get_calendar_events(query: 'str'='today', limit: 'int'=6) -> 'str':
    window = _normalize_query(query)
    limit = max(1, min(60, int(limit or window['default_limit'])))
    ok, raw = _run_helper(window['helper_mode'], payload=window.get('payload'), timeout=20)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _calendar_permission_message()
        return f'Takvim okunamadi: {raw}'
    parsed_ok, detail, events = _parse_payload(raw)
    if not parsed_ok:
        low = detail.lower()
        if 'permission' in low or 'mach error 4099' in low:
            return _calendar_permission_message()
        return f'Takvim okunamadi: {detail}'
    now = dt.datetime.now()
    if window['kind'] in {'next', 'agenda'}:
        events = [event for event in events if event['end_ts'] >= int(now.timestamp())]
    if not events:
        return window['empty']
    if window['kind'] == 'next':
        return f'Siradaki etkinlik: {_format_event_line(events[0], now)}.'
    selected = events[:limit]
    header = str(window['header']).format(count=len(selected))
    lines = [header]
    for event in selected:
        lines.append(f'- {_format_event_line(event, now)}')
    return '\n'.join(lines)

def add_calendar_event(title: 'str', start_iso: 'str', end_iso: 'str'='', notes: 'str'='', location: 'str'='', calendar_name: 'str'='', all_day: 'bool'=False) -> 'str':
    title = (title or '').strip()
    start_iso = (start_iso or '').strip()
    if not title:
        return 'Takvime eklemek icin etkinlik basligi gerekli.'
    if not start_iso:
        return 'Takvime eklemek icin baslangic tarihi gerekli.'
    payload = {'title': title, 'start_iso': start_iso, 'end_iso': (end_iso or '').strip(), 'notes': (notes or '').strip(), 'location': (location or '').strip(), 'calendar_name': (calendar_name or '').strip(), 'all_day': bool(all_day)}
    ok, raw = _run_helper('create_event', payload=payload, timeout=25)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _calendar_permission_message()
        return f'Takvim etkinligi eklenemedi: {raw}'
    parsed_ok, detail, event = _parse_single_event_payload(raw)
    if not parsed_ok:
        low = detail.lower()
        if 'permission' in low or 'mach error 4099' in low:
            return _calendar_permission_message()
        return f'Takvim etkinligi eklenemedi: {detail}'
    assert event is not None
    now = dt.datetime.now()
    line = _format_event_line(event, now)
    return f'Takvime eklendi: {line}.'

_DEL_FAILED = 'Etkinlik silinemedi'

def _event_row(item: 'object') -> 'dict | None':
    '''Yardımcının verdiği etkinlik kaydı → düzgün sözlük (bozuksa None).'''

    if not isinstance(item, dict):
        return
    try:
        row = {'start_ts': int(item.get('start_ts', 0)), 'end_ts': int(item.get('end_ts', 0)), 'calendar': str(item.get('calendar', '')).strip(), 'title': str(item.get('title', '')).strip() or 'Adsiz etkinlik', 'location': str(item.get('location', '')).strip(), 'all_day': bool(item.get('all_day', False)), 'recurring': bool(item.get('recurring', False))}
    except (TypeError, ValueError):
        pass
    else:
        if row['start_ts'] > 0 and row['end_ts'] > 0:
            return row

def _event_lines(events: 'list[dict]', mark_recurring: 'bool'=False) -> 'str':
    now = dt.datetime.now()
    return ' | '.join((_format_event_line(e, now) + (' (tekrarlayan)' if mark_recurring and e.get('recurring') else '') for e in events[:5]))

def event_not_found_text(dated: 'bool') -> 'str':
    if dated:
        return f'{_DEL_FAILED}: {'o gün'} takvimde bu ada uyan etkinlik bulamadım.'
    return f'{None}{None}{'önümüzdeki bir yılda'} takvimde bu ada uyan etkinlik bulamadım.'

def event_multiple_text(events: 'list[dict]', count: 'int') -> 'str':
    return f'Bu ada uyan {count} etkinlik var, hiçbirine dokunmadım; hangisi olduğunu söylersen silerim. Eşleşenler: {_event_lines(events, True)}'

def event_series_text(title: 'str', events: 'list[dict]') -> 'str':
    '''Eşleşenlerin hepsi tek bir tekrarlayan dizinin günleri ("haftalık toplantı"): hangi günkü, yoksa hepsi mi?'''

    return f'"{title}" tekrarlayan bir etkinlik, hiçbirine dokunmadım; hangi günkünü sileyim, yoksa hepsini mi? Sıradakiler: {_event_lines(events)}'

def event_deleted_text(events: 'list[dict]', series: 'int'=0, recurring: 'bool'=False) -> 'str':
    '''series: o günden itibaren bütün tekrarlarıyla silinen dizi sayısı; recurring: tek silinen, bir dizinin o günkü.'''

    lines = _event_lines(events)
    if len(events) == 1 and series:
        return f'Tekrarlayan etkinlik o günden itibaren bütün tekrarlarıyla takvimden silindi: {lines}.'
    if len(events) > 1:
        rest = ' Tekrarlayanlar o günden itibaren bütün tekrarlarıyla silindi.' if series else ''
        return f'{len(events)} etkinlik takvimden silindi: {lines}.{rest}'
    rest = ' Tekrarlayan bir etkinlik: yalnızca o günkü silindi, diğer günleri takvimde duruyor.' if recurring else ''
    return f'Takvimden silindi: {lines}.{rest}'

def event_targets(rows: 'list[dict]', title: 'str', day: 'dt.datetime | None'=None, has_time: 'bool'=False, every: 'bool'=False) -> 'tuple[list[dict], str]':
    """Silinecek etkinlikler → (hedefler, cevap); cevap doluysa hiçbirine dokunulmaz (Windows'un yerel ajandası için;
    orada tekrarlayan etkinlik ve salt okunur takvim yok). rows: arama aralığındaki etkinlikler (bugünden bir yıl,
    tarih verildiyse o gün). Eşleşenlerin hepsi aynı ad ve saatteyse (iki kez eklenmiş) hepsi gider."""

    from .reminders import _fold, match_titles
    picked = match_titles(rows, title, None, False, stamp='start_ts')
    if len(picked) > 1 and has_time:
        if day is not None:
            minute = day.replace(second=0, microsecond=0)
            picked = [e for e in picked
                 if dt.datetime.fromtimestamp(e['start_ts']).replace(second=0, microsecond=0) == minute] or picked
    if not picked:
        return [], event_not_found_text(day is not None)
    same = len({(_fold(e['title']), e['start_ts']) for e in picked}) == 1
    if len(picked) > 1 and not every and not same:
        return [], event_multiple_text(picked, len(picked))
    return picked, ''

def delete_calendar_event(title: 'str', start_iso: 'str'='', calendar_name: 'str'='', delete_all_matches: 'bool'=False) -> 'str':
    '''Takvimden etkinlik siler: bugünden bir yıl ileriye (tarih verilirse o güne) bakar. Birden çok eşleşmede
    hiçbirine dokunmaz, sorar; tekrarlayan etkinlikte yalnızca o günkü silinir, "hepsini sil"de o günden sonrası.'''

    title, start_iso = (title or '').strip(), (start_iso or '').strip()
    if not title:
        return f'{_DEL_FAILED}: etkinliğin adı gerekli.'
    payload = {'title': title, 'start_iso': start_iso, 'calendar_name': (calendar_name or '').strip(), 'delete_all_matches': bool(delete_all_matches)}
    ok, raw = _run_helper('delete_event', payload=payload, timeout=25)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _calendar_permission_message()
        return f'{_DEL_FAILED}: {raw}'
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict):
        return f'{_DEL_FAILED}: yardımcıdan geçersiz yanıt geldi.'
    matches = [row for row in map(_event_row, result.get('matches') or []) if row]
    if not result.get('ok', False):
        error = str(result.get('error') or '')
        detail = str(result.get('detail') or error or 'bilinmeyen sorun')
        if error == 'permission_denied' or 'permission' in detail.lower() or 'mach error 4099' in detail.lower():
            return _calendar_permission_message()
        if error == 'not_found':
            return event_not_found_text(bool(start_iso))
        if error == 'invalid_start_date':
            return f'{_DEL_FAILED}: tarih anlaşılamadı ({start_iso}). yyyy-MM-dd ya da yyyy-MM-dd HH:mm ver.'
        if error == 'read_only' and matches:
            return f'{_DEL_FAILED}: {_event_lines(matches[:1])} salt okunur bir takvimde, değiştirilemez.'
        if error == 'recurring' and matches:
            return event_series_text(str(result.get('title') or matches[0]['title']), matches)
        if error == 'multiple_matches' and matches:
            try:
                count = int(result.get('count') or len(matches))
            except (TypeError, ValueError):
                count = len(matches)
            return event_multiple_text(matches, count)
        return f'{_DEL_FAILED}: {detail}'
    items = [row for row in map(_event_row, result.get('deleted_items') or []) if row]
    if not items:
        return f'{_DEL_FAILED}: yardımcıdan geçersiz yanıt geldi.'
    try:
        series = int(result.get('series') or 0)
    except (TypeError, ValueError):
        series = 0
    return event_deleted_text(items, series, bool(result.get('recurring')))

# WARNING: Decompyle incomplete

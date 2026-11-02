'''
Apple Reminders tools for JARVIS.

Reads reminder lists and creates new reminders through the shared
EventKit helper app used by calendar access.
'''

from __future__ import annotations
import datetime as dt
import json
import re
import unicodedata
from .calendar import _run_helper
TR_WEEKDAYS = ['Pazartesi', 'Sali', 'Carsamba', 'Persembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Subat', 'Mart', 'Nisan', 'Mayis', 'Haziran', 'Temmuz', 'Agustos', 'Eylul', 'Ekim', 'Kasim', 'Aralik']

def _normalize_query(query: 'str') -> 'tuple[str, int]':
    q = (query or '').strip().translate(str.maketrans('ıİğĞüÜşŞöÖçÇ', 'iIgGuUsSoOcC')).lower()
    if any((token in q for token in ('bugun', 'today'))):
        return ('today', 8)
    if any((token in q for token in ('geciken', 'gecmis', 'overdue'))):
        return ('overdue', 8)
    if any((token in q for token in ('siradaki', 'sıradaki', 'next'))):
        return ('next', 1)
    if any((token in q for token in ('hepsi', 'tum', 'tüm', 'all', 'listele'))):
        return ('all', 10)
    return ('upcoming', 8)

def _parse_payload(raw: 'str') -> 'tuple[bool, str, list[dict]]':
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, 'Gecersiz animsatici yaniti alindi.', []
    if not isinstance(payload, dict):
        return False, 'Animsatici verisi beklenen formatta degil.', []
    if not payload.get('ok', False):
        return False, str(payload.get('detail') or payload.get('error') or 'Animsatici erisimi basarisiz.'), []
    reminders = payload.get('reminders', [])
    if not isinstance(reminders, list):
        return False, 'Animsatici listesi okunamadi.', []
    return True, '', _rows(reminders)

def _rows(reminders: 'list') -> 'list[dict]':
    '''Yardımcının verdiği anımsatıcı kayıtları → düzgün sözlükler, tarihe göre sıralı (tarihsizler sonda).'''

    normalized = []
    for item in reminders:
        if not isinstance(item, dict):
            continue
        try:
            due_ts = int(item.get('due_ts', 0) or 0)
            priority = int(item.get('priority', 0) or 0)
        except (TypeError, ValueError):
            continue
        normalized.append({'id': str(item.get('id', '') or '').strip(), 'title': str(item.get('title', '')).strip() or 'Adsiz animsatici', 'list_name': str(item.get('list_name', '')).strip(), 'notes': str(item.get('notes', '')).strip(), 'completed': bool(item.get('completed', False)), 'priority': priority, 'due_ts': due_ts, 'all_day': bool(item.get('all_day', False))})
        continue
    normalized.sort(key=(lambda item: (item['due_ts'] <= 0, item['due_ts'] or 0, item['title'].lower())))
    return normalized

def _parse_created_payload(raw: 'str') -> 'tuple[bool, str, dict]':
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, 'Gecersiz animsatici yaniti alindi.', {}
    if not isinstance(payload, dict):
        return False, 'Animsatici verisi beklenen formatta degil.', {}
    if not payload.get('ok', False):
        return False, str(payload.get('detail') or payload.get('error') or 'Animsatici eklenemedi.'), {}
    created = payload.get('created', {})
    if not isinstance(created, dict):
        return False, 'Animsatici kaydi okunamadi.', {}
    try:
        due_ts = int(created.get('due_ts', 0) or 0)
        priority = int(created.get('priority', 0) or 0)
    except (TypeError, ValueError):
        due_ts = 0
        priority = 0
    return True, '', {'title': str(created.get('title', '')).strip() or 'Adsiz animsatici', 'list_name': str(created.get('list_name', '')).strip(), 'notes': str(created.get('notes', '')).strip(), 'priority': priority, 'due_ts': due_ts, 'all_day': bool(created.get('all_day', False))}

def _day_label(when: 'dt.datetime', now: 'dt.datetime') -> 'str':
    today = now.date()
    target = when.date()
    if target == today:
        return 'bugun'
    if target == today + dt.timedelta(days=1):
        return 'yarin'
    return f'{when.day} {TR_MONTHS[when.month]} {TR_WEEKDAYS[when.weekday()]}'

def _format_due(item: 'dict', now: 'dt.datetime') -> 'str':
    if item['due_ts'] <= 0:
        return 'zaman atanmamis'
    due = dt.datetime.fromtimestamp(item['due_ts'])
    if item['all_day']:
        return f'{_day_label(due, now)} tum gun'
    return f'{_day_label(due, now)} {due.strftime('%H:%M')}'

def _format_reminder_line(item: 'dict', now: 'dt.datetime') -> 'str':
    parts = [f'{_format_due(item, now)} - {item['title']}']
    if item['list_name']:
        parts.append(f'[{item['list_name']}]')
    if item['priority'] == 1:
        parts.append('(yuksek oncelik)')
    return ' '.join(parts)

def _permission_message() -> 'str':
    return "Animsatici erisim izni gerekiyor. Ilk denemede macOS izin penceresi gelirse onayla; gelmediyse Sistem Ayarlari > Gizlilik ve Guvenlik > Animsaticilar bolumunde 'JARVIS Calendar Helper' uygulamasina izin ver."

def request_access() -> 'None':
    '''İlk açılış: yardımcı anımsatıcılara bir kez bakar; izin sorulmadıysa macOS sorar (cevap beklenir).'''

    _run_helper('reminders_list', payload={'query': 'upcoming', 'limit': 1, 'list_name': ''}, timeout=180)

def get_reminders(query: 'str'='upcoming', limit: 'int'=8, list_name: 'str'='') -> 'str':
    mode, default_limit = _normalize_query(query)
    limit = max(1, min(20, int(limit or default_limit)))
    ok, raw = _run_helper('reminders_list', payload={'query': mode, 'limit': limit, 'list_name': (list_name or '').strip()}, timeout=25)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _permission_message()
        return f'Animsaticilar okunamadi: {raw}'
    parsed_ok, detail, reminders = _parse_payload(raw)
    if not parsed_ok:
        low = detail.lower()
        if 'permission' in low or 'mach error 4099' in low:
            return _permission_message()
        return f'Animsaticilar okunamadi: {detail}'
    if not reminders:
        if mode == 'today':
            return 'Bugun icin animsatici gorunmuyor.'
        if mode == 'overdue':
            return 'Geciken animsatici gorunmuyor.'
        if mode == 'next':
            return 'Siradaki animsaticiyi bulamadim.'
        if mode == 'all':
            return 'Kayitli acik animsatici gorunmuyor.'
        return 'Yaklasan animsatici gorunmuyor.'
    now = dt.datetime.now()
    if mode == 'next':
        return f'Siradaki animsatici: {_format_reminder_line(reminders[0], now)}.'
    if mode == 'today':
        header = f'Bugun icin {len(reminders)} animsatici buldum:'
    elif mode == 'overdue':
        header = f'Gecikmis {len(reminders)} animsatici buldum:'
    elif mode == 'all':
        header = f'Acik {len(reminders)} animsatici buldum:'
    else:
        header = f'Yaklasan {len(reminders)} animsatici buldum:'
    lines = [header]
    for item in reminders:
        lines.append(f'- {_format_reminder_line(item, now)}')
    return '\n'.join(lines)

def _normalize_due_iso(due_iso: 'str') -> 'tuple[str, bool]':
    raw = (due_iso or '').strip()
    if not raw:
        return ('', False)
    candidates = (('%Y-%m-%dT%H:%M:%S', False), ('%Y-%m-%dT%H:%M', False), ('%Y-%m-%d %H:%M:%S', False), ('%Y-%m-%d %H:%M', False), ('%d.%m.%Y %H:%M', False), ('%Y-%m-%d', True), ('%d.%m.%Y', True))
    if raw.endswith('Z'):
        try:
            parsed = dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
            return parsed.isoformat(), False
        except ValueError:
            pass
    if re.match('^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}', raw):
        try:
            parsed = dt.datetime.fromisoformat(raw)
            return parsed.isoformat(timespec='minutes'), False
        except ValueError:
            pass
    for fmt, is_all_day in candidates:
        try:
            parsed = dt.datetime.strptime(raw, fmt)
            if is_all_day:
                return parsed.date().isoformat(), True
        except ValueError:
            continue
        try:
            pass
        except ValueError:
            continue
        return parsed.isoformat(timespec='minutes'), False
    raise ValueError("Animsatici tarihi gecersiz. due_iso icin 'YYYY-MM-DD' veya 'YYYY-MM-DDTHH:MM' kullan.")

def add_reminder(title: 'str', due_iso: 'str'='', notes: 'str'='', list_name: 'str'='', priority: 'str'='', all_day: 'bool'=False) -> 'str':
    if not title or not title.strip():
        return 'Animsatici basligi bos olamaz.'
    normalized_due = ''
    normalized_all_day = bool(all_day)
    if due_iso and due_iso.strip():
        try:
            normalized_due, inferred_all_day = _normalize_due_iso(due_iso)
        except ValueError as exc:
            return str(exc)
        normalized_all_day = normalized_all_day or inferred_all_day
    ok, raw = _run_helper('create_reminder', payload={'title': title.strip(), 'due_iso': normalized_due, 'notes': (notes or '').strip(), 'list_name': (list_name or '').strip(), 'priority': (priority or '').strip(), 'all_day': normalized_all_day}, timeout=25)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _permission_message()
        return f'Animsatici eklenemedi: {raw}'
    parsed_ok, detail, created = _parse_created_payload(raw)
    if not parsed_ok:
        low = detail.lower()
        if 'permission' in low or 'mach error 4099' in low:
            return _permission_message()
        return f'Animsatici eklenemedi: {detail}'
    now = dt.datetime.now()
    when = _format_due(created, now)
    list_suffix = f' [{created['list_name']}]' if created['list_name'] else ''
    return f'Animsatici eklendi: {when} - {created['title']}{list_suffix}'

_TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
_TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
_FAILED = {'delete': 'Anımsatıcı silinemedi', 'complete': 'Anımsatıcı tamamlanamadı'}
_WILL = {'delete': 'silerim', 'complete': 'işaretlerim'}

def reminder_line(item: 'dict', now: 'dt.datetime | None'=None) -> 'str':
    '''"yarın 09:00 - Dişçi [İş]": silme ve tamamlama cevaplarında (hata olursa ekranda da görünür).'''

    now = now or dt.datetime.now()
    if item['due_ts'] <= 0:
        when = 'tarihsiz'
    else:
        due = dt.datetime.fromtimestamp(item['due_ts'])
        day = {0: 'bugün', 1: 'yarın', -1: 'dün'}.get((due.date() - now.date()).days) or f'{due.day} {_TR_MONTHS[due.month]} {_TR_DAYS[due.weekday()]}'
        when = f'{day} tüm gün' if item.get('all_day') else f'{day} {due:%H:%M}'
    suffix = f' [{item['list_name']}]' if item.get('list_name') else ''
    return f'{when} - {item['title']}{suffix}'

def changed_text(action: 'str', items: 'list[dict]') -> 'str':
    lines = ' | '.join((reminder_line(r) for r in items[:5]))
    if len(items) > 1:
        verb = 'silindi' if action == 'delete' else 'tamamlandı olarak işaretlendi'
        return f'{len(items)} anımsatıcı {verb}: {lines}.'
    if action == 'delete':
        return f'Anımsatıcı silindi: {lines}.'
    return f'Tamamlandı olarak işaretlendi: {lines}.'

def not_found_text(action: 'str', by_id: 'bool'=False, dated: 'bool'=False) -> 'str':
    if by_id:
        return f'{_FAILED[action]}: artık listede yok (başka yerden silinmiş ya da tamamlanmış olabilir).'
    if dated:
        return f'{_FAILED[action]}: {'o tarihte '}bu ada uyan açık anımsatıcı bulamadım.'
    return f'{None}{None}{''}bu ada uyan açık anımsatıcı bulamadım.'

def multiple_text(action: 'str', matches: 'list[dict]', count: 'int') -> 'str':
    lines = ' | '.join((reminder_line(r) for r in matches[:5]))
    return f'Bu ada uyan {count} anımsatıcı var, hiçbirine dokunmadım; hangisi olduğunu söylersen {_WILL[action]}. Eşleşenler: {lines}'

def _fold(text: 'str') -> 'str':
    """Başlık karşılaştırması: büyük/küçük harf, şapka ve Türkçe ı/İ farkı yok (win_agenda._fold'un aynısı)."""

    text = unicodedata.normalize('NFKD', (text or '').replace('ı', 'i').replace('İ', 'i'))
    return ' '.join(''.join((c for c in text if not unicodedata.combining(c))).casefold().split())

def due_filter(due_iso: 'str') -> 'tuple[dt.datetime | None, bool]':
    '''due_iso → (yerel tarih/saat, saat de verilmiş mi); boşsa (None, False). Geçersizse ValueError.'''

    if not (due_iso or '').strip():
        return (None, False)
    normalized, date_only = _normalize_due_iso(due_iso)
    value = dt.datetime.fromisoformat(normalized)
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value, not date_only

def _widest(found: 'list[tuple[dict, str]]') -> 'list[dict]':
    '''Adaylardan başka bir adayın içinde kalmayanlar: "Dişçi" + "Dişçi randevusu" → yalnızca "Dişçi randevusu".'''

    return [r for r, n in found if not any((m != n in m for _r, m in found))]

def match_titles(rows: 'list[dict]', title: 'str', day: 'dt.datetime | None'=None, has_time: 'bool'=False, stamp: 'str'='due_ts') -> 'list[dict]':
    '''Ada göre eşleşenler (anımsatıcılar ve takvim; Swift'teki matchTitles ve telefondaki PhoneControl.match ile aynı
    kural). Önce tam ad, yoksa adı içeren, yoksa adı istenenin içinde geçen, yoksa çok kelimeli adın her kelimesi
    istenende bir kelimenin başı ("faturayı öde" → "Fatura öde"; 3 harften kısa kelimeler birebir: "Su iç", "sunum
    için"e uymaz). İçinde geçenlerden yalnızca başka bir adayın içinde kalmayanlar seçilir ("dişçi randevusunu" →
    "Dişçi" değil "Dişçi randevusu"); ayrı adlar birlikte geçiyorsa ("standup toplantısı": "Standup" ve "Toplantı")
    hepsi döner, kullanıcıya hangisi diye sorulur. Eskiden en uzun ad seçiliyordu ve yanlış kayıt silinebiliyordu.
    Tarih verildiyse o günküler; saat de verildiyse birden çok eşleşmede o dakikadakiler. stamp: zaman alanı.'''

    wanted = _fold(title)
    if not wanted:
        return []
    if day is not None:
        rows = [r for r in rows if r[stamp] if dt.datetime.fromtimestamp(r[stamp]).date() == day.date()]
    named = [(r, _fold(r['title'])) for r in rows]
    picked = [r for r, n in named if n == wanted] or [r for r, n in named if wanted in n]
    if not picked:
        picked = _widest([(r, n) for r, n in named if len(n) >= 3 if n in wanted])
    if not picked:
        said = wanted.split()
        picked = _widest([(r, n) for r, n in named if len(n.split()) > 1 if all((any((w == part or len(part) >= 3 and w.startswith(part) for w in said)) for part in n.split()))])
    if len(picked) > 1 and has_time:
        if day is not None:
            minute = day.replace(second=0, microsecond=0)
            picked = [r for r in picked
                 if r[stamp]
                 if dt.datetime.fromtimestamp(r[stamp]).replace(second=0) == minute] or picked
    return picked

def match_reminders(rows: 'list[dict]', title: 'str'='', due: 'dt.datetime | None'=None, has_time: 'bool'=False, reminder_id: 'str'='') -> 'list[dict]':
    """Swift'teki eşleştirmenin Python hâli (Windows'un yerel ajandası için). Kimlik verildiyse yalnızca o kayıt
    (ekrandaki ✓/×); yoksa ada göre (match_titles)."""

    if reminder_id:
        return [r for r in rows if r.get('id') == reminder_id]
    return match_titles(rows, title, due, has_time)

def pick_targets(action: 'str', rows: 'list[dict]', title: 'str'='', due_iso: 'str'='', reminder_id: 'str'='', every: 'bool'=False) -> 'tuple[list[dict], str]':
    '''Açık anımsatıcılardan silinecek/tamamlanacaklar → (hedefler, cevap). Cevap doluysa hiçbirine dokunulmaz.
    Eşleşenlerin hepsi aynı ad ve zamandaysa (yanlışlıkla iki kez eklenmiş) "hangisi?" diye sorulmaz, hepsi gider.'''

    if not (title or '').strip() and not reminder_id:
        return [], f'{_FAILED[action]}: anımsatıcının adı gerekli.'
    try:
        due, has_time = due_filter('' if reminder_id else due_iso)
    except ValueError as exc:
        return [], str(exc)
    picked = match_reminders(rows, title, due, has_time, reminder_id)
    if not picked:
        return [], not_found_text(action, bool(reminder_id), due is not None)
    same = len({(_fold(r['title']), r['due_ts']) for r in picked}) == 1
    if len(picked) > 1 and not every and not same:
        return [], multiple_text(action, picked, len(picked))
    return picked, ''

def _change(action: 'str', title: 'str', due_iso: 'str', list_name: 'str', every: 'bool', reminder_id: 'str') -> 'str':
    title, reminder_id = (title or '').strip(), (reminder_id or '').strip()
    if not title and not reminder_id:
        return f'{_FAILED[action]}: anımsatıcının adı gerekli.'
    try:
        due, has_time = due_filter('' if reminder_id else due_iso)
    except ValueError as exc:
        return str(exc)
    when = '' if due is None else due.isoformat(timespec='minutes') if has_time else due.date().isoformat()
    ok, raw = _run_helper('reminders_delete' if action == 'delete' else 'reminders_complete', payload={'title': title, 'id': reminder_id, 'due_iso': when, 'list_name': (list_name or '').strip(), 'delete_all_matches': bool(every)}, timeout=25)
    if not ok:
        detail = raw.lower()
        if 'permission_denied' in detail or 'not authorized' in detail or 'mach error 4099' in detail:
            return _permission_message()
        return f'{_FAILED[action]}: {raw}'
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return f'{_FAILED[action]}: yardımcıdan geçersiz yanıt geldi.'
    if not payload.get('ok', False):
        error = str(payload.get('error') or '')
        detail = str(payload.get('detail') or error or 'bilinmeyen sorun')
        if error == 'permission_denied' or 'permission' in detail.lower() or 'mach error 4099' in detail.lower():
            return _permission_message()
        if error == 'not_found':
            return not_found_text(action, bool(reminder_id), due is not None)
        if error == 'multiple_matches':
            matches = _rows(payload.get('matches') if isinstance(payload.get('matches'), list) else [])
            try:
                count = int(payload.get('count') or len(matches))
            except (TypeError, ValueError):
                count = len(matches)
            return multiple_text(action, matches, count)
        return f'{_FAILED[action]}: {detail}'
    items = _rows(payload.get('reminders') if isinstance(payload.get('reminders'), list) else [])
    if not items:
        return f'{_FAILED[action]}: yardımcıdan geçersiz yanıt geldi.'
    return changed_text(action, items)

def delete_reminder(title: 'str'='', due_iso: 'str'='', list_name: 'str'='', delete_all_matches: 'bool'=False, reminder_id: 'str'='') -> 'str':
    '''Açık bir anımsatıcıyı siler (sesle adıyla, ekrandan kimliğiyle).'''

    return _change('delete', title, due_iso, list_name, delete_all_matches, reminder_id)

def complete_reminder(title: 'str'='', due_iso: 'str'='', list_name: 'str'='', reminder_id: 'str'='') -> 'str':
    """Açık bir anımsatıcıyı tamamlandı olarak işaretler (Anımsatıcılar'da tamamlananlara geçer)."""

    return _change('complete', title, due_iso, list_name, False, reminder_id)

# WARNING: Decompyle incomplete

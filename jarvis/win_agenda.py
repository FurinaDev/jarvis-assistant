'''Yerel takvim ve anımsatıcılar (Windows): JARVIS'in kendi ajandası.

Mac'te takvim ve anımsatıcılar macOS'un EventKit'inden (Takvim ve Anımsatıcılar uygulamaları) okunur. Windows'ta
bir hesaba bağlı olmayan yerel bir ajanda: veri klasöründe agenda.json (herkese açık sürümde de çalışsın diye;
Outlook/Google eşitlemesi sonra, WINDOWS.md). Araç cevapları Mac'le aynı biçimde: actions/calendar.py ve
reminders.py'nin sorgu ve biçim işlevleri kullanılır; aralıklar Mac'teki Swift yardımcısıyla aynı (sıradaki 30
gün, ajanda 3 gün, hafta 7 gün; bitiş verilmezse +1 saat; silmede önce tam ad, yoksa içeren ad).

Anımsatıcının zamanı gelince JARVIS söyler (Mac'te bildirimi Anımsatıcılar uygulaması verir; Watcher). Söylenen
anımsatıcı kendiliğinden tamamlanmış sayılır, listede gecikmiş olarak birikmesin. Silme ve tamamlama sesle
(delete_reminder / complete_reminder) ve büyük görünümdeki ✓/× ile (kimlikle); eşleştirme Mac'le ortak
(reminders.pick_targets). JARVIS kapalıyken, uykudayken ya da bağlı değilken zamanı gelenler, söyleyebildiği ilk anda
"kaçırılan" olarak söylenir. Tüm gün anımsatıcıları o gün 09:00'da (Anımsatıcılar uygulamasının varsayılanı). Yeni
eklenen bir anımsatıcı en erken bir dakika sonra söylenir: geçmiş bir zamana yanlışlıkla kurulduysa iptal edilebilsin.
'''

from __future__ import annotations
import datetime as dt
import json
import os
import re
import threading
import time
import unicodedata
import uuid
from typing import Any, Callable
from . import paths
from .log import log
FILE = paths.DATA_DIR / 'agenda.json'
ALL_DAY_HOUR = 9
GRACE = 60
REPEAT_WINDOW = 120
CHECK_EVERY = 15.0
LATE = 300
_lock = threading.RLock()
on_change: 'Callable[[], None]' = lambda: None

def _load() -> 'dict[str, list[dict[str, Any]]]':
    with _lock:
        try:
            data = json.loads(FILE.read_text(encoding='utf-8'))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            spare = FILE.with_name(f'agenda.bozuk-{dt.datetime.now():%Y%m%d-%H%M%S}.json')
            try:
                FILE.replace(spare)
                log('ajanda dosyası okunamadı, kenara alındı:', spare.name)
            except OSError:
                pass
            return {'events': [], 'reminders': []}
        if not isinstance(data, dict):
            data = {}
        return {'events': [e for e in data.get('events') or [] if isinstance(e, dict)], 'reminders': [r for r in data.get('reminders') or [] if isinstance(r, dict)]}

def _save(data: 'dict[str, list[dict[str, Any]]]') -> 'None':
    with _lock:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, FILE)
    try:
        on_change()
    except Exception:
        return

def _fold(text: 'str') -> 'str':
    text = unicodedata.normalize('NFKD', (text or '').replace('ı', 'i').replace('İ', 'i'))
    return ' '.join(''.join((c for c in text if not unicodedata.combining(c))).casefold().split())

def _parse(text: 'str') -> 'tuple[dt.datetime | None, bool]':
    '''ISO ya da gg.aa.yyyy → (yerel saat, yalnızca tarih mi). Saat dilimli ise yerel saate çevrilir.'''

    raw = (text or '').strip()
    if not raw:
        return (None, False)
    try:
        if re.fullmatch('\\d{4}-\\d{2}-\\d{2}', raw):
            return dt.datetime.fromisoformat(raw), True
        if re.fullmatch('\\d{2}\\.\\d{2}\\.\\d{4}', raw):
            return dt.datetime.strptime(raw, '%d.%m.%Y'), True
    except ValueError:
        return (None, False)
    for fmt in ('%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S'):
        try:
            pass
        except ValueError:
            continue
        return dt.datetime.strptime(raw, fmt), False
    try:
        value = dt.datetime.fromisoformat(raw.replace('Z', '+00:00').replace(' ', 'T', 1))
    except ValueError:
        return (None, False)
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value, False

def _day_start(value: 'dt.datetime') -> 'dt.datetime':
    return value.replace(hour=0, minute=0, second=0, microsecond=0)

def _event_view(e: 'dict[str, Any]') -> 'dict[str, Any]':
    """Mac'teki calendar._parse_payload'un verdiği biçim."""

    return {'start_ts': int(e.get('start_ts', 0)), 'end_ts': int(e.get('end_ts', 0)), 'calendar': str(e.get('calendar', '')), 'title': str(e.get('title', '')) or 'Adsiz etkinlik', 'location': str(e.get('location', '')), 'all_day': bool(e.get('all_day', False))}

def _reminder_view(r: 'dict[str, Any]') -> 'dict[str, Any]':
    """Mac'teki reminders._parse_payload'un verdiği biçim (kimlik: büyük görünümdeki ✓/× ve silme için)."""

    return {'id': str(r.get('id', '') or ''), 'title': str(r.get('title', '')) or 'Adsiz animsatici', 'list_name': str(r.get('list_name', '')), 'notes': str(r.get('notes', '')), 'completed': bool(r.get('completed', False)), 'priority': int(r.get('priority', 0) or 0), 'due_ts': int(r.get('due_ts', 0) or 0), 'all_day': bool(r.get('all_day', False))}

def events_between(start: 'dt.datetime', end: 'dt.datetime') -> 'list[dict[str, Any]]':
    '''Aralıkla kesişen etkinlikler (Mac biçiminde), başlangıca göre sıralı.'''

    lo, hi = start.timestamp(), end.timestamp()
    rows = [_event_view(e) for e in _load()['events']]
    hits = [e for e in rows if e['start_ts'] < hi if e['end_ts'] > lo]
    return sorted(hits, key=(lambda e: (e['start_ts'], e['title'].lower())))

def _window(mode: 'str', payload: 'dict | None') -> 'tuple[dt.datetime, dt.datetime]':
    """Mac'teki Swift yardımcısının sorgu aralıkları."""

    now = dt.datetime.now()
    today = _day_start(now)
    if mode == 'range' and payload:
        return dt.datetime.fromisoformat(payload['start_iso']), dt.datetime.fromisoformat(payload['end_iso'])
    if mode == 'tomorrow':
        return today + dt.timedelta(days=1), today + dt.timedelta(days=2)
    if mode == 'week':
        return today, today + dt.timedelta(days=7)
    if mode == 'next':
        return now, now + dt.timedelta(days=30)
    if mode == 'agenda':
        return now, now + dt.timedelta(days=3)
    return today, today + dt.timedelta(days=1)

def get_calendar_events(query: 'str'='today', limit: 'int'=6) -> 'str':
    from .actions import calendar as cal
    window = cal._normalize_query(query)
    limit = max(1, min(60, int(limit or window['default_limit'])))
    events = events_between(*_window(window['helper_mode'], window.get('payload')))
    now = dt.datetime.now()
    if window['kind'] in {'next', 'agenda'}:
        events = [e for e in events if e['end_ts'] >= int(now.timestamp())]
    if not events:
        return window['empty']
    if window['kind'] == 'next':
        return f'Siradaki etkinlik: {cal._format_event_line(events[0], now)}.'
    selected = events[:limit]
    return '\n'.join([str(window['header']).format(count=len(selected))] + [f'- {cal._format_event_line(e, now)}' for e in selected])

def add_calendar_event(title: 'str', start_iso: 'str', end_iso: 'str'='', notes: 'str'='', location: 'str'='', calendar_name: 'str'='', all_day: 'bool'=False) -> 'str':
    from .actions import calendar as cal
    title, start_iso = (title or '').strip(), (start_iso or '').strip()
    if not title:
        return 'Takvime eklemek icin etkinlik basligi gerekli.'
    if not start_iso:
        return 'Takvime eklemek icin baslangic tarihi gerekli.'
    start, date_only = _parse(start_iso)
    if start is None:
        return 'Takvim etkinligi eklenemedi: Etkinlik baslangic tarihi gecersiz.'
    all_day = bool(all_day) or date_only
    end, _ = _parse(end_iso) if (end_iso or '').strip() else (None, False)
    if (end_iso or '').strip() and end is None:
        return 'Takvim etkinligi eklenemedi: Etkinlik bitis tarihi gecersiz.'
    if all_day:
        start = _day_start(start)
        end = (_day_start(end) if end and _day_start(end) >= start else start) + dt.timedelta(days=1)
    else:
        end = end or start + dt.timedelta(hours=1)
    if end <= start:
        return 'Takvim etkinligi eklenemedi: Etkinlik bitis tarihi baslangictan sonra olmali.'
    event = {'id': uuid.uuid4().hex[:12], 'title': title, 'start_ts': int(start.timestamp()), 'end_ts': int(end.timestamp()), 'all_day': all_day, 'location': (location or '').strip(), 'notes': (notes or '').strip(), 'calendar': (calendar_name or '').strip(), 'created': dt.datetime.now().isoformat(timespec='seconds')}
    with _lock:
        data = _load()
        data['events'].append(event)
        _save(data)
    return f'Takvime eklendi: {cal._format_event_line(_event_view(event), dt.datetime.now())}.'

def delete_calendar_event(title: 'str', start_iso: 'str'='', calendar_name: 'str'='', delete_all_matches: 'bool'=False) -> 'str':
    '''Eşleştirme ortak kuralla (Mac'teki ve telefondaki gibi; WINDOWS-NOTLAR 10.1): "en uzun ad kazanır" yok, iki
    farklı ad eşleşirse hiçbirine dokunulmaz ve sorulur; bugünden bir yıl ileri bakılır (tarih verildiyse o gün).'''

    from .actions import calendar as cal
    title = (title or '').strip()
    if not title:
        return 'Etkinlik silinemedi: etkinliğin adı gerekli.'
    day, date_only = _parse(start_iso)
    if (start_iso or '').strip() and day is None:
        return f'Etkinlik silinemedi: tarih anlaşılamadı ({start_iso}). yyyy-MM-dd ya da yyyy-MM-dd HH:mm ver.'
    lo = _day_start(day or dt.datetime.now())
    hi = lo + dt.timedelta(days=1 if day else 365)
    cal_name = _fold(calendar_name)
    with _lock:
        data = _load()
        pool = sorted((e for e in data['events']
             if e.get('start_ts', 0) < hi.timestamp() and e.get('end_ts', 0) > lo.timestamp() and (not cal_name or cal_name in _fold(e.get('calendar', '')))), key=(lambda e: e.get('start_ts', 0)))
    views = [(e, _event_view(e)) for e in pool]
    targets, answer = cal.event_targets([v for _e, v in views], title, day, day is not None and not date_only, delete_all_matches)
    if answer:
        return answer
    gone = {id(e) for e, v in views if any((v is t for t in targets))}
    data['events'] = [e for e in data['events'] if id(e) not in gone]
    _save(data)
    return cal.event_deleted_text(targets)

_PRIORITY = {'high': 1, 'yuksek': 1, 'yüksek': 1, 'important': 1, 'onemli': 1, 'önemli': 1, 'medium': 5, 'orta': 5, 'normal': 5, 'low': 9, 'dusuk': 9, 'düşük': 9}

def reminder_rows(mode: 'str'='all', limit: 'int'=20, list_name: 'str'='') -> 'list[dict[str, Any]]':
    """Açık (tamamlanmamış) anımsatıcılar, Mac'teki sorgu kipleriyle ve biçimiyle."""

    rows = [_reminder_view(r) for r in _load()['reminders'] if not r.get('completed')]
    wanted = _fold(list_name)
    if wanted:
        exact = [r for r in rows if _fold(r['list_name']) == wanted]
        partial = [r for r in rows if wanted in _fold(r['list_name'])]
        rows = exact or partial or rows
    now = time.time()
    today = _day_start(dt.datetime.now()).timestamp()
    if mode == 'today':
        rows = [r for r in rows if r['due_ts'] if not today <= r['due_ts'] if r['due_ts'] < today + 86400]
    elif mode == 'overdue':
        rows = [r for r in rows if r['due_ts'] if r['due_ts'] + (86400 if r['all_day'] else 0) < now]
    elif mode in ('next', 'upcoming'):
        span = 30 if mode == 'next' else 7
        rows = [r for r in rows
             if r['due_ts']
             if now <= r['due_ts'] + (86400 if r['all_day'] else 0)
             if r['due_ts'] <= now + span * 86400]
    rows.sort(key=(lambda r: (r['due_ts'] <= 0, r['due_ts'] or 0, r['title'].lower())))
    return rows[:1 if mode == 'next' else max(1, min(20, limit))]

def get_reminders(query: 'str'='upcoming', limit: 'int'=8, list_name: 'str'='') -> 'str':
    from .actions import reminders as rem
    mode, default_limit = rem._normalize_query(query)
    rows = reminder_rows(mode, max(1, min(20, int(limit or default_limit))), list_name)
    if not rows:
        return {'today': 'Bugun icin animsatici gorunmuyor.', 'overdue': 'Geciken animsatici gorunmuyor.', 'next': 'Siradaki animsaticiyi bulamadim.', 'all': 'Kayitli acik animsatici gorunmuyor.'}.get(mode, 'Yaklasan animsatici gorunmuyor.')
    now = dt.datetime.now()
    if mode == 'next':
        return f'Siradaki animsatici: {rem._format_reminder_line(rows[0], now)}.'
    header = {'today': f'Bugun icin {len(rows)} animsatici buldum:', 'overdue': f'Gecikmis {len(rows)} animsatici buldum:', 'all': f'Acik {len(rows)} animsatici buldum:'}.get(mode, f'Yaklasan {len(rows)} animsatici buldum:')
    return '\n'.join([header] + [f'- {rem._format_reminder_line(r, now)}' for r in rows])

def add_reminder(title: 'str', due_iso: 'str'='', notes: 'str'='', list_name: 'str'='', priority: 'str'='', all_day: 'bool'=False) -> 'str':
    from .actions import reminders as rem
    if not title or not title.strip():
        return 'Animsatici basligi bos olamaz.'
    due_ts, is_all_day = 0, bool(all_day)
    if due_iso and due_iso.strip():
        try:
            normalized, inferred = rem._normalize_due_iso(due_iso)
        except ValueError as exc:
            return str(exc)
        when, _ = _parse(normalized)
        if when is None:
            return "Animsatici tarihi gecersiz. due_iso icin 'YYYY-MM-DD' veya 'YYYY-MM-DDTHH:MM' kullan."
        is_all_day = is_all_day or inferred
        due_ts = int((_day_start(when) if is_all_day else when).timestamp())
    item = {'id': uuid.uuid4().hex[:12], 'title': title.strip(), 'due_ts': due_ts, 'all_day': is_all_day and bool(due_ts), 'notes': (notes or '').strip(), 'list_name': (list_name or '').strip(), 'priority': _PRIORITY.get(str(priority or '').strip().lower(), 0), 'completed': False, 'created': dt.datetime.now().isoformat(timespec='seconds')}
    now = time.time()
    with _lock:
        data = _load()
        twin = next((r for r in data['reminders']
             if _fold(str(r.get('title', ''))) == _fold(item['title'])
             if abs(int(r.get('due_ts', 0) or 0) - due_ts) <= 60 and now - _created_ts(r) <= REPEAT_WINDOW and (not r.get('completed') or r.get('said'))), None)
        if twin is None:
            data['reminders'].append(item)
            _save(data)
    view = _reminder_view(twin or item)
    suffix = f' [{view['list_name']}]' if view['list_name'] else ''
    when = rem._format_due(view, dt.datetime.now())
    if twin is not None and twin.get('said'):
        return f'Anımsatıcı az önce hatırlatıldı ve tamamlandı, yeniden eklenmedi: {when} - {view['title']}{suffix}'
    if twin is not None:
        return f'Anımsatıcı zaten var (az önce eklendi): {when} - {view['title']}{suffix}'
    past = ''
    if due_ts:
        if view['all_day']:
            if due_ts + 86400 <= now:
                pass
        elif due_ts < now - 60:
            past = ' (Dikkat: bu ' + ('gün' if view['all_day'] else 'saat') + ' geçti, bir dakika içinde hatırlatılacak; tarih ya da saat yanlışsa kullanıcıya sor, yanlışsa delete_reminder ile sil.)'
    return f'Animsatici eklendi: {when} - {view['title']}{suffix}{past}'

def _change_reminders(action: 'str', title: 'str', due_iso: 'str', list_name: 'str', every: 'bool', reminder_id: 'str') -> 'str':
    '''Açık bir anımsatıcıyı siler ya da tamamlar. Eşleştirme ve cevaplar Mac'le ortak (reminders.pick_targets,
    changed_text): birden çok eşleşmede hiçbirine dokunulmaz, "hangisi?" diye sorulur.'''

    from .actions import reminders as rem
    with _lock:
        data = _load()
        for r in data['reminders']:
            if r.get('id'):
                continue
            r['id'] = uuid.uuid4().hex[:12]
    rows = [_reminder_view(r) for r in data['reminders'] if not r.get('completed')]
    wanted = _fold(list_name)
    if wanted:
        if not reminder_id:
            rows = [r for r in rows if _fold(r['list_name']) == wanted] or [r for r in rows if wanted in _fold(r['list_name'])] or rows
    targets, answer = rem.pick_targets(action, rows, title, due_iso, (reminder_id or '').strip(), every)
    if answer:
        return answer
    ids = {t['id'] for t in targets}
    if action == 'delete':
        data['reminders'] = [r for r in data['reminders'] if str(r.get('id', '')) not in ids]
    else:
        stamp = dt.datetime.now().isoformat(timespec='seconds')
        for r in data['reminders']:
            if str(r.get('id', '')) in ids:
                r['completed'], r['done_at'] = True, stamp
    _save(data)
    return rem.changed_text(action, targets)

def still_open(views: 'list[dict[str, Any]]') -> 'list[dict[str, Any]]':
    '''Söylenmek üzere olan anımsatıcılardan hâlâ açık olanlar (konuşma bitmesi beklenirken silinmiş ya da
    tamamlanmış olabilir: app._reminders_due göndermeden hemen önce sorar).'''

    open_ids = {str(r.get('id', '')) for r in _load()['reminders'] if not r.get('completed')}
    return [v for v in views if v.get('id') in open_ids]

def delete_reminder(title: 'str'='', due_iso: 'str'='', list_name: 'str'='', delete_all_matches: 'bool'=False, reminder_id: 'str'='') -> 'str':
    '''Açık bir anımsatıcıyı siler (sesle adıyla, ekrandan kimliğiyle).'''

    return _change_reminders('delete', title, due_iso, list_name, delete_all_matches, reminder_id)

def complete_reminder(title: 'str'='', due_iso: 'str'='', list_name: 'str'='', reminder_id: 'str'='') -> 'str':
    '''Açık bir anımsatıcıyı tamamlandı olarak işaretler (listeden kalkar, silinmez).'''

    return _change_reminders('complete', title, due_iso, list_name, False, reminder_id)

BATCH = 6

def _created_ts(r: 'dict[str, Any]') -> 'float':
    try:
        return dt.datetime.fromisoformat(str(r.get('created', ''))).timestamp()
    except ValueError:
        return 0.0

def _alarm_ts(r: 'dict[str, Any]') -> 'float':
    '''Söyleneceği an: saatli anımsatıcıda zamanı, tüm gün olanda o gün 09:00, tarihsizde hiç (0). Tüm gün
    anımsatıcısı o gün 09:00'dan sonra eklendiyse bir saat sonra ("bugün markete gitmeyi hatırlat" eklendiği an
    söylenmesin). Hiçbiri eklendikten sonraki GRACE saniyeden önce değil: geçmişe kurulan yanlış bir anımsatıcı
    söylenip tamamlanmadan iptal edilebilsin.'''

    due = int(r.get('due_ts', 0) or 0)
    if not due:
        return 0.0
    created = _created_ts(r)
    if not r.get('all_day'):
        return max(float(due), created + GRACE)
    alarm = due + ALL_DAY_HOUR * 3600
    return created(created + 3600 if alarm < created < due + 86400 else float(alarm), created + GRACE)

class Watcher:
    '''Zamanı gelen anımsatıcıları söyletir. Ekranda her biri bir kez görünür (`show`); `ready()` True iken
    `say` ile söyletilir ve yalnızca not asistana gerçekten gittiyse (say True) tamamlanır. JARVIS uykuda, bağlı
    değil ya da söyleyemediyse kayıt açık kalır, sonraki denetimde yeniden denenir; geç kalınmışsa "kaçırılan" diye.'''

    ''
    ''
    ''
    ''
    def __init__(self, ready: 'Callable[[], bool]', say: 'Callable[[list[dict[str, Any]], bool], bool]', show: 'Callable[[dict[str, Any]], bool | None]') -> 'None':
        self.ready, self.say, self.show = ready, say, show
        self._shown = set()
        self._thread = None

    def start(self) -> 'None':
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name='anımsatıcılar')
            self._thread.start()

    def _loop(self) -> 'None':
        while True:
            try:
                self.check()
            except Exception as exc:
                log('anımsatıcı denetimi:', exc)
            time.sleep(CHECK_EVERY)

    def check(self, now: 'float | None'=None) -> 'None':
        now = now or time.time()
        due = sorted((r for r in _load()['reminders']
             if not r.get('completed') and _alarm_ts(r) and _alarm_ts(r) <= now), key=_alarm_ts)
        if not due:
            return
        for r in due:
            if r.get('id') in self._shown:
                continue
            if self.show(_reminder_view(r)) is not False:
                self._shown.add(r.get('id'))
        if not self.ready():
            return
        batch = due[:BATCH]
        late = any((now - max(_alarm_ts(r), _created_ts(r)) > LATE for r in batch))
        log(f'anımsatıcı zamanı: {len(batch)} adet' + (' (kaçırılan)' if late else '') + (f', {len(due) - len(batch)} sırada' if len(due) > len(batch) else ''))
        if not self.say([_reminder_view(r) for r in batch], late):
            log('anımsatıcı söylenemedi; açık kaldı, yeniden denenecek')
            return
        stamp, ids = dt.datetime.now().isoformat(timespec='seconds'), {r.get('id') for r in batch}
        with _lock:
            data = _load()
            for r in data['reminders']:
                if r.get('id') in ids:
                    r['completed'], r['done_at'], r['said'] = True, stamp, True
            _save(data)



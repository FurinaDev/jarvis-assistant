"""Yerleşik araçlar: şema (schemas.py) + her platformdaki uygulaması.

Windows uygulamaları ikinci aşamada `win=` olarak eklenecek. Şimdilik
`win=None` olan araçlar Windows'ta görünmez; beyin onları hiç duymaz.
"""

from __future__ import annotations
import threading
import time
from typing import Any, Callable
from .. import paths
from ..log import log
from .registry import (Registry, Tool, ToolContext, looks_like_error)
from .schemas import SCHEMAS

def _s(args: 'dict[str, Any]', key: 'str', default: 'str'='') -> 'str':
    return str(args.get(key, default) or default)

def _i(args: 'dict[str, Any]', key: 'str', default: 'int') -> 'int':
    try:
        return int(args.get(key, default) or default)
    except (TypeError, ValueError):
        return default

def _b(args: 'dict[str, Any]', key: 'str') -> 'bool':
    return bool(args.get(key, False))

def _f(args: 'dict[str, Any]', key: 'str') -> 'float':
    try:
        return float(args.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0

def _open_app(a, _c):
    from ..actions.open_app import open_app
    return open_app(_s(a, 'app_name')) or f'{_s(a, 'app_name')} açıldı.'

def _close_app(a, _c):
    from ..actions.open_app import close_app
    return close_app(_s(a, 'app_name'), _b(a, 'force'))

def _win_open_app(a, _c):
    from ..actions.win_apps import open_app
    return open_app(_s(a, 'app_name'))

def _win_close_app(a, _c):
    from ..actions.win_apps import close_app
    return close_app(_s(a, 'app_name'), _b(a, 'force'))

def _sys_info(a, c):
    from ..actions.sys_info import sys_info
    query = _s(a, 'query', 'all').lower()
    c.focus_panel('time' if query in {'date', 'saat', 'time', 'tarih', 'zaman'} else 'system')
    return sys_info(query)

def _win_sys_info(a, c):
    from ..actions.win_sys_info import sys_info
    query = _s(a, 'query', 'all').lower()
    c.focus_panel('time' if query in {'date', 'saat', 'time', 'tarih', 'zaman'} else 'system')
    return sys_info(query)

_HERE_WORDS = {'burası', 'şu anki konum', 'bulunduğum yer', 'my location', 'mevcut konum', 'current location', 'here', 'current', 'konumum'}

def _weather(a, _c):
    from ..actions.weather import get_weather_summary
    location = _s(a, 'location').strip()
    if location.lower() in _HERE_WORDS:
        location = ''
    return get_weather_summary(location or None)

def _cal_get(a, _c):
    from ..actions.calendar import get_calendar_events
    return get_calendar_events(_s(a, 'query', 'today'), _i(a, 'limit', 6))

def _cal_add(a, _c):
    from ..actions.calendar import add_calendar_event
    return add_calendar_event(_s(a, 'title'), _s(a, 'start_iso'), _s(a, 'end_iso'), _s(a, 'notes'), _s(a, 'location'), _s(a, 'calendar_name'), _b(a, 'all_day'))

def _cal_del(a, _c):
    from ..actions.calendar import delete_calendar_event
    return _once('etkinlik', a, 'start_iso', (lambda: delete_calendar_event(_s(a, 'title'), _s(a, 'start_iso'), _s(a, 'calendar_name'), _b(a, 'delete_all_matches'))))

def _rem_get(a, _c):
    from ..actions.reminders import get_reminders
    return get_reminders(_s(a, 'query', 'upcoming'), _i(a, 'limit', 8), _s(a, 'list_name'))

def _rem_add(a, _c):
    from ..actions.reminders import add_reminder
    return add_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'notes'), _s(a, 'list_name'), _s(a, 'priority'), _b(a, 'all_day'))

def _rem_del(a, _c):
    from ..actions.reminders import delete_reminder
    return _once('sil', a, 'due_iso', (lambda: _or_timer(delete_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'list_name'), _b(a, 'delete_all_matches')))))

def _rem_done(a, _c):
    from ..actions.reminders import complete_reminder
    return _once('tamamla', a, 'due_iso', (lambda: complete_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'list_name'))))

def _or_timer(text: 'str') -> 'str':
    '''Silinecek anımsatıcı yoksa ama çalışan bir zamanlayıcı varsa: "10 dakika sonra hatırlat" set_timer'la kurulur,
    "hatırlatmayı iptal et" denince kastedilen o olabilir.'''

    from ..timers import TIMERS
    if 'bulamadım' in text:
        if any((not t['done'] for t in TIMERS.panel()['timers'])):
            return text + ' Ama çalışan bir zamanlayıcı var; kastedilen o olabilir.'
    return text

ONCE_FOR = 10.0
_once_lock = threading.Lock()
_once_done: 'dict[str, tuple[float, str]]' = {}
_once_running: 'dict[str, threading.Event]' = {}

def _once(action: 'str', a: 'dict[str, Any]', when: 'str', work: 'Callable[[], str]') -> 'str':
    from ..actions.reminders import _fold
    key = '|'.join((action, _fold(_s(a, 'title')), _s(a, 'list_name').strip(), _s(a, 'calendar_name').strip(), _s(a, when).strip(), str(_b(a, 'delete_all_matches'))))
    while True:
        with _once_lock:
            done = _once_done.get(key)
            if done and time.monotonic() - done[0] < ONCE_FOR:
                log('aynı silme/tamamlama yinelendi, yeniden yapılmadı:', action)
                return done[1]
            running = _once_running.get(key)
            if running is None:
                _once_running[key] = threading.Event()
                break
        log('aynı silme/tamamlama aynı anda iki kez geldi, bir kez yapılıyor:', action)
        running.wait(30)
    try:
        try:
            result = work()
            if not looks_like_error(result):
                if 'hiçbirine dokunmadım' not in result:
                    with _once_lock:
                        _once_done[key] = time.monotonic(), result
        finally:
            pass
    finally:
        with _once_lock:
            _once_running.pop(key).set()
    return result

def _win_cal_get(a, _c):
    from ..win_agenda import get_calendar_events
    return get_calendar_events(_s(a, 'query', 'today'), _i(a, 'limit', 6))

def _win_cal_add(a, _c):
    from ..win_agenda import add_calendar_event
    return add_calendar_event(_s(a, 'title'), _s(a, 'start_iso'), _s(a, 'end_iso'), _s(a, 'notes'), _s(a, 'location'), _s(a, 'calendar_name'), _b(a, 'all_day'))

def _win_cal_del(a, _c):
    from ..win_agenda import delete_calendar_event
    return _once('etkinlik', a, 'start_iso', (lambda: delete_calendar_event(_s(a, 'title'), _s(a, 'start_iso'), _s(a, 'calendar_name'), _b(a, 'delete_all_matches'))))

def _win_rem_get(a, _c):
    from ..win_agenda import get_reminders
    return get_reminders(_s(a, 'query', 'upcoming'), _i(a, 'limit', 8), _s(a, 'list_name'))

def _win_rem_add(a, _c):
    from ..win_agenda import add_reminder
    return add_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'notes'), _s(a, 'list_name'), _s(a, 'priority'), _b(a, 'all_day'))

def _win_rem_del(a, _c):
    from ..win_agenda import delete_reminder
    return _once('sil', a, 'due_iso', (lambda: _or_timer(delete_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'list_name'), _b(a, 'delete_all_matches')))))

def _win_rem_done(a, _c):
    from ..win_agenda import complete_reminder
    return _once('tamamla', a, 'due_iso', (lambda: complete_reminder(_s(a, 'title'), _s(a, 'due_iso'), _s(a, 'list_name'))))

def _browser(a, _c):
    from ..actions.browser import browser_control
    return browser_control(a.get('action'), a.get('url'), a.get('query')) or 'Tamam.'

def _win_browser(a, _c):
    from ..actions.win_browser import browser_control
    return browser_control(a.get('action'), a.get('url'), a.get('query')) or 'Tamam.'

def _shell(a, _c):
    from ..actions.shell import shell_run
    return shell_run(_s(a, 'command')) or 'Komut çalıştırıldı.'

def _win_shell(a, _c):
    from ..actions.win_shell import shell_run
    return shell_run(_s(a, 'command')) or 'Komut çalıştırıldı.'

def _media(a, _c):
    from ..actions.media import play_media
    return play_media(_s(a, 'query'), _s(a, 'provider', 'auto'), bool(a.get('autoplay', True)))

def _win_media(a, _c):
    from ..actions.win_media import play_media
    return play_media(_s(a, 'query'), _s(a, 'provider', 'auto'), bool(a.get('autoplay', True)))

def _media_control(a, _c):
    from ..actions.media import media_control
    level = a.get('level')
    return media_control(_s(a, 'action'), _i(a, 'level', 0) if level is None else None)

def _win_media_control(a, _c):
    from ..actions.win_media import media_control
    level = a.get('level')
    return media_control(_s(a, 'action'), _i(a, 'level', 0) if level is None else None)

def _screen(a, _c):
    from ..actions.screen_vision import analyze_screen
    return analyze_screen(_s(a, 'query', 'Ekranda ne var?'), _s(a, 'target', 'active_window'))

def _win_screen(a, c: 'ToolContext'):
    from ..actions.win_screen import analyze_screen
    text, images = analyze_screen(_s(a, 'query', 'Ekranda ne var?'), _s(a, 'target', 'active_window'))
    c.images.extend(images)
    return text

def _wa_send(a, _c):
    from ..actions.whatsapp import send_whatsapp_message
    return send_whatsapp_message(_s(a, 'message'), _s(a, 'phone_number'), _s(a, 'recipient_name'), bool(a.get('send_now', True)), _s(a, 'app_target', 'auto'))

def _win_wa_send(a, _c):
    from ..actions.win_whatsapp import send_whatsapp_message
    return send_whatsapp_message(_s(a, 'message'), _s(a, 'phone_number'), _s(a, 'recipient_name'), bool(a.get('send_now', True)), _s(a, 'app_target', 'auto'))

def _wa_save(a, _c):
    from ..actions.whatsapp import save_whatsapp_contact
    return save_whatsapp_contact(_s(a, 'display_name'), _s(a, 'phone_number'), _s(a, 'aliases'))

def _show_map(a, c: 'ToolContext'):
    from ..geo import show_on_map
    text, spot = show_on_map(_s(a, 'query'))
    if spot:
        c.show_map(spot)
    return text

def _directions(a, c: 'ToolContext'):
    from ..geo import directions
    text, spot = directions(_s(a, 'destination'), _s(a, 'origin'), _s(a, 'mode', 'car'))
    if spot:
        c.show_map(spot)
    return text

def _web_search(a, _c):
    from ..brain.web_search import search
    return search(_s(a, 'query'))

def _timer_set(a, c: 'ToolContext'):
    import datetime as dt
    from ..timers import TIMERS, fmt
    seconds = _f(a, 'hours') * 3600 + _f(a, 'minutes') * 60 + _f(a, 'seconds')
    if seconds < 1:
        return 'Hata: süre anlaşılmadı. Kaç dakika olsun?'
    label = _s(a, 'label')
    try:
        timer = TIMERS.add(seconds, label)
    except ValueError as exc:
        return f'Hata: {exc}'
    c.focus_panel('timer')
    ends = dt.datetime.fromtimestamp(timer['ends']).strftime('%H:%M')
    name = f'{label} zamanlayıcısı' if label else 'Zamanlayıcı'
    return f"{name} kuruldu: {fmt(timer['total'])}, {ends}'de bitecek."

def _timer_cancel(a, _c):
    from ..timers import TIMERS
    gone = TIMERS.cancel(_s(a, 'label') or None)
    if not gone:
        return 'İptal edilecek zamanlayıcı bulunamadı.'
    if len(gone) > 1:
        return f'{len(gone)} zamanlayıcı iptal edildi.'
    return 'Zamanlayıcı iptal edildi.'

def _timer_status(_a, c: 'ToolContext'):
    from ..timers import TIMERS
    c.focus_panel('timer')
    return TIMERS.status_text()

def _stopwatch(a, c: 'ToolContext'):
    from ..timers import TIMERS
    c.focus_panel('timer')
    return TIMERS.stopwatch(_s(a, 'action', 'status'))

def _note_add(a, c: 'ToolContext'):
    from .. import notes
    note = notes.add(_s(a, 'text'))
    c.focus_panel('notes')
    return 'Not alındı.' if note else 'Hata: not boş.'

def _notes_list(a, c: 'ToolContext'):
    from .. import notes
    c.focus_panel('notes')
    return notes.summary(_i(a, 'limit', 10))

def _note_delete(a, _c):
    from .. import notes
    gone = notes.delete(_s(a, 'match'))
    if not gone:
        return 'Silinecek not bulunamadı.'
    if len(gone) == 1:
        return f'Silindi: {gone[0]['text']}'
    return f'{len(gone)} not silindi.'

def _notes_clear(_a, _c):
    from .. import notes
    return f'{notes.clear()} not silindi.'

def _webcam(a, c: 'ToolContext'):
    return c.set_webcam(_s(a, 'action', 'start').lower() == 'start')

def _offer_disable(a, c: 'ToolContext'):
    return c.app_action('offer_disable', {'said': _s(a, 'said'), 'ask': _s(a, 'ask')})

def _set_microphone(a, c: 'ToolContext'):
    return c.app_action('set_mic', {'enabled': _b(a, 'enabled')})

def _go_to_sleep(_a, c: 'ToolContext'):
    return c.app_action('sleep', {})

def _show_creator(a, c: 'ToolContext'):
    return c.app_action('creator', {'said': _s(a, 'said')})

def _chip_picker(a, c: 'ToolContext'):
    return c.app_action('chips', {'said': _s(a, 'said'), 'ask': _s(a, 'ask'), 'kill': _b(a, 'kill')})

def _quit_app(_a, c: 'ToolContext'):
    return c.app_action('quit', {})

def _secret_topic(a, c: 'ToolContext'):
    return c.app_action('secret_topic', {'topic': _s(a, 'topic', 'sir').lower()})

def _final_choice(a, c: 'ToolContext'):
    return c.app_action('final_choice', {'side': _s(a, 'side', 'jarvis').lower()})

def _find_files(a, c: 'ToolContext'):
    from .. import files
    folder = _s(a, 'folder', 'any').lower()
    kind = _s(a, 'kind', 'any').lower()
    when = _s(a, 'when', 'any').lower()
    found = files.find(_s(a, 'query'), folder if folder in (*files.FOLDERS, 'jarvis') else 'any', kind if kind in (*files.KINDS, 'screenshot', 'folder') else 'any', when, max(1, min(_i(a, 'limit', 5), files.MAX_SHOWN)))
    if not found:
        return 'Bu tarife uyan dosya yok. Aranan yerler: Masaüstü, Belgeler, İndirilenler, Resimler.'
    c.show_files([str(f.path) for f in found], False)
    low = lambda text: text.replace('İ', 'i').replace('I', 'ı').lower()
    rows = [f'{i}) {f.path.name} — {low(files.KIND_LABEL[f.kind])}, {files.ROOT_NAMES.get(f.root, f.root)}, {low(files.when_label(f.stamp))}' + (f', {files.human_size(f.size)}' if f.size else '') + f' · yol: {f.path}' for i, f in enumerate(found, 1)]
    more = ' Birden çok eşleşme var: hangisini istediğini sor ya da en uygununu söyle.' if len(found) > 1 else ''
    finder = "Dosya Gezgini'nde" if paths.IS_WIN else "Finder'da"
    return f'Sohbette {len(found)} dosya kartı gösterildi (kullanıcı açabilir, {finder} görebilir, kopyalayabilir).{more}\n' + '\n'.join(rows)

def _read_file(a, c: 'ToolContext'):
    from .. import files
    text, images = files.read(_s(a, 'path'))
    c.images.extend(images)
    return text

def _create_file(a, c: 'ToolContext'):
    from .. import files
    try:
        path = files.create(_s(a, 'name', 'JARVIS dosyası'), _s(a, 'content'), _s(a, 'format', 'txt'), _s(a, 'folder', 'jarvis').lower())
    except ValueError as exc:
        return f'Hata: dosya hazırlanamadı ({exc}).'
    c.show_files([str(path)], True)
    return f'Dosya hazırlandı ve sohbette kart olarak gösterildi: {path.name} ({files.where_name(path)}). Yol: {path}. Kullanıcıya kısaca söyle; içeriği baştan okuma.'

def _mem_save(a, _c):
    from ..memory import update_memory
    cat, key, val = _s(a, 'category', 'notes'), _s(a, 'key'), _s(a, 'value')
    if key and val:
        update_memory({cat: {key: {'value': val}}})
    return 'ok'

def _mem_delete(a, _c):
    from ..memory import delete_memory
    return delete_memory(_s(a, 'category'), _s(a, 'key'), _s(a, 'match_text'))

_IMPL = {'open_app': (_open_app, _win_open_app, None, True), 'close_app': (_close_app, _win_close_app, None, True), 'sys_info': (_sys_info, _win_sys_info, None, False), 'get_weather': (_weather, _weather, 'weather', False), 'get_calendar_events': (_cal_get, _win_cal_get, 'calendar', False), 'add_calendar_event': (_cal_add, _win_cal_add, 'calendar', True), 'delete_calendar_event': (_cal_del, _win_cal_del, 'calendar', True), 'get_reminders': (_rem_get, _win_rem_get, 'reminders', False), 'add_reminder': (_rem_add, _win_rem_add, 'reminders', True), 'delete_reminder': (_rem_del, _win_rem_del, 'reminders', True), 'complete_reminder': (_rem_done, _win_rem_done, 'reminders', True), 'browser_control': (_browser, _win_browser, None, False), 'web_search': (_web_search, _web_search, None, False), 'shell_run': (_shell, _win_shell, None, False), 'toggle_webcam': (_webcam, _webcam, None, False), 'set_timer': (_timer_set, _timer_set, None, True), 'cancel_timer': (_timer_cancel, _timer_cancel, None, True), 'timer_status': (_timer_status, _timer_status, None, False), 'stopwatch': (_stopwatch, _stopwatch, None, False), 'add_note': (_note_add, _note_add, None, True), 'list_notes': (_notes_list, _notes_list, None, False), 'delete_note': (_note_delete, _note_delete, None, True), 'clear_notes': (_notes_clear, _notes_clear, None, True), 'offer_disable_others': (_offer_disable, _offer_disable, None, False), 'secret_topic': (_secret_topic, _secret_topic, None, False), 'set_microphone': (_set_microphone, _set_microphone, None, False), 'go_to_sleep': (_go_to_sleep, _go_to_sleep, None, False), 'quit_app': (_quit_app, _quit_app, None, False), 'show_creator': (_show_creator, _show_creator, None, False), 'open_chip_picker': (_chip_picker, _chip_picker, None, False), 'final_choice': (_final_choice, _final_choice, None, False), 'find_files': (_find_files, _find_files, None, False), 'read_file': (_read_file, _read_file, None, False), 'create_file': (_create_file, _create_file, None, True), 'show_on_map': (_show_map, _show_map, 'map', False), 'get_directions': (_directions, _directions, 'map', True), 'play_media': (_media, _win_media, None, False), 'media_control': (_media_control, _win_media_control, None, False), 'analyze_screen': (_screen, _win_screen, None, False), 'save_memory': (_mem_save, _mem_save, None, False), 'delete_memory': (_mem_delete, _mem_delete, None, False), 'send_whatsapp_message': (_wa_send, _win_wa_send, None, False), 'save_whatsapp_contact': (_wa_save, _wa_save, None, False)}
_QUIET: 'set[str]' = set()
_QUIET |= {'secret_topic', 'final_choice'}
_QUIET.add('open_chip_picker')
_FREE_TEXT = {'web_search'}

def build() -> 'Registry':
    registry = Registry()
    for name, schema in SCHEMAS.items():
        if paths.IS_WIN:
            from . import win_schemas
            schema = win_schemas.apply(name, schema)
        mac, win, panel, sfx = _IMPL[name]
        registry.add(Tool(name=name, description=schema['description'], parameters=schema['parameters'], mac=mac, win=win, panel=panel, success_sfx=sfx, quiet=name in _QUIET, free_text=name in _FREE_TEXT))
    return registry


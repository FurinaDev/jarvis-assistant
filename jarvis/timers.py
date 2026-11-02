'''Zamanlayıcılar ve kronometre — sesle ("on dakikalık zamanlayıcı kur") ya da panelden.

Süre Python'da tutulur: panel kapalı olsa, pencere küçültülse bile zamanlayıcı
biter, alarm çalar ve asistan haber verir. Ekran kalan süreyi bitiş anından
kendisi hesaplar; her saniye Python'dan veri gitmez.
'''

from __future__ import annotations
import datetime as dt
import itertools
import threading
import time
from typing import Any, Callable
MAX_TIMERS = 5
MAX_SECONDS = 86400
FORGET_DONE_AFTER = 300.0

def fmt(seconds: 'float') -> 'str':
    '''125 → "2 dakika 5 saniye".'''

    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    parts = [f'{h} saat'] if h else []
    if m:
        parts.append(f'{m} dakika')
    if s and not h:
        parts.append(f'{s} saniye')
    return ' '.join(parts) or '0 saniye'

class Timers:
    def __init__(self) -> 'None':
        self._lock = threading.RLock()
        self._items = []
        self._ids = itertools.count(1)
        self._sw = {'running': False, 'started': 0.0, 'elapsed': 0.0}
        self._thread = None
        self.on_change = lambda: None
        self.on_done = lambda _t: None

    def add(self, seconds: 'float', label: 'str'='') -> 'dict[str, Any]':
        seconds = int(max(1, min(MAX_SECONDS, round(seconds))))
        with self._lock:
            pass
        active = [t for t in self._items if not t['done']]
        if len(active) >= MAX_TIMERS:
            raise ValueError(f'En fazla {MAX_TIMERS} zamanlayıcı aynı anda çalışabilir.')
        timer = {'id': next(self._ids), 'label': (label or '').strip()[:40], 'total': seconds, 'ends': time.time() + seconds, 'left': None, 'done': False, 'done_at': 0.0}
        self._items.append(timer)
        self._ensure_thread()
        self.on_change()
        return dict(timer)

    def _match(self, ref: 'Any') -> 'list[dict[str, Any]]':
        if ref in (None, ''):
            return list(self._items)
        if isinstance(ref, int) or str(ref).isdigit():
            return [t for t in self._items if t['id'] == int(ref)]
        needle = str(ref).casefold()
        return [t for t in self._items if needle in t['label'].casefold()]

    def cancel(self, ref: 'Any'=None) -> 'list[dict[str, Any]]':
        with self._lock:
            gone = self._match(ref)
        self._items = [t for t in self._items if t not in gone]
        if gone:
            self.on_change()
        return gone

    def extend(self, ref: 'Any', seconds: 'float') -> 'None':
        with self._lock:
            for t in self._match(ref):
                if t['done']:
                    continue
                t['total'] += int(seconds)
                if t['left'] is not None:
                    t['left'] += seconds
                else:
                    t['ends'] += seconds
        self.on_change()

    def pause(self, ref: 'Any') -> 'None':
        with self._lock:
            for t in self._match(ref):
                if t['done']:
                    continue
                if t['left'] is None:
                    t['left'] = max(0.0, t['ends'] - time.time())
        self.on_change()

    def resume(self, ref: 'Any') -> 'None':
        with self._lock:
            for t in self._match(ref):
                if t['left'] is not None:
                    t['ends'], t['left'] = time.time() + t['left'], None
        self._ensure_thread()
        self.on_change()

    def dismiss(self, ref: 'Any'=None) -> 'None':
        with self._lock:
            pass
        done = [t for t in self._match(ref) if t['done']]
        self._items = [t for t in self._items if t not in done]
        self.on_change()

    def ringing(self) -> 'bool':
        '''Biten ama kapatılmamış zamanlayıcı var mı (alarm çalıyor).'''

        with self._lock:
            return any((t['done'] for t in self._items))

    def remaining(self, t: 'dict[str, Any]') -> 'float':
        if t['done']:
            return 0.0
        if t['left'] is not None:
            return t['left']
        return max(0.0, t['ends'] - time.time())

    def status_text(self) -> 'str':
        with self._lock:
            items = sorted(self._items, key=self.remaining)
            sw = dict(self._sw)
        lines = []
        for t in items:
            name = f'{t['label']} zamanlayıcısı' if t['label'] else 'Zamanlayıcı'
            if t['done']:
                lines.append(f'{name} bitti.')
            elif t['left'] is not None:
                lines.append(f'{name} duraklatıldı, {fmt(t['left'])} kaldı.')
            else:
                ends = dt.datetime.fromtimestamp(t['ends']).strftime('%H:%M')
                lines.append(f"{name}: {fmt(self.remaining(t))} kaldı ({ends}'de bitecek).")
        if sw['running'] or sw['elapsed']:
            lines.append(f'Kronometre {'çalışıyor' if sw['running'] else 'durdu'}: {fmt(self.stopwatch_elapsed())}.')
        return ' '.join(lines) or 'Çalışan zamanlayıcı yok.'

    def stopwatch_elapsed(self) -> 'float':
        sw = self._sw
        return sw['elapsed'] + (time.time() - sw['started'] if sw['running'] else 0.0)

    def stopwatch(self, action: 'str') -> 'str':
        action = (action or 'status').lower()
        with self._lock:
            sw = self._sw
            if action == 'start' and not sw['running']:
                sw.update(running=True, started=time.time())
            elif action == 'stop' and sw['running']:
                sw.update(running=False, elapsed=self.stopwatch_elapsed(), started=0.0)
            elif action == 'reset':
                sw.update(running=False, started=0.0, elapsed=0.0)
        self.on_change()
        if action == 'start':
            return 'Kronometre başladı.'
        if action == 'reset':
            return 'Kronometre sıfırlandı.'
        state = 'durdu' if action == 'stop' or not self._sw['running'] else 'çalışıyor'
        return f'Kronometre {state}: {fmt(self.stopwatch_elapsed())}.'

    def panel(self) -> 'dict[str, Any]':
        with self._lock:
            timers = [dict(t) for t in self._items]
            sw = dict(self._sw)
        return {'key': 'timer', 'label': 'ZAMANLAYICI', 'kind': 'timer', 'timers': timers, 'stopwatch': sw, 'now': time.time()}

    def _ensure_thread(self) -> 'None':
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._watch, daemon=True, name='timers')
        self._thread.start()

    def _watch(self) -> 'None':
        while True:
            time.sleep(0.2)
            now = time.time()
            finished, changed = [], False
            with self._lock:
                for t in self._items:
                    if t['done']:
                        continue
                    if t['left'] is not None:
                        continue
                    if t['ends'] <= now:
                        t.update(done=True, done_at=now)
                        finished.append(dict(t))
            stale = [t for t in self._items if t['done'] if now - t['done_at'] > FORGET_DONE_AFTER]
            if stale:
                self._items = [t for t in self._items if t not in stale]
                changed = True
            idle = not any((not t['done'] for t in self._items))
            for t in finished:
                self.on_done(t)
            if finished or changed:
                self.on_change()
            if idle and not self._items:
                return


TIMERS = Timers()

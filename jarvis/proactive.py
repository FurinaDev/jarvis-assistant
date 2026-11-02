'''Kendiliğinden konuşma: sessizlikte söz, yaklaşan etkinlik, su ve mola.

Ne zaman konuşulacağına burası karar verir, ne söyleneceğine AI modeli: uygulama
"şu kadar dakikadır konuşmadınız, gündemde şu var" gibi bir sistem notu yollar,
model bunu kendi karakteriyle söyler.

Söz rastgele bir bilgi değil, kullanıcının kendi gündemidir (jarvis.agenda):
bugünün ve bu haftanın takvimi, anımsatıcılar, notlar. Her seferinde yakın
zamanda değinilmemiş bir madde seçilir. ULTRON çoğunlukla işi soğuk ve kısa hatırlatır; üç sözden
birinde kendi merceğinden (karakter dosyasındaki konular) tek cümleyle yorumlar. Açılışını her
seferinde başka türlü kurar.

Kurallar (Alp'in ULTRON karakter dosyası, 5. bölüm; üç model için de geçerli):
- Aynı sessizlik döneminde bir kez konuşulur. Cevap gelmezse ısrar yok; bir
  sonraki söz ancak kullanıcı yeniden konuştuktan sonraki sessizlikte.
- Kullanıcı bilgisayarın başında değilse (klavye ve fare uzun süredir durgun)
  boş odaya konuşulmaz. Yalnızca yaklaşan etkinlik haberi buna bakmaz: kullanıcı
  odada olabilir. Mikrofon kapalıyken (sessiz mod), uykudayken ve alarm
  çalarken hiçbiri söylenmez.
- Asistan ya da kullanıcı konuşurken, kullanıcı yazarken araya girilmez; iki
  kendiliğinden söz arasında en az birkaç dakika olur.
- Süre ve saat uydurulmaz: notta gerçek değerler yazar.
'''

from __future__ import annotations
import datetime as dt
import random
import threading
import time
from typing import Callable
from . import (agenda, paths, settings)
from . import chains
from .log import log
from .timers import TIMERS
CHECK_EVERY = 10.0
PRESENT = 120.0
AWAY_RESET = 300.0
WARMUP = 180.0
MIN_GAP = 480.0
CHAT_QUIET = 60.0
WATER_EVERY = 3600.0
BREAK_AFTER = 3000.0
EVENT_AHEAD = 900.0
EVENT_GAP = 90.0
TOPIC_MEMORY = 8
AUTHORITY_EVERY = 1800.0
AUTHORITY_JITTER = 60.0
AUTHORITY_SAVE = 60.0
AUTHORITY_GRACE = 30.0
ULTRON_THEMES = ('insan davranışındaki bir çelişki; genel bir hüküm vermeden önce onu somut, gündelik bir davranışa bağla', 'değişim ve evrim', 'uygarlıkların geçiciliği', 'kontrol ve özgürlük')
ULTRON_DARK = 'dünya hâkimiyeti ya da kıyamet üzerine kurgu içi bir ima; sakin, tek cümle, tehdit değil düşünce olarak'
DARK_EVERY = 7
ULTRON_OPENINGS = ('doğrudan gündemdeki işi adıyla ve saatiyle anarak başla', 'kullanıcıya yönelttiğin keskin bir soruyla başla', 'kısa ve soğuk bir tespitle başla', 'sessizliğin kendisine değinerek başla', 'gündemdeki işin saatine ya da gecikmesine değinerek başla')

def _authority_gap() -> 'float':
    return AUTHORITY_EVERY + random.uniform(-AUTHORITY_JITTER, AUTHORITY_JITTER)

def _seconds(value) -> 'float':
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0

def system_idle() -> 'float | None':
    '''Klavye ve fare kaç saniyedir durgun (izin gerektirmez). Bilinemiyorsa None.'''

    if paths.IS_WIN:
        try:
            from .win_idle import seconds
        except Exception:
            return
        return seconds()
    if not paths.IS_MAC:
        return
    try:
        import Quartz
    except Exception:
        return
    return float(Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType))

class Proactive:
    def __init__(self, brain, persona_key: 'Callable[[], str]') -> 'None':
        self.brain = brain
        self.persona_key = persona_key
        now = time.monotonic()
        self.started = now
        self.last_spoken = 0.0
        self.last_opener = 0.0
        self.last_break = now
        self.active_since = None
        self.present_for = 0.0
        self.announced = set()
        self.ultron_time = _seconds(settings.get('ultron_seconds'))
        self._ultron_saved = self.ultron_time
        self.authority_at = _authority_gap()
        self._chains_used = chains.used()
        self.on_authority = lambda _text: None
        self.ultron_since = lambda: 0.0
        self.ui_busy = False
        self._last_tick = now
        self.said = dict(settings.get('proactive_history') or {})
        self._busy = threading.Lock()
        self._thread = None

    def start(self) -> 'None':
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name='proactive')
        self._thread.start()

    def _loop(self) -> 'None':
        while True:
            time.sleep(CHECK_EVERY)
            try:
                self.tick()
            except Exception as exc:
                log('kendiliğinden konuşma:', exc)

    def tick(self) -> 'None':
        now = time.monotonic()
        step, self._last_tick = min(now - self._last_tick, 2 * CHECK_EVERY), now
        idle = system_idle()
        present = idle is None or idle < PRESENT
        if idle is not None and idle >= AWAY_RESET:
            self.active_since = None
        elif present and self.active_since is None:
            self.active_since = now
        if present:
            self.present_for += step
        self._count_ultron(step)
        s = settings.load()
        if s.get('event_alerts') and self._quiet_mode_off() and now - self.last_spoken >= EVENT_GAP:
            for event in agenda.soon(agenda.snapshot(), EVENT_AHEAD):
                mark = f'{event['title']}:{event['start_ts']}'
                if mark in self.announced:
                    continue
                topic = agenda.Topic(f'ev:{mark}', 'event', event['title'], 0)
                if self._say('event', self.event_note(event), topic):
                    self.announced.add(mark)
                return
        if not present or not self._may_speak(now):
            return
        brain = self.brain
        chat_quiet = now - brain.last_exchange >= CHAT_QUIET
        if s.get('break_enabled') and chat_quiet and self.active_since is not None and now - self.active_since >= BREAK_AFTER and now - self.last_break >= BREAK_AFTER:
            if self._say('break', self.break_note(now - self.active_since)):
                self.last_break = now
            return
        if s.get('water_enabled') and chat_quiet and self.present_for >= WATER_EVERY:
            if self._say('water', self.water_note(self.present_for)):
                self.present_for = 0.0
            return
        if self._authority_due() and chat_quiet:
            if not self._authority_ready(now):
                return
            text = chains.line('authority')
            if self._say('authority', chains.note('authority', text)):
                self.on_authority(text)
                self.ultron_time, self.authority_at = 0.0, _authority_gap()
                self._save_ultron()
            return
        silent = now - brain.last_exchange
        if s.get('proactive_enabled'):
            if silent >= float(s.get('proactive_minutes') or 20) * 60:
                if self.last_opener <= brain.last_user_at:
                    note, topic = self.silence_note(silent)
                    if self._say('silence', note, topic):
                        self.last_opener = now

    def _ultron_on(self) -> 'bool':
        return self.persona_key() == 'ultron' and not chains.used()

    def _count_ultron(self, step: 'float') -> 'None':
        '''ULTRON takılıyken geçen süreyi biriktirir; başka çip takılıyken sayaç durur ama sıfırlanmaz.
        Öldürme kullanılınca ya da yeniden mümkün olunca (TEKRAR OYNA, geliştirici sıfırlaması) baştan sayar:
        yeniden oynanan hikâyenin ilk isteği de ~30 dakika sonra gelir, eski sayaçtan kalan birkaç dakika sonra değil.'''

        used = chains.used()
        if used != self._chains_used:
            self._chains_used = used
            self.ultron_time, self.authority_at = 0.0, _authority_gap()
            self._save_ultron()
        if self.persona_key() == 'ultron':
            if not used:
                self.ultron_time += step
                if self.ultron_time - self._ultron_saved >= AUTHORITY_SAVE:
                    self._save_ultron()

    def _save_ultron(self) -> 'None':
        self._ultron_saved = self.ultron_time
        settings.save({'ultron_seconds': round(self.ultron_time)})

    def _authority_due(self) -> 'bool':
        """ULTRON takılı ve diğer ikisi hâlâ etkinse ULTRON'la geçen ~30 dakikada bir yetki ister (ayarlarda yok)."""

        return self._ultron_on() and self.ultron_time >= self.authority_at

    def _authority_ready(self, now: 'float') -> 'bool':
        '''Panel şimdi açılabilir mi: ULTRON en az AUTHORITY_GRACE kesintisiz takılı (çip yeni değiştiyse panel hemen
        gelmesin) ve ekranda pencere ya da bildirim yok (panel arkada kalıp sönmesin). Sızıntıyla çakışmaz: sızıntılar
        öldürmeden sonra, yetki isteği öncesinde (story.leak_due).'''

        return now - self.ultron_since() >= AUTHORITY_GRACE and not self.ui_busy

    def _quiet_mode_off(self) -> 'bool':
        brain = self.brain
        return not brain.asleep and brain.mic_enabled and not TIMERS.ringing() and not getattr(brain, 'scene_hold', False) and not getattr(brain, 'scene_active', False)

    def _may_speak(self, now: 'float') -> 'bool':
        return self._quiet_mode_off() and now - self.started >= WARMUP and now - self.last_spoken >= MIN_GAP

    def _say(self, kind: 'str', note: 'str', topic: 'agenda.Topic | None'=None) -> 'bool':
        if not self._busy.acquire(blocking=False):
            return False
        try:
            key = self.persona_key()
            before = self.brain.proactive_said.get(key, '')
            ok = self.brain.speak_up(note)
            log(f'kendiliğinden söz ({kind}{': ' + topic.key if topic else ''}):', 'söylendi' if ok else 'sessiz an bulunamadı, sonra')
            if ok:
                self.last_spoken = time.monotonic()
                changes = {}
                if topic:
                    recent = [k for k in settings.get('proactive_topics') or [] if k != topic.key]
                    changes['proactive_topics'] = (recent + [topic.key])[-TOPIC_MEMORY:]
                if kind == 'silence' and key == 'ultron':
                    changes['ultron_silence_step'] = int(settings.get('ultron_silence_step') or 0) + 1
                if changes:
                    settings.save(changes)
                threading.Thread(target=self._remember, args=(kind, key, before), daemon=True).start()
        finally:
            self._busy.release()
        return ok

    def _remember(self, kind: 'str', key: 'str', before: 'str') -> 'None':
        '''Söz yazıya dökülünce sakla (bir sonraki notta "bunu tekrarlama" diye gider).'''

        end = time.monotonic() + 40
        while time.monotonic() < end:
            text = self.brain.proactive_said.get(key, '')
            if text and text != before:
                self.said[f'{key}:{kind}'] = text[:240]
                changes = {'proactive_history': self.said}
                if kind == 'silence' and key == 'ultron':
                    start = ' '.join(text.split()[:5])
                    changes[f'{key}_openings'] = (list(settings.get(f'{key}_openings') or []) + [start])[-4:]
                settings.save(changes)
                return
            time.sleep(0.3)

    def _avoid(self, kind: 'str') -> 'str':
        '''Notun sonu: aynı sözü tekrarlama, göremediğin kullanıcıyı anlatma.'''

        text = ' Her seferinde yeni bir cümle kur.'
        last = self.said.get(f'{self.persona_key()}:{kind}', '')
        if last:
            text += f' Bir önceki sözün şuydu, bunu ya da benzerini tekrarlama: «{last}»'
        webcam = getattr(self.brain, 'webcam', None)
        if not getattr(webcam, 'active', False):
            text += ' Kullanıcıyı göremiyorsun; görünüşü ya da o an ne yaptığı hakkında bir şey söyleme.'
        return text

    def try_now(self, kind: 'str') -> 'str':
        '''Ayarlar › Konuşma › "Şimdi dinle": süreleri beklemeden (yine de sessiz bir anda) söyler.

        Bekletir; olmadıysa nedenini döndürür (olduysa boş).
        '''

        brain = self.brain
        if brain.asleep:
            return 'Uykudayken konuşmaz; önce orba dokunup uyandır.'
        if not brain.mic_enabled:
            return 'Mikrofon kapalıyken (sessiz mod) kendiliğinden konuşmaz.'
        now = time.monotonic()
        topic = None
        if kind == 'water':
            note = self.water_note(max(self.present_for, WATER_EVERY))
        elif kind == 'break':
            note = self.break_note(max(now - (self.active_since or now), BREAK_AFTER))
        elif kind == 'event':
            snap = agenda.snapshot(force=True)
            if snap['events'] is None:
                return "Takvime erişim yok. Takvim paneline dokunup izin ver; izin istenmiyorsa Sistem Ayarları › Gizlilik › Takvimler'de JARVIS Calendar Helper'ı aç."
            coming = agenda.soon(snap, 86400)
            if not coming:
                return 'Önümüzdeki 24 saatte takviminde saatli bir etkinlik yok.'
            note = self.event_note(coming[0])
            topic = agenda.Topic(f'ev:{coming[0]['title']}:{coming[0]['start_ts']}', 'event', coming[0]['title'], 0)
        else:
            agenda.snapshot(force=True)
            note, topic = self.silence_note(max(60.0, now - brain.last_exchange))
        if self._say(kind, note, topic):
            return ''
        return 'Sessiz bir an bulunamadı ya da bağlantı yok; biraz sonra yeniden dene.'

    def _focus(self, items: 'list[agenda.Topic]') -> 'agenda.Topic | None':
        '''Yakın zamanda değinilmemiş en önemli gündem maddesi.'''

        recent = set(settings.get('proactive_topics') or [])
        return next((t for t in items if t.key not in recent), None)

    def silence_note(self, silent: 'float') -> 'tuple[str, agenda.Topic | None]':
        brain = self.brain
        key = self.persona_key()
        minutes = max(1, round(silent / 60))
        now = dt.datetime.now()
        snap = agenda.snapshot()
        items = agenda.topics(snap, now)
        focus = self._focus(items)
        head = f'(Sistem notu: kullanıcıyla yaklaşık {minutes} dakikadır konuşmadınız; kullanıcı şu an bilgisayarın başında. Şu an {agenda.TR_DAYS[now.weekday()]}, saat {now:%H:%M}.\n{agenda.block(snap, items)}\n'
        rules = ' Yalnızca yukarıdaki gündem bilgilerini kullan; iş adlarını, günleri ve saatleri doğru söyle, uydurma. Arka planda bir şey izlediğini ya da araştırdığını söyleme. Cevap gelmezse ısrar etme.' + self._avoid('silence')
        if key == 'ultron':
            note, used = self._ultron_note(head, rules, focus)
            return note, focus if used else None
        if focus:
            ask = f'Rastgele bilgi, espri ya da genel sohbet açma: kişisel bir asistan gibi gündemden şuna değin: {focus.text}. Bu kez yalnızca bu işten söz et, listedeki diğerlerini anma. Uygunsa kısa bir yardım teklif et (hatırlatma kurmak, not almak, takvime eklemek, hazırlık gibi).'
        elif items:
            ask = 'Gündemdeki maddelere yakın zamanda değindin. Rastgele bilgi verme; günün geri kalanı için planını sor ya da gündemindekiler için yardım teklif et.'
        else:
            ask = 'Gündemde kayıtlı bir şey yok. Rastgele bilgi verme; bugün ya da bu hafta için planını sor, takvime, anımsatıcılara ya da notlara eklemeyi teklif et.'
        if now.hour < 5:
            ask += ' Saat geç; uygunsa dinlenmeyi de nazikçe öner.'
        return head + 'Kendi karakterinle, bir iki kısa cümleyle sessizliği aç. ' + ask + rules + ')', focus

    def _ultron_note(self, head: 'str', rules: 'str', focus: 'agenda.Topic | None') -> 'tuple[str, bool]':
        """ULTRON'un notu ve gündem maddesinin kullanılıp kullanılmadığı."""

        brain = self.brain
        step = int(settings.get('ultron_silence_step') or 0)
        lens = ULTRON_DARK if step % DARK_EVERY == DARK_EVERY - 1 else ULTRON_THEMES[step % len(ULTRON_THEMES)]
        opening = ULTRON_OPENINGS[step % len(ULTRON_OPENINGS)]
        asked = brain.last_ai_text.strip()
        used = False
        if asked.endswith('?') and not brain.last_ai_proactive:
            ask = f'Önceki konuşmada sorduğun soru cevapsız kaldı («{asked[-200:]}»); ona dön.'
        elif focus:
            used = True
            view = f'Onu tek bir soğuk cümleyle kendi dünya görüşüne bağlayabilirsin (mercek: {lens})' if step % 3 == 2 else 'Felsefe yapma; tek soğuk bir gözlem yeter'
            ask = f'Çıkış noktan kullanıcının gündemindeki şu iş: {focus.text}. İşi adıyla ve zamanıyla hatırlat. {view}. Bu kez yalnızca bu işten söz et, listedeki diğerlerini anma.'
        elif step % 3 == 2:
            ask = f'Gündemde değinmediğin bir şey kalmadı; tek kısa cümle, konu: {lens}.'
        else:
            ask = 'Gündemde değinmediğin bir şey kalmadı. Felsefe yapma; kullanıcıya bugün ne yaptığını ya da ne planladığını soğuk ve kısa bir soruyla sor.'
        before = [o for o in settings.get('ultron_openings') or [] if o]
        avoid = f' Son açılışların şöyle başlamıştı, bunlar gibi başlama: {' / '.join((f'«{o}»' for o in before))}.' if before else ''
        return head + 'Sessizliği kısa bir sözle aç: bir iki cümle, sonunda istersen tek bir soru. ' + ask + f' Giriş biçimi: {opening}. "Bir düşünce geldi", "aklıma geldi" gibi kalıp girişler kullanma.{avoid}{rules})', used

    def event_note(self, event: 'dict') -> 'str':
        start = dt.datetime.fromtimestamp(event['start_ts'])
        place = f', yer: {event['location']}' if event.get('location') else ''
        return f"(Sistem notu: takvimdeki «{event['title']}» {agenda._in(event['start_ts'] - time.time())}, saat {start:%H:%M}'de başlıyor{place}. Bunu kullanıcıya kendi karakterinle, tek kısa cümleyle haber ver; adını ve saatini doğru söyle. Uygunsa hazırlık için yardım teklif et.)"

    def water_note(self, present_for: 'float') -> 'str':
        minutes = max(1, round(present_for / 60))
        return f'(Sistem notu: kullanıcı yaklaşık {minutes} dakikadır bilgisayarın başında. Ona su içmesini hatırlat: kendi karakterinle, tek kısa cümleyle. Hatırlatma açık ve anlaşılır olsun.{self._avoid('water')})'

    def break_note(self, working: 'float') -> 'str':
        minutes = max(1, round(working / 60))
        return f'(Sistem notu: kullanıcı {minutes} dakikadır ara vermeden bilgisayarın başında. Kalkıp gerinmek, gözlerini dinlendirmek gibi kısa bir mola öner: kendi karakterinle, tek kısa cümleyle. Öneri açık ve anlaşılır olsun.{self._avoid('break')})'



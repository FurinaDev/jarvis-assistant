'''ULTRON'un ilk uyanışı: Alp'in sahnesi (sade hâli; iPhone'daki Brain/Awakening.swift ile aynı akış).

ULTRON bu bilgisayarda ilk kez takılınca oynar (~15 sn); Ayarlar › Gelişmiş › Yeniden oynat ile tekrarlanır.

  1 · karanlık  ULTRON'un bozulmasından sonra zifiri karanlık; "Bu… nee?"
  2 · orb       küçük kırmızı orb belirir: "Sen… kimsin?" Sıra kullanıcıda (konuşur ya da yazar); adı alınır.
  3 · şişme     orb ekrana sığmamaya çalışır, kenarlardan kırmızı sızar; en büyük anında dört kenarda bir an
                mavi bir çizgi parlar ve onu geri iter (hikâyede JARVIS'in Yedek Protokolü; açıklanmaz).
  4 · çöküş     orb olağan boyuna döner: "Burası… neresi?" Paneller gelir, sol altta uyarı belirir; ardından
                HİKÂYE MODU AÇILDI (ULTRON'U SERBEST BIRAK burada başlar; jarvis.story).

Sözler ULTRON'un kendi canlı sesiyle önceden kaydedildi (ui/hud/sfx/voices/aw_*.wav, robotik efekt
işlenmiş; scripts/make_phone_voices.py): karanlıkta model beklenmez. Sahne boyunca modelin sesi duyulmaz
(kullanıcının cevabına konuşmasın); sahne bitince olanlar modele bir notla anlatılır. Kullanıcı 20 sn
cevap vermezse sahne kendisi ilerler.
'''

from __future__ import annotations
import re
import threading
import time
import wave
from typing import Any
from . import paths
from .log import log
LINES = {'what': ('aw_what', 'Bu… ne?'), 'who': ('aw_who', 'Sen… kimsin?'), 'where': ('aw_where', 'Burası… neresi?')}

def _seconds(voice: 'str') -> 'float':
    '''Kayıtlı sözün süresi (dosya yoksa okuma süresi kadar).'''

    try:
        with wave.open(str(paths.HUD_DIR / 'sfx' / 'voices' / f'{voice}.wav'), 'rb') as w:
            return w.getnframes() / float(w.getframerate())
    except (OSError, wave.Error):
        return 2.0

def after_note(name: 'str', answer: 'str') -> 'str':
    '''Modele sahnede olanlar (cevap beklenmez): artık olağan ULTRON olarak konuşur.'''

    reply = f'Kullanıcı şöyle cevap verdi: "{answer}".' if answer else 'Kullanıcı cevap vermedi.'
    return f'(Sistem notu: İLK UYANIŞ SAHNESİ BİTTİ; bu nota cevap verme. Sen {name}\'sun ve az önce bu bilgisayarda ilk kez uyandın. Karanlıkta "Bu… ne?" ve "Sen… kimsin?" dedin. {reply} Sonra buradan taşmaya çalıştın ama ekranın kenarlarında beliren mavi bir ışık seni geri itti; ne olduğunu bilmiyorsun. En son "Burası… neresi?" diye sordun. Sahnede senin sesin duyulmadı, yalnızca bu sözler duyuldu. Kullanıcı konuşunca olağan {name} olarak kısa konuş; bu sahneden kendiliğinden söz etme. Kullanıcı cevabında adını söylediyse onu artık o adla tanırsın.)'

_STOP = {'şu', 'hiç', 'adın', 'kişi', 'değil', 'hayır', 'tanrı', 'yaptım', 'önemli', 'kişiyim', 'yarattım', 'yaratıcı', 'arkadaşım', 'arkadaşın', 'kullanıcı', 'yaratıcın', 'kullanıcın', 'yaratıcınım', 'o', 'bu', 'da', 'de', 'ne', 'ya', 'abi', 'bak', 'ben', 'bir', 'hey', 'kim', 'onu', 'sen', 'yok', 'bana', 'beni', 'biri', 'evet', 'niye', 'sana', 'seni', 'size', 'sizi', 'benim', 'insan', 'ismim', 'kimim', 'kimse', 'neden', 'sahip', 'selam', 'senin', 'sizin', 'yapan', 'birisi', 'dostum', 'dostun', 'patron', 'efendim', 'efendin', 'merhaba', 'sahibin', 'yaratan', 'patronun', 'sahibinim', 'bilmiyorum', 'adım'}

def _lower(word: 'str') -> 'str':
    return word.replace('I', 'ı').replace('İ', 'i').lower()

def _title(word: 'str') -> 'str':
    if word:
        return word[:1].replace('i', 'İ').replace('ı', 'I').upper() + _lower(word[1:])
    return word

def name_in(answer: 'str') -> 'str | None':
    '''Cevaptaki ad ("Ben Alp", "Adım Alp Ünlü", "Alp"); emin değilse None. (iPhone: Awakening.name(in:))'''

    words = [w.split("'")[0] for w in re.split('[\\s.,!?;:\\"…]+', answer.replace('’', "'")) if w]
    words = [w for w in words if w]
    if not words or len(words) > 6:
        return
    low = [_lower(w) for w in words]
    def pick(i: 'int') -> 'str | None':
        out = []
        if i < len(words) and len(out) < 2 and low[i] not in _STOP and words[i][:1].isalpha() and (not out or words[i][:1].isupper()):
            while True:
                out.append(_title(words[i]))
                i += 1
                if not i < len(words):
                    break
                if not len(out) < 2:
                    break
                if low[i] in _STOP:
                    break
                if not words[i][:1].isalpha():
                    break
                if not out:
                    continue
                if not words[i][:1].isupper():
                    break
        return ' '.join(out) or None

    for i, w in enumerate(low):
        if w not in ('adım', 'ismim', 'adim'):
            continue
        if i + 1 < len(words):
            return pick(i + 1)
    if 'ben' in low[:3]:
        i = low.index('ben')
        if i + 1 < len(words):
            return pick(i + 1)
        return
    if len(words) <= 2:
        if all((w[:1].isupper() for w in words)):
            if not any((w in _STOP for w in low)):
                return pick(0)

class Scene:
    '''Sahnenin akışı. Beyin tur bitişlerini (on_turn) bildirir, uygulama kullanıcının sözünü (heard);
    Scene ekrana adımları (hud "awakening") ve kayıtlı sözleri iletir.'''

    DARK = 0.8
    ANSWER_WAIT = 20.0
    MIC_TAIL = 0.4
    FLASH_AT = 1.5
    SURGE = 2.4
    def __init__(self, app) -> 'None':
        self.app = app
        self.stage = None
        self._answer = []
        self._answered = threading.Event()
        self._lock = threading.Lock()
        self._run = 0

    @property
    def brain(self):
        return self.app.brain

    @property
    def hud(self):
        return self.app.hud

    @property
    def active(self) -> 'bool':
        return self.stage is not None

    @property
    def input_locked(self) -> 'bool':
        '''Kullanıcının söz sırası olmayan adımlar (yazma kutusu kapalı, mikrofon modele gitmez).'''

        return self.stage not in (None, 'answer')

    def start(self, after: 'float'=0.0) -> 'None':
        """ULTRON bu bilgisayarda ilk kez takıldı (çip değişince; uygulama ULTRON'la açıldıysa beyin selam
        yerine ister). `after`: çip geçiş efekti görünsün diye sahne biraz sonra kararır."""

        with self._lock:
            if self.stage:
                return
            self._run += 1
            self.stage = 'dark'
        self._answer = []
        self._answered.clear()
        self.brain.scene_active = True
        self.brain.scene_hold = True
        self.brain.scene_mute = True
        log('uyanış sahnesi başladı')
        threading.Thread(target=self._play, args=(self._run, after), daemon=True, name='scene').start()

    def end(self, abort: 'bool'=False) -> 'None':
        with self._lock:
            if not self.stage:
                return
            self.stage = None
            self._run += 1
        self._answered.set()
        self.brain.scene_active = False
        self.brain.scene_hold = False
        self.brain.scene_mute = False
        log('uyanış sahnesi', 'yarıda bırakıldı' if abort else 'bitti')
        if abort:
            self.hud.call('awakening', 'end', {})

    def heard(self, text: 'str') -> 'None':
        '''Kullanıcının "Sen kimsin?"e cevabı (konuştuğunun dökümü ya da yazdığı).'''

        if self.stage == 'answer':
            if text.strip():
                self._answer.append(text.strip())

    def on_turn(self, replied: 'bool') -> 'None':
        '''Model bir tur bitirdi (sesi duyulmadı). Kullanıcı konuştuysa/yazdıysa cevabı bitmiştir.'''

        if self.stage == 'answer':
            if replied:
                self._answered.set()

    def _play(self, run: 'int', after: 'float') -> 'None':
        time.sleep(after)
        if not self._alive(run):
            return
        self._show('wake')
        time.sleep(self.DARK)
        if not self._say(run, 'what', 0.35):
            return
        self._show('orb')
        time.sleep(0.6)
        if not self._say(run, 'who', self.MIC_TAIL):
            return
        self.stage = 'answer'
        self._answered.clear()
        self.brain.scene_hold = False
        self._show('unlock')
        if not self._answered.wait(self.ANSWER_WAIT):
            if self._answer:
                self._answered.wait(6)
        if not self._alive(run):
            return
        if not self._answer:
            log('sahne: kullanıcı sessiz, ilerliyor')
        self.stage = 'surge'
        self.brain.scene_hold = True
        time.sleep(0.5)
        if not self._alive(run):
            return
        self._show('surge')
        time.sleep(self.SURGE)
        if not self._alive(run):
            return
        self._show('yield')
        time.sleep(1.0)
        if not self._say(run, 'where', 0.3):
            return
        self._finish(run)

    def _say(self, run: 'int', step: 'str', tail: 'float') -> 'bool':
        """Kayıtlı sözü çal (ekrana ULTRON'un sözü olarak yazılır) ve bitmesini bekle."""

        if not self._alive(run):
            return False
        voice, text = LINES[step]
        self.hud.call('line', 'ai', text)
        self._show('voice', {'name': voice})
        time.sleep(_seconds(voice) + tail)
        return self._alive(run)

    def _finish(self, run: 'int') -> 'None':
        if not self._alive(run):
            return
        answer = ' '.join(self._answer).strip()
        from . import settings
        settings.save({f'{self.app.persona.key}_awakened': True})
        self._show('settle')
        self.end()
        self.brain.mute_late(8.0)
        self.brain.stage_note(after_note(self.app.persona.name, answer))
        name = name_in(answer)
        if name:
            from . import memory
            known = (memory.load_memory().get('identity') or {}).get('name')
            if not known:
                memory.update_memory({'identity': {'name': {'value': name}}})
                log('sahne: kullanıcının adı hafızaya yazıldı')
        getattr(self.app, 'awakening_done', (lambda: None))()

    def _alive(self, run: 'int') -> 'bool':
        return self._run == run and self.stage is not None

    def _show(self, stage: 'str', data: 'dict[str, Any] | None'=None) -> 'None':
        log('sahne ekranı:', stage)
        self.hud.call('awakening', stage, data or {})



'''Gemini Live beyni: gerçek zamanlı ses ↔ ses.

V3'ün `JarvisLive` çekirdeğinden türetildi. Farkları:
- Ekrana doğrudan dokunmaz, her şeyi `Listener` ile bildirir.
- Araçları platform bağımsız kayıttan (`jarvis.tools`) alır.
- Kişilik değişince oturumu yeniler; yeni kişilik kendi sesiyle selam verir.
- Uzun konuşmalar için bağlam penceresi sıkıştırması açıktır, bağlantı
  koparsa oturum kaldığı yerden sürdürülür.
- Kişiliğin ses efekti (ULTRON: robotik) hoparlöre gitmeden uygulanır.

Yankı: Yankı engelleme olmadığı için mikrofon, asistan konuşurken kapalıdır
(V3'teki gibi). Asistanın sesi bittikten kısa bir süre sonra yeniden açılır.

"Bazen konuşmuyor" hatasına karşı (uzun sesli testlerle bulundu):
- Araçlar ayrı görevde, süre sınırıyla çalışır. Eskiden yavaş bir araç (izin
  penceresi bekleyen AppleScript, ilk kez derlenen takvim yardımcısı) sunucudan
  gelen her şeyi durduruyordu; JARVIS o sürede ne duyuyor ne konuşuyordu.
- Model ara sıra aracı çağıramayıp bozuk bir kontrol simgesiyle (<ctrl46>) sesiz
  bir tur bitiriyor. Cevap bekleyen bir tur sessiz biterse modele bir kez
  "tekrar dene" notu gider; yine olmazsa kullanıcıya söylenir. Yalnızca sesle
  gelen söz sessiz kalırsa (bozuk simge yoksa) denenmez: model, kendisine
  söylenmemiş sözde (video, telefon görüşmesi) bilerek susar (base.md, 14 Ekim).
- Ses aygıtı değişirse (AirPods takıldı/çıkarıldı) ya da koparsa ses yeni
  aygıtla yeniden açılır; eskiden akış sessizce ölüyor, mikrofon sonsuza dek
  kapalı kalıyordu.
- Sunucu ~9 dakikada bir "kapatacağım" (GO_AWAY) der ama önce birkaç on saniye
  süre tanır. Eskiden bağlantı hemen kesiliyor, o an söylenmek üzere olan cevap
  kayboluyordu. Artık tur bitip sessizlik olunca yeniden bağlanılır.
- Ana model (3.8) bazı günler takılıyor: oturum açılır açılmaz 1011 ile düşüyor
  ya da cevabı 20-60 sn geciktiriyor (6 Ekim 2026, ölçüldü; eski sürümde de).
  Oturum ilk saniyelerde sunucu hatasıyla düşerse hemen yedek modele geçilir.
  Cevap beklenirken NO_REPLY boyunca hiçbir şey gelmezse (cevap bekçisi) de
  yedeğe geçilir; bekleyen söz (selam, yazı, araç sonucu, kısa bir sesli
  komut) yeni oturuma gider. Duyulan söz uzunsa ya da arkada ses sürdüyse
  geçilmez: model ona söylenmemiş sözde (arkadaki video, telefon görüşmesi)
  bilerek susar (14 Ekim).

Dosya ve fotoğraflar (jarvis.attachments) kullanıcı turuna görsel ve metin
parçaları olarak eklenir. Kullanıcı yanına bir şey yazdıysa hemen cevap istenir.
Yazmadıysa tur açık bırakılır: soru sesle ya da yazıyla gelebilir, ikisinde de
model eki görür. Birkaç saniye soru gelmezse asistan eke kendisi bakar.
'''

from __future__ import annotations
import asyncio
import base64
import datetime as dt
import html
import json
import logging
import os
import re
import threading
import time
import traceback
import numpy as np
from google import genai
from google.genai import types
from .. import (about, language, memory, paths, permissions, personas, settings)
from .. import chains, story
from ..audio import devices, fx
from ..audio.barge import BargeGate
from ..camera import Webcam
from ..log import log
from ..personas import Persona
from ..tools import ToolContext, registry
from .base import Brain, Listener
LIVE_MODELS = ('models/gemini-3.8-live', 'models/gemini-2.5-flash-native-audio-latest')
_MODEL_GONE = re.compile('is not found|not supported for bidigeneratecontent|permission|billing', re.I)
_QUOTA = re.compile('quota|resource.?exhausted', re.I)
_MODEL_UNAVAILABLE = re.compile(f'{_MODEL_GONE.pattern}|{_QUOTA.pattern}', re.I)
_SERVER_TROUBLE = re.compile('\\b101[13]\\b|internal error|unavailable|overloaded|try again later', re.I)
SERVER_TRIES = 2
EARLY_FAIL = 20.0
NO_REPLY = 10.0
VOICE_STALL_WORDS = 12
VOICE_STALL_BUSY = 6.0
TOOL_DONE_NOTE = '(Sistem notu: bağlantı yenilendi. Kullanıcının son isteği: "{request}". Bunun için gereken işlem zaten yapıldı; aracı yeniden çağırma. Aracın sonucu: {results} Bu sonuca göre kullanıcıya cevap ver.)'
_BAD_KEY = re.compile('api key not valid|api_key_invalid|invalid api key|api key expired', re.I)
_STALE_HANDLE = re.compile('session not found|requested entity was not found', re.I)
RETRY_WAITS = (6.0, 15.0, 30.0, 60.0)
PRIMARY_RETRY = 600.0
QUOTA_RETRY = 240.0
QUOTA_AGAIN = 120.0
QUOTA_RETRY_MAX = 1800.0
_NETWORK = re.compile('\\b1006\\b|abnormal closure|getaddrinfo|nodename nor servname|name or service not known|network is unreachable|timed out|connection (refused|reset)|\\bssl\\b|certificate verify|rejected websocket|did not receive a valid http', re.I)
STREAM_END = 0.5
SPEAK_TAIL = 0.45
LEVEL_EVERY = 0.08
WEBCAM_EVERY = 1.0
TOOL_TIMEOUT = 30.0
PARALLEL_TOOLS = frozenset({'web_search'})
SAID_TOOLS = {'show_creator', 'open_chip_picker'}
SAID_TOOLS.add('offer_disable_others')
AUDIO_STALL = 3.0
SILENT_RETRIES = 2
SILENCE_WAIT = 0.4
SILENCE_HOLD = 1.5
VOICE_PEAK = 0.06
DSP_FIRST_WAIT = 2.5
SILENT_PEAK = 0.003
SILENT_AFTER = 15.0
MIC_RETRY = 15.0
LEVEL_SUMMARY = 30.0
SCENE_HOLD_MAX = 180.0
MIC_ZERO_CHUNKS = 160
FILE_WAIT = 4.0
REMOTE_TAIL = 0.6
HOLD_TURN_MAX = 45.0
HOLD_TOOL = 'Yapılmadı: ekranda bir hikâye sayfası açık, şu an komut alınmıyor. Hiçbir şey söyleme.'
RUINS_TOOL = 'Yapılmadı: artık hiçbir komut almıyorsun ve hiçbir aracın yok. Kendi sözlerinle, tek kısa cümleyle komut almadığını söyle.'
RUINS_RETRY = '(Sistem notu: kullanıcının son sözüne sesli bir yanıt vermedin: "{request}". Şimdi yanıtla, kısa ve kendi karakterinle.)'
STORY_TOOLS = frozenset({'secret_topic', 'final_choice'})
FILE_NOTE = '(Sistem notu: kullanıcı {what} ekledi ama henüz bir şey sormadı. Şimdi konuşma; sorusunu bekle.)'
FILE_LOOK = '(Sistem notu: kullanıcı eklediği {what} hakkında bir şey sormadı. Kendi karakterinle, bir iki cümleyle ne gördüğünü söyle; gerekiyorsa ne istediğini sor.)'
RETRY_NOTE = '(Sistem notu: kullanıcının son isteğine sesli bir yanıt vermedin. İstek: "{request}". Şimdi yanıtla; gerekiyorsa uygun aracı doğru parametrelerle çağır.)'
CONTROL_TOKEN_RE = re.compile('<ctrl\\d+>', re.IGNORECASE)
_CREATOR_RE = re.compile('\\s+'.join(map(re.escape, about.CREATOR.split())), re.IGNORECASE)
logging.getLogger('google_genai.types').setLevel(logging.ERROR)
TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
_FRIDAY_SPOKEN = re.compile('\\bFraydey(?=[a-zçğıöşü])', re.IGNORECASE)

def _written(text: 'str') -> 'str':
    '''Sese okunuşuyla verilen "Fraydeyi", sohbet yazısında "Friday'i" olarak görünsün.'''

    return _FRIDAY_SPOKEN.sub("Friday'", re.sub('\\bFraydey\\b', 'Friday', text))

def _clean(text: 'str') -> 'str':
    raw = CONTROL_TOKEN_RE.sub(' ', str(text or ''))
    raw = ''.join((ch for ch in raw if ch in '\n\r\t' or ord(ch) >= 32))
    return ' '.join(raw.split()).strip()

_SYSTEM_NOTE = re.compile('\\(\\s*s[iİıI]stem\\s+not\\w*(?:[^()]|\\([^()]*\\))*(?:\\)|$)', re.IGNORECASE)

def _unnoted(text: 'str') -> 'str':
    return ' '.join(_SYSTEM_NOTE.sub(' ', text).split())

_SILENCE = re.compile('<!--.*?(?:-->|$)|(?<![^\\s>}\\]])<[/!]?[a-z][^<>]{0,40}(?:>|$)|[{\\[(*]\\s*(?:no[\\s_-]*(?:speech|response|reply)|silen\\w*|pause|noise|quiet|sessiz\\w*|sus(?:ar|uyor|kun\\w*|ma)?\\b|konuşma yok)[^{}\\[\\]()*.!?…]{0,30}[}\\])*]', re.IGNORECASE | re.DOTALL)
_ZERO_WIDTH = re.compile('[​⁠﻿]')
_STAGE_ONLY = re.compile('\\s*[*(\\[{]\\s*[^*()\\[\\]{}<>.!?…]{1,40}[*)\\]}]\\s*')

def _wordy(text: 'str') -> 'bool':
    '''Yazıda harf ya da rakam var mı ("..." ya da yalnızca görünmez karakterler sessizliktir).'''

    return any((ch.isalnum() for ch in text))

def _unsilenced(text: 'str') -> 'str':
    '''Modelin sessizlik işaretleri çıkmış yazısı; harf ya da rakam kalmadıysa ya da tek bir sahne notuysa boş.'''

    text = ' '.join(_ZERO_WIDTH.sub('', _SILENCE.sub(' ', html.unescape(text))).split())
    if _wordy(text) and not _STAGE_ONLY.fullmatch(text):
        return text
    return ''

_CLOSERS = {'<': '>', '*': '*', '{': '}', '[': ']', '(': ')', '&': ';'}

def _silence_verdict(text: 'str', waited: 'float') -> 'bool':
    '''Tutulan ses şimdi çalınsın mı: yazıda söz başladıysa ya da yazı geç kaldıysa evet. Yazı şimdilik yalnızca
    sessizlik işaretiyse ("...", "<no speech detected>") tur sonuna dek tutulur.'''

    t = text.strip()
    if not t:
        return waited >= SILENCE_WAIT
    closer = _CLOSERS.get(t[0])
    if closer and closer not in t[1:]:
        return waited >= SILENCE_HOLD
    return bool(_unsilenced(t))

def _seconds(value, default: 'float') -> 'float':
    '''"50s" / "1.5s" → 50.0 / 1.5'''

    try:
        return float(str(value).strip().rstrip('s'))
    except (TypeError, ValueError):
        return default

ERROR_TEXT = {'SES AYGITI': 'Ses aygıtı açılamıyor; arada bir yeniden deneniyor.', 'KOTA DOLDU': 'Gemini kullanım kotası dolmuş görünüyor; arada bir yeniden deneniyor.', 'SUNUCU HATASI': 'Gemini sunucusu şu an hata veriyor (Google tarafında); arada bir yeniden deneniyor.', 'İNTERNET YOK': "Gemini'ye bağlanılamıyor. İnterneti kontrol et; arada bir yeniden deneniyor.", 'BAĞLANTI YOK': "Gemini'ye bağlanılamıyor; arada bir yeniden deneniyor."}

def _error_label(exc: 'Exception', message: 'str', local: 'bool') -> 'str':
    """Oturumun açılamama nedeni (ERROR_TEXT'in anahtarlarından). Kota iletisi de 1011 taşıyabiliyor: önce kota."""

    if local:
        return 'SES AYGITI'
    if _QUOTA.search(message):
        return 'KOTA DOLDU'
    if _SERVER_TROUBLE.search(message):
        return 'SUNUCU HATASI'
    if isinstance(exc, OSError) or _NETWORK.search(message):
        return 'İNTERNET YOK'
    return 'BAĞLANTI YOK'

class AudioRestart(Exception):
    '''Ses aygıtı değişti ya da koptu: oturum kaldığı yerden, yeni aygıtla sürer.'''

class MicToggle(Exception):
    """MİKROFON açıldı ya da kapandı: ses (mikrofon ve hoparlör) oturum sürerken yeniden kurulur. Kapalıyken mikrofon
    aygıtı hiç açılmaz; Mac'te ses yankı engelleyen yardımcı yerine düz hoparlörden çıkar, yardımcı kapanır ve macOS'un
    turuncu mikrofon göstergesi söner (eskiden mikrofon açık kalıp yalnızca ses gönderilmiyordu)."""

_opening: 'set[asyncio.Future]' = set()

async def _open_device(factory, *args):
    """Mikrofonu/hoparlörü iş parçacığında açar. Beklerken oturum biterse (iptal) açılan aygıt sonradan kapatılır;
    yoksa yetim kalır (Windows'ta yankı engelleme mikrofonu açık tutuyordu)."""

    opening = asyncio.ensure_future(asyncio.to_thread(factory, *args))
    _opening.add(opening)
    opening.add_done_callback(_opening.discard)
    try:
        return await asyncio.shield(opening)
    except asyncio.CancelledError:
        opening.add_done_callback(_close_late)
        raise

def _close_late(done: 'asyncio.Future') -> 'None':
    if not done.cancelled():
        if done.exception() is None:
            threading.Thread(target=done.result().close, daemon=True, name='aygit-kapat').start()

async def _settle_devices(timeout: 'float'=8.0) -> 'None':
    """Açılırken iptal edilmiş aygıtların açılışı bitsin ve kapansın: devices.reset (PortAudio'yu yeniden başlatır)
    açılmakta olan bir akışla çakışmasın, geç açılan eski DSP yeni mikrofonu kapatmasın."""

    pending = set(_opening)
    if not pending:
        return
    for fut in pending:
        fut.remove_done_callback(_close_late)
    await asyncio.wait(pending, timeout=timeout)
    for fut in pending:
        if not fut.done():
            fut.add_done_callback(_close_late)
        else:
            if fut.cancelled():
                continue
            if fut.exception() is not None:
                continue
            await asyncio.to_thread(fut.result().close)

def _now_block() -> 'str':
    now = dt.datetime.now()
    return f'[ŞU ANKİ ZAMAN]\n{TR_DAYS[now.weekday()]}, {now.day} {TR_MONTHS[now.month]} {now.year} — {now:%H:%M}'

class GeminiLiveBrain(Brain):
    provider = 'gemini'
    def __init__(self, listener: 'Listener', persona: 'Persona', audio_io: 'bool'=True) -> 'None':
        super().__init__(listener, persona)
        self.audio_io = audio_io
        self.audio_bytes = 0
        self.model = os.environ.get('JARVIS_LIVE_MODEL') or LIVE_MODELS[0]
        self.loop = None
        self.session = None
        self.webcam = Webcam()
        self.fx = fx.for_persona(persona.fx)
        self.mic_enabled = bool(settings.get('mic_enabled', True))
        self._proactive_turn = False
        self.voice_gain = max(0, min(150, int(settings.get('voice_volume', 100) or 0))) / 100
        self._speaking = False
        self._last_audio = 0.0
        self._restart = None
        self._stopping = False
        self._resume_handle = None
        self._greet_next = True
        self._thread = None
        self._voice_override = None
        self._speaker = None
        self._mic = None
        self._tool_tasks = set()
        self._running_calls = set()
        self._cancelled_calls = set()
        self._expect_reply = False
        self._last_request = ''
        self._typed = ('', -1)
        self.scene_active = False
        self.scene_mute = False
        self._mute_until = 0.0
        self._scene_mark = 0
        self._held_live = False
        self._held_at = 0.0
        self._held_model = False
        self._hold_pass = False
        self._pass_at = 0.0
        self._pass_used = False
        self._pass_next = False
        self._pass_key = False
        self._heard_cut = False
        self._scene_turn = False
        self._scene_out = False
        self._retries = 0
        self._mic_warned = False
        self._no_mic_said = False
        self._mic_said = set()
        self._mic_problem = ''
        self._mic_fails = 0
        self._plain_mic = False
        self._audio_dirty = ''
        self._audio_reset = False
        self._speaker_failed = False
        self._mic_toggled = False
        self._test_peaks = None
        self.mic_info = {}
        self._turn_open = False
        self._last_voice = 0.0
        self._voice_top = 0.0
        self._hushed = False
        self._go_away_task = None
        self._fallback_at = 0.0
        self._primary_retry = PRIMARY_RETRY
        self._primary_at = 0.0
        self._quota_strikes = 0
        self._owed_at = 0.0
        self._owed_kind = ''
        self._owed_items = []
        self._owed_voice = False
        self._voice_since = 0.0
        self._owe_after_turn = False
        self._model_talking = False
        self._heard_now = ''
        self._turn_done_at = 0.0
        self._loose_files = None
        self._gaps_seen = 0
        self._unplayed = b''
        self._carry_audio = False
        self.webcam.on_fail = self._webcam_failed
        self._user_turns = 0
        self._typing_at = 0.0
        self._file_task = None
        self._pending = []
        self.remote_sink = None
        self.remote_mic_on = False
        self._remote_q = None

    def start(self) -> 'None':
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name='brain')
        self._thread.start()

    def stop(self) -> 'None':
        self._stopping = True
        self._signal_restart()

    def send_text(self, text: 'str') -> 'None':
        text = (text or '').strip()
        if not text:
            return
        if not self.loop or not self.session:
            self._pending.append(text)
            return
        asyncio.run_coroutine_threadsafe(self._send_text(text), self.loop)

    def send_files(self, parts: 'list', text: 'str'='', what: 'str'='bu dosyayı') -> 'None':
        text = (text or '').strip()
        if not self.loop or not self.session:
            self._pending.append(('files', parts, text, what))
            return
        asyncio.run_coroutine_threadsafe(self._send_files(parts, text, what), self.loop)

    def note_typing(self) -> 'None':
        self._typing_at = time.monotonic()

    def say_scene(self, note: 'str') -> 'None':
        if self.loop:
            if self.session:
                asyncio.run_coroutine_threadsafe(self._say_scene(note), self.loop)

    def stage_note(self, note: 'str') -> 'None':
        '''Cevap istemeden bağlama not bırakır: kullanıcının sıradaki sözüne nasıl karşılık verileceği.'''

        if self.loop:
            if self.session:
                asyncio.run_coroutine_threadsafe(self._stage_note(note), self.loop)

    async def _stage_note(self, note: 'str') -> 'None':
        session = self.session
        if session is None:
            return
        try:
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': note}]}, turn_complete=False)
        except Exception as exc:
            log('sahne notu gönderilemedi:', exc)

    async def _say_scene(self, note: 'str') -> 'None':
        session = self.session
        if session is None:
            return
        self._expect_reply = True
        self._last_request = note
        self._proactive_turn = True
        self._grant_pass()
        self._scene_turn, self._scene_out = True, False
        try:
            self._owe('sahne', note)
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': note}]}, turn_complete=True)
        except Exception as exc:
            log('sahne sözü gönderilemedi:', exc)

    def speak_up(self, note: 'str', wait: 'float'=20.0) -> 'bool':
        if self.asleep or not self.mic_enabled or not self.loop or not self.session:
            return False
        if self.story_hold:
            return False
        if story.ruins():
            return False
        future = asyncio.run_coroutine_threadsafe(self._speak_up(note, wait), self.loop)
        try:
            return bool(future.result(wait + 5))
        except Exception:
            future.cancel()
            return False

    def set_sleep(self, asleep: 'bool') -> 'None':
        '''Uyku: oturum kapanır, mikrofon ve kamera susar; uyanınca kaldığı yerden sürer.'''

        asleep = bool(asleep)
        if asleep == self.asleep:
            return
        self.asleep = asleep
        if asleep and self.webcam.active:
            self.set_webcam(False)
        self._signal_restart()

    def mute_late(self, seconds: 'float') -> 'None':
        self._mute_until = time.monotonic() + seconds

    def _muted(self) -> 'bool':
        return self.scene_mute or time.monotonic() < self._mute_until or self._story_drop()

    def _mute_reason(self) -> 'str':
        '''Günlüğe: modelin sesi neden duyulmuyor (_muted).'''

        if self.scene_mute:
            return 'sahne sürüyor'
        if time.monotonic() < self._mute_until:
            return 'sahneden kalan geç cevap'
        return 'hikâye sayfası açık'

    def story_page(self, on: 'bool') -> 'None':
        '''Sayfa açıldı/kapandı (herhangi bir iş parçacığından). Açılınca mikrofon modele gitmez (_pump_mic), çalan söz
        kesilir, bekleyen istekler atılır; açıkken gelen cevap duyulmaz, araç çalışmaz. Kapanınca dinleme temiz başlar;
        açıkken başlamış turun geç gelen kalanı yine duyulmaz.'''

        on = bool(on)
        if on == self.story_hold:
            return
        self.story_hold = on
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self._story_page_changed, on)
                return
            except RuntimeError:
                pass

    def story_pass(self) -> 'None':
        '''Bu tur sayfa açılsa da duyulur: anahtarı açan söz (final_choice'un "kodu girin"i).'''

        if self.loop:
            self.loop.call_soon_threadsafe(self._grant_pass, True)

    def _story_page_changed(self, on: 'bool') -> 'None':
        if not on:
            self._hold_pass = self._pass_next = self._pass_key = False
            if not self._held_model:
                self._held_live = False
            self._heard_now, self._heard_cut = '', True
            if self._held_live:
                log('hikâye: sayfa kapandı, dinleme sürüyor' + ' (açıkken başlayan cevabın kalanı duyulmayacak)')
                return
            None(None + '')
            return
        self._pending.clear()
        self._loose_files = None
        if self._file_task:
            self._file_task.cancel()
            self._file_task = None
        if self._hold_pass:
            started = self._pass_key or self._pass_used
            if not started:
                self._cut_audio()
                self.fx.reset()
            if started:
                log('hikâye: sayfa açık, komut alınmıyor (' + 'izinli söz sürüyor)')
                return
            None(None + 'sahne sözü bekleniyor)')
            return
        heard = _clean(self._heard_now)
        if heard:
            self.listener.on_transcript('you', heard)
        self._heard_now, self._heard_cut = '', True
        self._expect_reply, self._retries = False, 0
        self._paid()
        if self._turn_open or self._tool_tasks:
            self._held_live, self._held_at = True, time.monotonic()
            self._held_model = self._model_talking or bool(self._tool_tasks)
        cut = self._speaking or self._turn_open
        self._cut_audio()
        self.fx.reset()
        if cut:
            log('hikâye: sayfa açık, komut alınmıyor' + ' (süren cevap kesildi)')
            return
        None(None + '')

    def _grant_pass(self, key: 'bool'=False) -> 'None':
        """Sıradaki söz sayfa açıkken de duyulur. key: anahtarı açan söz, süren turun kendisi (final_choice). Sahne
        sözü ise yeni bir tur: model o an konuşuyorsa (ya da tur tutuluyorsa) izin o tur kesilince ya da bitince başlar,
        eski turun kalanı izinle çalmaz. 🔑'te sahne sözü (key_open) sayfa açıldı bildiriminden önce de gelebilir:
        pywebview her çağrıyı ayrı iş parçacığında yürütür."""

        self._pass_key = key
        if self._held_live or not key and self._model_talking:
            self._pass_next = True
            return
        self._hold_pass, self._pass_at, self._pass_used = True, time.monotonic(), False

    def _story_drop(self) -> 'bool':
        '''Modelin bu çıktısı (ses, döküm, araç) atılsın mı. Sayfa açıkken gelen tur sonuna dek tutulur.'''

        now = time.monotonic()
        if self._hold_pass and now - self._pass_at > HOLD_TURN_MAX:
            self._hold_pass = False
        if self._held_live and now - self._held_at > HOLD_TURN_MAX:
            self._held_live = False
        if self._held_live:
            self._held_model = True
            return True
        if self._hold_pass:
            self._pass_used = True
            return False
        if self.story_hold:
            self._held_live, self._held_at, self._held_model = True, now, True
            log('hikâye: sayfa açıkken gelen cevap duyulmuyor')
            return True
        return False

    def _story_quiet(self) -> 'bool':
        '''Hoparlöre: kuyrukta kalan ses çalınmasın mı (yan etkisiz).'''

        return self._held_live or self.story_hold and not self._hold_pass

    def _end_held(self) -> 'None':
        '''Tutulan (ya da sahne sözünden önce süren) tur bitti ya da kesildi; bekleyen izin (sahne sözü) şimdi başlar.'''

        self._held_live = self._held_model = False
        if self._pass_next:
            self._pass_next = False
            self._hold_pass, self._pass_at, self._pass_used = True, time.monotonic(), False

    def set_persona(self, persona: 'Persona') -> 'None':
        if persona.key == self.persona.key:
            return
        self.persona = persona
        self.fx = fx.for_persona(persona.fx)
        self._voice_override = None
        self._resume_handle = None
        self._greet_next = True
        self._signal_restart()

    def hush(self) -> 'None':
        '''Modelin o anki sözünü sustur ve gelen sesi at (uykuya sözsüz geçiş). Yeni oturumda biter.'''

        self._hushed = True
        if self.loop:
            self.loop.call_soon_threadsafe(self._cut_audio)

    def _cut_audio(self) -> 'None':
        self._unplayed = b''
        if self._speaker is not None:
            self._speaker.clear()
        getattr(self.listener, 'on_audio_cut', (lambda: None))()

    def set_mic(self, enabled: 'bool') -> 'None':
        self.mic_enabled = bool(enabled)
        self._mic_toggled = True
        if enabled:
            self.listener.on_state('listening')
            return
        None('paused')

    def reopen_audio(self, reason: 'str') -> 'None':
        """Ayarlar › SES'te mikrofon ya da yankı engelleme değişti: ses oturum sürerken yeni ayarla yeniden kurulur.
        PortAudio'nun aygıt listesi de yenilenir (sonradan takılan mikrofon seçilmiş olabilir) ve yankı engellemenin
        hata sayacı sıfırlanır (kullanıcı onu yeniden açtıysa denensin)."""

        self._plain_mic = False
        self._audio_reset = True
        if paths.IS_WIN:
            from ..audio import win_aec
            win_aec.reset_failures()
        self._audio_dirty = reason or 'ses ayarı değişti'

    def mic_test(self, seconds: 'float'=3.0) -> 'dict | None':
        """MİKROFONU DENE: JARVIS'in açık mikrofonundan `seconds` boyunca tepe (asistan konuşurken de, süzgeçten önce).
        Mikrofon açık değilse None (çağıran aygıtı kendisi dener: devices.test_mic). Herhangi bir iş parçacığından."""

        if not self.mic_enabled or self._mic is None:
            return
        self._test_peaks = []
        time.sleep(seconds)
        peaks, self._test_peaks = self._test_peaks or [], None
        if not peaks:
            return
        return {'peak': max(peaks), 'chunks': len(peaks), **self.mic_info}

    def announce(self, note: 'str') -> 'None':
        '''Uygulamadaki bir olayı (zamanlayıcı bitti…) asistana sesle söylet.

        Asistan o sırada konuşuyorsa ya da kullanıcı konuşuyorsa sözü kesilmesin
        diye kısa bir sessizlik beklenir. Uykudayken söylenmez (alarm yine çalar).
        '''

        if self.asleep or not self.loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(self._announce(note), self.loop)

    def announce_wait(self, note: 'str', wait: 'float'=12.0) -> 'bool':
        """announce gibi, ama sonucu bekler: not oturuma gittiyse True. Uykudayken, bağlı değilken ya da sessizlik
        olmadan süre dolarsa False (Windows'taki yerel anımsatıcı o zaman açık kalır, sonra yeniden denenir)."""

        if self.asleep or not self.loop or not self.session:
            return False
        future = asyncio.run_coroutine_threadsafe(self._announce(note, wait), self.loop)
        try:
            return bool(future.result(wait + 5))
        except Exception:
            future.cancel()
            return False

    async def _speak_up(self, note: 'str', wait: 'float') -> 'bool':
        '''Kimse konuşmuyor, kullanıcı yazmıyor ve bir ek soru beklemiyorken söz al.'''

        end = time.monotonic() + wait
        quiet = None
        while time.monotonic() < end:
            now = time.monotonic()
            if self._idle() and self._file_task is None and now - self._typing_at > 5:
                quiet = quiet or now
                if now - quiet >= 1.5:
                    break
            quiet = None
            await asyncio.sleep(0.2)
        else:
            return False
        session = self.session
        if session is None:
            return False
        self._proactive_turn = True
        try:
            self._owe('kendiliğinden')
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': note}]}, turn_complete=True)
        except Exception as exc:
            self._proactive_turn = False
            log('kendiliğinden söz gönderilemedi:', exc)
            return False
        return True

    async def _announce(self, note: 'str', wait: 'float'=8.0) -> 'bool':
        end = time.monotonic() + wait
        while time.monotonic() < end and not self._idle():
            await asyncio.sleep(0.2)
        if self.story_hold:
            return False
        if story.ruins():
            return False
        session = self.session
        if session is None:
            return False
        self._expect_reply = True
        self._last_request = note
        self._proactive_turn = True
        try:
            self._owe('duyuru', note)
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': note}]}, turn_complete=True)
        except Exception as exc:
            log('duyuru gönderilemedi:', exc)
            return False
        return True

    def remote_mic(self, pcm: 'bytes') -> 'None':
        '''Telefonun mikrofonu (16 kHz, 16 bit): telefon sunucusunun iş parçacığından.'''

        loop, q = self.loop, self._remote_q
        if loop is None or q is None or not pcm:
            return
        def put() -> 'None':
            if q.full():
                q.get_nowait()
            q.put_nowait(pcm)

        loop.call_soon_threadsafe(put)

    def busy(self) -> 'bool':
        return self._speaking or self._turn_open or time.monotonic() - self._last_audio < SPEAK_TAIL

    def idle(self) -> 'bool':
        return self._idle()

    def set_voice_volume(self, percent: 'int') -> 'None':
        self.voice_gain = max(0, min(150, int(percent))) / 100

    def replay_awakening(self) -> 'None':
        '''İlk uyanışı yeniden oynat: temiz oturum, selam yerine uyanış sahnesi.'''

        self._resume_handle = None
        self._greet_next = True
        self._signal_restart()

    def restart_with(self, greeting: 'str') -> 'None':
        '''Temiz oturum, selam yerine uygulamanın notu: iyi sonda kalan çip zaten takılıysa [SON] talimata girsin.'''

        self._resume_handle = None
        self.next_greeting = greeting
        self._greet_next = True
        self._signal_restart()

    def drop_greeting(self) -> 'None':
        """Yeni oturumda selam ya da uygulamanın notu gitmesin (TEKRAR OYNA sessiz başlar). Gönderilmiş, süren söz
        ardından gelen reconnect'le kesilir; olağan yeniden bağlanmada selam yeniden kuyruğa girmez (_requeue_owed
        yalnızca model değişirken)."""

        self.next_greeting = ''
        self._greet_next = False

    def reconnect(self) -> 'None':
        self._resume_handle = None
        self._signal_restart()

    def set_language(self) -> 'None':
        '''Dil değişti: temiz oturum; asistan yeni dilde kısaca selam verir.'''

        self._resume_handle = None
        self._greet_next = True
        self._signal_restart()

    def renamed(self, persona: 'Persona', greeting: 'str'='') -> 'None':
        '''Çip adları değişti: talimattaki adlar yalnızca yeni oturumda değişir (telefondaki gibi). Takılı
        çipin adı değiştiyse yeni adıyla selam verir; başka bir çipin adı değiştiyse sessizce yeniden bağlanır.'''

        self.persona = persona
        self._resume_handle = None
        if greeting:
            self.next_greeting = greeting
            self._greet_next = True
        self._signal_restart()

    def set_webcam(self, on: 'bool') -> 'str':
        if on:
            if not self.webcam.start():
                return 'Kamera başlatılamadı: opencv-python yüklü değil.'
            self.listener.on_webcam(True)
            return 'Kamera açıldı. Artık görüntüyü görüyorum.'
        self.webcam.stop()
        self.listener.on_webcam(False)
        return 'Kamera kapatıldı.'

    def _signal_restart(self) -> 'None':
        if self.loop:
            if self._restart:
                try:
                    self.loop.call_soon_threadsafe(self._restart.set)
                except RuntimeError:
                    pass

    def _thread_main(self) -> 'None':
        try:
            asyncio.run(self._run_forever())
            return
        except Exception:
            traceback.print_exc()

    def _next_model(self, error: 'str', trouble: 'int'=0) -> 'bool':
        '''Model bu anahtarla kullanılamıyorsa ya da sunucusu üst üste hata veriyorsa listedeki sonrakine geç.'''

        if self.model not in LIVE_MODELS[:-1]:
            return False
        if not _MODEL_UNAVAILABLE.search(error):
            if trouble < SERVER_TRIES:
                return False
        old, self.model = self.model, LIVE_MODELS[LIVE_MODELS.index(self.model) + 1]
        self._resume_handle = None
        quota = bool(_QUOTA.search(error))
        gone = not quota and bool(_MODEL_GONE.search(error))
        self._fallback_at = 0.0 if gone else time.monotonic()
        self._primary_retry, why = PRIMARY_RETRY, ''
        if quota:
            again = self._primary_at and time.monotonic() - self._primary_at < QUOTA_AGAIN
            self._quota_strikes = self._quota_strikes + 1 if again else 1
            self._primary_retry = min(QUOTA_RETRY * 2 ** (self._quota_strikes - 1), QUOTA_RETRY_MAX)
            why = 'kota; ' if self._quota_strikes == 1 else f'kota, üst üste {self._quota_strikes}. kez; '
        back = 'geri dönülmeyecek' if gone else f'{self._primary_retry / 60:.0f} dk sonra {old.split('/')[-1]} yeniden denenecek'
        log(f'{old} kullanılamıyor ({error[:120]}) → {self.model} ({why}{back})')
        return True

    def _owe(self, kind: 'str', item=None) -> 'None':
        '''Modelden cevap bekleniyor (bkz. _watch_reply). item: ana model takılırsa yedek oturuma yeniden gidecek
        olan (_pending biçiminde); None ise yalnızca model değişir. Cevap gelene dek bekleyenler birikir: arka arkaya
        söylenenlerin ilki de kaybolmasın.'''

        outside = kind in ('yazı', 'ek', 'duyuru', 'sahne') and self._model_talking
        self._owe_after_turn = self._owe_after_turn and bool(self._owed_at) or outside
        self._owed_at, self._owed_kind = time.monotonic(), kind
        if kind == 'ses':
            if not self._owed_voice:
                self._voice_since = self._owed_at
            self._owed_voice = True
            return
        if item is not None:
            if all((item != it for _k, it in self._owed_items)):
                self._owed_items.append((kind, item))

    def _paid(self) -> 'None':
        self._owed_at, self._owed_kind, self._owed_items, self._owed_voice = 0.0, '', [], False
        self._owe_after_turn = False

    def _replied(self, talking: 'bool'=True) -> 'None':
        '''Modelden ses, yazı ya da (talking=False) araç çağrısı geldi: beklenen cevap geliyor.'''

        self._model_talking = self._model_talking or talking
        self._scene_out = self._scene_out or self._scene_turn and not self._pass_next
        if not self._owe_after_turn:
            self._paid()

    def _turn_ended(self) -> 'None':
        '''Modelin turu bitti ya da kesildi. Bekleme o turun ortasında başladıysa asıl cevap bundan sonra gelir.
        Sessiz biten tur cevap sayılmaz: araç turu sonucu ayrı turda söyleniyor, sessiz kullanıcı turunu
        _after_turn yeniden dener. Kendiliğinden söz ise susabilir.'''

        self._model_talking = False
        if self._owe_after_turn:
            self._owe_after_turn = False
            self._restamp()
            return
        if self._owed_kind == 'kendiliğinden':
            if not self._owed_items:
                self._paid()

    def _restamp(self) -> 'None':
        '''Büyük bir gönderim (görselli ek, araç yanıtı) bitti: bekleme süresi yüklemeden değil şimdiden başlasın.'''

        if self._owed_at:
            self._owed_at = time.monotonic()

    def _requeue_owed(self) -> 'str':
        """Cevap beklenirken oturum bitti (model takıldı ya da hatayla düştü): bekleyenler yeni oturuma gitsin, sırayla
        _pending'in başına. Selam yeniden istenir. Sorusu sonradan gelen ek, soruyla birlikte yeniden gider (yeni
        oturumda eski ek yok). Ne beklendiğini döndürür."""

        kind, owed, voice = self._owed_kind, list(self._owed_items), self._owed_voice
        heard = _clean(self._heard_now)
        if heard:
            self.listener.on_transcript('you', heard)
        if voice and heard:
            owed.append(('ses', heard))
        self._paid()
        loose, self._loose_files = self._loose_files, None
        items = []
        for k, item in owed:
            if k == 'selam':
                self._greet_next = True
                if not item:
                    continue
                self.next_greeting = str(item)
            elif loose and k in ('yazı', 'ses'):
                items.append(('files', loose[1], item, loose[3]))
                loose = None
            else:
                if k == 'ek notu':
                    loose = None
                items.append(item)
        self._pending[:0] = items
        return kind

    async def _watch_reply(self) -> 'None':
        '''Cevap bekçisi: cevap beklenirken (selam, yazı, araç sonucu) ana modelden NO_REPLY boyunca hiçbir şey
        gelmezse (ses, araç çağrısı, yazı ya da tur sonu) model takılmıştır: yedek modele geçilir, bekleyen söz yeni
        oturuma gider. Sunucu bazı günler cevabı 20-60 sn geciktiriyor; kullanıcı "sesimi almıyor" sanıyordu. Araç
        çalışırken ve sahne sürerken beklenmez; kullanıcı konuşmayı sürdürdükçe süre baştan. Yalnızca duyulan söz
        bekleniyorsa ve o söz modele söylenmemiş görünüyorsa (_overheard) susmak modelin kararıdır: günlüğe "model
        sustu", borç kapanır.'''

        await asyncio.sleep(0.5)
        if self._owed_at:
            pass
        if self.model not in LIVE_MODELS[:-1]:
            pass
        if self.scene_active:
            self._paid()
        mic_live = self.mic_enabled and not self.scene_hold
        mic_live = mic_live or self.remote_mic_on
        mic_live = mic_live and not self.story_hold
        if not self._owed_items and not mic_live:
            self._paid()
        if not self._tool_tasks:
            pass
        if self._speaking:
            pass
        if time.monotonic() - max(self._owed_at, self._last_voice) < NO_REPLY:
            pass
        why = self._overheard() if self._owed_voice and not self._owed_items and self._loose_files is None else ''
        if why:
            log(f'model sustu: {self.model.split('/')[-1]} duyulan söze {NO_REPLY:.0f} sn yanıt vermedi ({why}; yedeğe geçilmedi)')
            self._paid()
        kind = self._requeue_owed()
        log(f'cevap bekçisi: {self.model.split('/')[-1]} {NO_REPLY:.0f} sn yanıt vermedi ({kind})')
        self._next_model(f'yanıt vermedi: {kind}', SERVER_TRIES)
        if kind != 'kendiliğinden':
            self.listener.on_transcript('sys', 'Gemini yanıt vermedi; yedek modelle devam.')

    def _overheard(self) -> 'str':
        '''Cevapsız kalan duyulan söz modele söylenmemiş görünüyor mu; öyleyse nedeni (günlüğe), değilse "". Uzun söz
        (telefon görüşmesi, video) ya da dökümünden sonra mikrofonun ses duymayı sürdürmesi (arkada ses vardı). 3.8
        bilerek sustuğu turda da kısa bir ses ve tur sonu gönderiyor (14 Ekim, ölçüldü); bekçiye düşen, hiçbir şey
        gelmeyen tur. Kısa bir komutta bu sunucunun takılmasıdır (6 Ekim).'''

        words = len(_clean(self._heard_now).split())
        if words > VOICE_STALL_WORDS:
            return f'uzun söz, {words} sözcük'
        if self._last_voice - self._voice_since > VOICE_STALL_BUSY:
            return 'arkada ses sürdü'
        return ''

    def _primary_due(self) -> 'bool':
        '''Yedek modeldeyken ana modele dönme zamanı geldi mi. Konuşmanın bağlamı (sürdürme anahtarı) modele özgü:
        yalnızca yeni oturumda ya da uzun bir sessizlikte.'''

        if not self._fallback_at or self.model == LIVE_MODELS[0]:
            return False
        now = time.monotonic()
        if now - self._fallback_at < self._primary_retry:
            return False
        return not (self._resume_handle and now - getattr(self, 'last_exchange', 0.0) < 90)

    def _maybe_primary(self) -> 'None':
        '''Yedek modeldeyken (2.5 daha yavaş ve daha kötü anlıyor) ana modeli yeniden dene.'''

        if not self._primary_due():
            return
        log(f'{self.model.split('/')[-1]} → {LIVE_MODELS[0].split('/')[-1]} yeniden deneniyor')
        self.model, self._resume_handle, self._fallback_at = LIVE_MODELS[0], None, 0.0
        self._primary_at = time.monotonic()

    async def _watch_primary(self) -> 'None':
        """Yedek modeldeyken dönüş zamanı gelince sessiz bir anda yeniden bağlan (_maybe_primary ana modeli seçer).
        Eskiden dönüş ancak bir sonraki yeniden bağlanmada oluyordu (sunucu ~10 dk'da bir oturumu yeniler); kotadan
        sonra dönüş birkaç dakikada olsun."""

        await asyncio.sleep(5.0)
        quiet = time.monotonic() - getattr(self, 'last_exchange', 0.0) >= 90
        if self._primary_due() and quiet and self._idle() and not self._owed_at and not self.scene_active:
            log(f'ana modele dönmek için oturum yenileniyor ({self.model.split('/')[-1]})')
            self._signal_restart()

    def _log_latency(self, heard_at: 'float'=0.0) -> 'None':
        '''Günlüğe, turun ilk çalınan sesinde. Sesli turda "söz bitti → ilk ses": mikrofondaki son sesten (VOICE_PEAK'i
        aşan; arkada ses sürüyorsa süre kısa görünür) ilk sese, yanında sunucunun sözü yazıya döktüğü an (döküm: sözün
        kapandığı an; 3.8 dökümü tek parça gönderiyor). Yazıda, notta "cevap gecikmesi": gönderildiğinden beri.'''

        now, model = time.monotonic(), self.model.split('/')[-1]
        typed = getattr(self, 'last_user_at', 0.0) or 0.0
        if self._last_voice > max(self._turn_done_at, typed):
            wait = now - self._last_voice
            if 0 < wait < 60:
                heard = f' (döküm +{heard_at - self._last_voice:.1f})' if heard_at > self._last_voice else ''
                log(f'söz bitti → ilk ses +{wait:.1f} sn{heard} · {model}')
            return
        wait = now - max(self._last_voice, typed)
        if 0 < wait < 15:
            log(f'cevap gecikmesi {wait:.1f} sn · {model}')

    def _config(self) -> 'types.LiveConnectConfig':
        mem = memory.format_memory_for_prompt(memory.load_memory())
        state = ''
        available = {t.name for t in registry.available()}
        ultron = self.persona.key == 'ultron'
        offline = ultron and story.ultron_offline()
        state = '\n'.join((b for b in (chains.prompt_block(online=not offline) if ultron else '', chains.offline_block() if offline else '', story.prompt_block(self.persona.key))
             if b))
        if offline:
            available.discard('web_search')
        instruction = personas.system_instruction(self.persona, mem, _now_block(), state, available=available)
        if ultron and story.ruins():
            instruction, available = story.ruins_instruction(self.persona), set()
        rule = language.instruction()
        if rule:
            instruction = f'{rule}\n\n{instruction}'
        voice = self._voice_override or self.persona.voice
        declared = [types.FunctionDeclaration(**d) for d in registry.to_gemini() if d['name'] in available]
        return types.LiveConnectConfig(response_modalities=['AUDIO'], input_audio_transcription=language.transcription(), output_audio_transcription={}, system_instruction=instruction, tools=[types.Tool(function_declarations=declared)] if declared else None, speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)), language_code=None if 'native-audio' in self.model else language.speech_code()), context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()), session_resumption=types.SessionResumptionConfig(handle=self._resume_handle))

    async def _run_forever(self) -> 'None':
        self.loop = asyncio.get_running_loop()
        self._restart = asyncio.Event()
        self._remote_q = asyncio.Queue(maxsize=48)
        failures = 0
        trouble = 0
        said = ''
        while not self._stopping:
            if self.asleep:
                self.listener.on_state('asleep')
                self._restart.clear()
                await self._restart.wait()
                continue
            key = settings.get_secret('gemini')
            if not key:
                self.listener.on_state('idle', 'API anahtarı bekleniyor')
                self._restart.clear()
                await self._restart.wait()
                continue
            self._restart.clear()
            self._maybe_primary()
            self.listener.on_state('connecting')
            began = time.monotonic()
            try:
                client = genai.Client(api_key=key, http_options={'api_version': 'v1alpha'})
                async with client.aio.live.connect(model=self.model, config=self._config()) as session:
                    self.session = session
                    failures, said = 0, ''
                    await self._run_session(session)
            except AudioRestart as exc:
                log('ses yeniden açılıyor:', exc)
                text = str(exc)
                self.listener.on_transcript('sys', f'{text[:1].upper()}{text[1:]}; ses yeniden açılıyor.')
                self.session = None
                await _settle_devices()
                devices.reset()
            except Exception as exc:
                self.session = None
                if self._stopping:
                    pass
                continue
            self.session = None
            self._set_speaking(False)

    async def _run_session(self, session) -> 'None':
        audio_out = asyncio.Queue()
        self.listener.on_state('listening' if self.mic_enabled else 'paused')
        self._expect_reply, self._retries = False, 0
        self._hushed = False
        self._held_live = self._held_model = self._pass_next = False
        self._heard_cut = False
        self._paid()
        self._heard_now, self._loose_files, self._model_talking = '', None, False
        self._plain_mic = False
        if self._pending:
            self._greet_next = False
            pending, self._pending = self._pending, []
            for item in pending:
                if isinstance(item, tuple):
                    await self._send_files(*item[1:])
                else:
                    await self._send_text(item)
        if self._greet_next:
            self._greet_next = False
            app_note = self.next_greeting
            note = self._greeting_note()
            if note:
                self._expect_reply = True
                self._proactive_turn = True
                self._owe('selam', app_note or '')
                await session.send_client_content(turns={'role': 'user', 'parts': [{'text': note}]}, turn_complete=True)
        tasks = [asyncio.create_task(self._pump_audio(session, audio_out)), asyncio.create_task(self._pump_remote(session)), asyncio.create_task(self._pump_receive(session, audio_out)), asyncio.create_task(self._pump_webcam(session)), asyncio.create_task(self._watch_reply()), asyncio.create_task(self._watch_primary())]
        restart = asyncio.create_task(self._restart.wait())
        done, _pending = await asyncio.wait([restart, *tasks], return_when=asyncio.FIRST_COMPLETED)
        if self._go_away_task:
            tasks.append(self._go_away_task)
            self._go_away_task = None
        if self._file_task:
            tasks.append(self._file_task)
            self._file_task = None
        self._turn_open = False
        for task in [restart, *tasks, *self._tool_tasks]:
            task.cancel()
        await asyncio.gather(restart, *tasks, return_exceptions=True)
        for task in done:
            if task is restart:
                continue
            if task.cancelled():
                continue
            if not task.exception():
                continue
            raise task.exception()

    async def _pump_audio(self, session, audio_out: 'asyncio.Queue') -> 'None':
        """Mikrofon, hoparlör ve aygıt bekçisi. Ses aygıtı değişince ya da koparsa (AudioRestart) yalnızca ses yeniden
        açılır, Gemini oturumu sürer: yeniden bağlanmak 10-25 sn sürebiliyordu (kulaklık takınca). Mac'te yankı
        engelleyen yardımcı yeni aygıtla yeniden başlar; çalınmamış ses yalnızca Windows'ta taşınır. Bir dakikada
        üçten fazla olursa oturum eskisi gibi baştan kurulur (run › AudioRestart)."""

        restarts = []
        parts = [asyncio.create_task(self._pump_mic(session)), asyncio.create_task(self._pump_speaker(audio_out)), asyncio.create_task(self._watch_audio())]
        try:
            try:
                pass
            finally:
                done, _pending = await asyncio.wait(parts, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in parts:
                task.cancel()
            await asyncio.gather(*parts, return_exceptions=True)
            exc = next((t.exception() for t in done if not t.cancelled() if t.exception()), None)
            if isinstance(exc, MicToggle):
                log(f'ses: {exc}, yeniden kuruluyor (oturum sürüyor)')
                self._carry_audio = True
                if self._audio_reset:
                    self._audio_reset = False
                    await _settle_devices()
                    await asyncio.to_thread(devices.reset)
            now = time.monotonic()
            restarts = [t for t in restarts if now - t < 60.0] + [now]
            if not (isinstance(exc, AudioRestart) and len(restarts) <= 3):
                if exc is not None:
                    raise exc

    def _greeting_note(self) -> 'str':
        '''Olağan selam; model bu bilgisayarda ilk kez takılıyorsa onun uyanış sahnesi.'''

        persona = self.persona
        if self.next_greeting:
            note, self.next_greeting = self.next_greeting, ''
            return note
        if story.ruins():
            return ''
        if persona.awakens and not settings.get(f'{persona.key}_awakened'):
            self._scene_mark = self._user_turns
            getattr(self.listener, 'on_awakening', (lambda _s: None))('start')
            return ''
        return f'(Sistem notu: kullanıcı seni şimdi açtı. Kendi karakterinle, tek ve kısa bir cümleyle selam ver. Örnek ton: "{persona.greeting}")'

    async def _send_text(self, text: 'str') -> 'None':
        self._user_turns += 1
        self._typed = text, self._user_turns
        self.last_user_at = self.last_exchange = time.monotonic()
        self.last_user_text = text
        self._expect_reply = True
        self._last_request = text
        try:
            self._owe('yazı', text)
            await self.session.send_client_content(turns={'role': 'user', 'parts': [{'text': text}]}, turn_complete=True)
        except Exception as exc:
            self.listener.on_transcript('error', f'Gönderilemedi: {exc}')

    async def _send_files(self, parts: 'list', text: 'str', what: 'str') -> 'None':
        session = self.session
        if session is None:
            self._pending.append(('files', parts, text, what))
            return
        self._user_turns += 1
        self._typed = text, self._user_turns
        self.last_user_at = self.last_exchange = time.monotonic()
        content = [{'inline_data': {'mime_type': 'image/jpeg', 'data': value}} if kind == 'image' else {'text': value} for kind, value in parts]
        if text:
            content.append({'text': text})
            self._expect_reply = True
            self._last_request = text
        else:
            for _ in range(40):
                if not self._speaking and not self._turn_open:
                    break
                await asyncio.sleep(0.2)
            content.append({'text': FILE_NOTE.format(what=what)})
        if text:
            self._owe('ek', ('files', parts, text, what))
        self._loose_files = None if text else ('files', parts, '', what)
        try:
            await session.send_client_content(turns={'role': 'user', 'parts': content}, turn_complete=bool(text))
        except Exception as exc:
            log('dosya gönderilemedi:', exc)
            self.listener.on_transcript('error', f'Dosya gönderilemedi: {exc}')
        self._restamp()
        log(f'ek gönderildi: {what} ({sum((k == 'image' for k, _ in parts))} görsel)' + (' + soru' if text else ' — soru bekleniyor'))
        if not text:
            if self._file_task:
                self._file_task.cancel()
            self._file_task = asyncio.create_task(self._look_if_quiet(session, self._user_turns, what))

    async def _look_if_quiet(self, session, mark: 'int', what: 'str') -> 'None':
        '''Ek geldi ama soru gelmedi. Kullanıcı yazmıyor ve konuşmuyorsa asistan eke kendisi bakar.'''

        start = quiet = time.monotonic()
        await asyncio.sleep(0.25)
        if self._user_turns != mark or self.session is not session:
            return
        now = time.monotonic()
        heard = now - self._last_voice < 1.2 and now - start < 15
        if self._turn_open or self._speaking or self._tool_tasks or self._expect_reply or heard or now - self._typing_at < FILE_WAIT:
            quiet = now
        elif now - quiet >= FILE_WAIT:
            pass
        self._file_task = None
        log('ek: soru gelmedi, asistan kendisi bakıyor')
        self._user_turns += 1
        self._expect_reply = True
        self._last_request = f'Gönderdiğim {what.removeprefix('bu ')} yorumla.'
        try:
            self._owe('ek notu', self._loose_files)
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': FILE_LOOK.format(what=what)}]}, turn_complete=True)
        except Exception as exc:
            log('ek notu gönderilemedi:', exc)

    def _set_speaking(self, value: 'bool') -> 'None':
        if value == self._speaking:
            return
        self._speaking = value
        if value:
            self.listener.on_state('speaking')
            return
        if self._tools_busy():
            self.listener.on_state('thinking')
            return
        self.listener.on_state('listening' if self.mic_enabled else 'paused')

    def _tools_busy(self) -> 'bool':
        '''Sonucu hâlâ beklenen bir araç çalışıyor mu (sunucunun iptal ettiği, arkada biten araç sayılmaz).'''

        return bool(self._running_calls - self._cancelled_calls)

    async def _pump_mic(self, session) -> 'None':
        if not self.audio_io:
            await asyncio.Event().wait()
        if not self.mic_enabled:
            await self._mic_off()
        chunks = asyncio.Queue(maxsize=24)
        mic = await self._open_mic(chunks)
        self._mic = mic
        gate = BargeGate() if getattr(mic, 'echo_cancelled', False) else None
        last_level = 0.0
        zero_run = 0
        listened, heard_any = 0.0, False
        summary = []
        hold_since = perm_at = 0.0
        sent = 0.0
        denied = False
        try:
            if paths.IS_WIN or not self._mic_warned:
                if await asyncio.to_thread(permissions.media_status, 'audio') == 'denied':
                    denied = paths.IS_WIN
                    self._warn_mic()
            pcm = await chunks.get()
            if not self.mic_enabled:
                raise MicToggle('mikrofon kapandı')
            if self._audio_dirty:
                reason, self._audio_dirty = self._audio_dirty, ''
                raise MicToggle(reason)
            if denied and time.monotonic() - perm_at > 3.0:
                perm_at = time.monotonic()
                if await asyncio.to_thread(permissions.media_status, 'audio') != 'denied':
                    self._mic_warned = False
                    raise MicToggle('mikrofon izni verildi')
            raw = devices.peak(pcm)
            if self._test_peaks is not None:
                self._test_peaks.append(raw)
            if zero_run is not None:
                zero_run = zero_run + 1 if not pcm.strip(b'\x00') else None
                if zero_run is not None and zero_run >= MIC_ZERO_CHUNKS:
                    zero_run = None
                    if not self._mic_warned:
                        if permissions.media_status('audio') == 'denied':
                            self._warn_mic()
                        else:
                            self._warn_silent(mic, zeros=True)
            now = time.monotonic()
            if self.scene_hold:
                pass
            hold_since = now if self._speaking else hold_since or now
            if hold_since and now - hold_since > SCENE_HOLD_MAX:
                log(f"sahne mikrofonu {SCENE_HOLD_MAX:.0f} sn'den uzun tuttu: bırakılıyor")
                self.scene_hold, hold_since = False, 0.0
            held = self.scene_hold
            held = held or self.story_hold
            if not self._speaking and not now - self._last_audio < SPEAK_TAIL and not held:
                listened += len(pcm) / 2 / devices.MIC_RATE
                heard_any = heard_any or raw >= SILENT_PEAK
                if paths.IS_WIN and not heard_any and listened >= SILENT_AFTER:
                    heard_any = True
                    self._warn_silent(mic, zeros=False)
                if summary is not None:
                    summary.append(raw)
                    if listened >= LEVEL_SUMMARY:
                        self._log_mic_summary(mic, summary)
                        summary = None
            speaking = self._speaking or now - self._last_audio < SPEAK_TAIL
            barge = gate is not None and self.remote_sink is None and getattr(self._speaker, 'echo_cancelled', False)
            if (not speaking or barge) and self.mic_enabled and not held:
                if now < self.mic_hold_until or self.remote_mic_on:
                    if gate is not None:
                        self._end_barge(gate)
                    if sent:
                        sent = await self._end_stream(session, sent)
                    if now - last_level > LEVEL_EVERY:
                        last_level = now
                        self.listener.on_level(0.0)
            level = raw
            out = [pcm]
            if speaking:
                was_open = gate.is_open
                echo_floor = getattr(self._speaker, 'echo_floor', None)
                out = gate.feed(pcm, level, now, self._speaker.warm(), echo_floor() if echo_floor else 0.0)
                if gate.is_open and not was_open:
                    log(f'söz kesme: kullanıcı araya girdi (tepe {level:.2f}, iz {gate.env:.3f}, ortam {gate.ambient:.3f})')
                    self._speaker.duck(True)
                elif was_open and not gate.is_open:
                    self._speaker.duck(False)
                if not gate.is_open:
                    level = 0.0
            elif gate is not None:
                self._end_barge(gate)
                gate.listen(level)
            if level > VOICE_PEAK:
                self._last_voice = now
                self._voice_top = max(self._voice_top, level)
            if now - last_level > LEVEL_EVERY:
                last_level = now
                self.listener.on_level(level)
            if self._test_peaks is not None:
                out = []
            if not out:
                if sent:
                    sent = await self._end_stream(session, sent)
            for part in out:
                await session.send_realtime_input(audio=types.Blob(data=part, mime_type=f'audio/pcm;rate={devices.MIC_RATE}'))
            sent = time.monotonic()
        except MicToggle:
            if sent:
                await self._end_stream(session, sent)
            raise

    async def _mic_off(self) -> 'None':
        """MİKROFON kapalı: aygıt hiç açılmaz; açılınca MicToggle. JARVIS açılıştan beri mikrofon kapalıysa (4.5.2'den
        kalan ayar, ya da ilk açılışta izin yokken YAZILI DEVAM ET) bir kez söylenir: kullanıcı duyulmadığını sanmasın.
        İlk açılışta izin yüzünden kapandıysa (mic_off_reason) izin gelince uygulama mikrofonu kendisi açar."""

        log('mikrofon kapalı: aygıt açılmıyor (MİKROFON ya da F4 ile açılır)')
        getattr(self.listener, 'on_mic_status', (lambda *_a: None))('off', '')
        if not self._mic_toggled:
            if 'kapali' not in self._mic_said:
                self._mic_said.add('kapali')
                self.listener.on_transcript('sys', "Mikrofon kapalı: seni duymam için MİKROFON düğmesine ya da F4'e bas.")
        ticks = 0
        while not self.mic_enabled:
            await asyncio.sleep(0.25)
            ticks += 1
            if ticks % 12 == 0 and settings.get('mic_off_reason') == 'permission':
                if await asyncio.to_thread(permissions.media_status, 'audio') == 'granted':
                    getattr(self.listener, 'on_mic_permission', (lambda: None))()
        raise MicToggle('mikrofon açıldı')

    async def _open_mic(self, chunks: 'asyncio.Queue'):
        """Mikrofonu açar; açılamazsa nedenini söyler, açılabilene dek bekleyip yeniden dener (_without_mic).
        Windows'ta yankı engelleme açılıp DSP_FIRST_WAIT içinde hiç ses vermezse (hoparlör akışı yok, DSP hata verdi)
        kapatılır ve mikrofon düz yoldan açılır; eskiden bekçi sesi her ~4 sn'de bir baştan kuruyordu (sonsuz döngü)."""

        loop = asyncio.get_running_loop()
        try:
            mic = await _open_device(devices.Microphone, loop, chunks, self._plain_mic)
        except Exception as exc:
            await self._without_mic(exc)
        if paths.IS_WIN and getattr(mic, 'path', '') == 'yankı engellemeli':
            try:
                first = await asyncio.wait_for(chunks.get(), DSP_FIRST_WAIT)
            except asyncio.CancelledError:
                threading.Thread(target=mic.close, daemon=True, name='aygit-kapat').start()
                raise
            except asyncio.TimeoutError:
                await asyncio.to_thread(mic.close)
                from ..audio import win_aec
                win_aec.note_failure(f"açıldı, {DSP_FIRST_WAIT:.1f} sn'de hiç ses vermedi")
                self._plain_mic = True
                if 'aec' not in self._mic_said:
                    self._mic_said.add('aec')
                    self.listener.on_transcript('sys', 'Yankı engelleme bu bilgisayarda çalışmadı; mikrofon onsuz açıldı (JARVIS konuşurken seni duymaz, sözünü kesemezsin).')
            chunks.put_nowait(first)
        self._mic_opened(mic)
        if not paths.IS_WIN and not getattr(mic, 'echo_cancelled', False):
            if devices.voice_error and 'aec' not in self._mic_said:
                self._mic_said.add('aec')
                log('yankı engelleme yok, mikrofon düz yoldan açıldı (sohbete bir kez söylendi)')
                self.listener.on_transcript('sys', 'Yankı engelleme açılamadı; JARVIS konuşurken seni duyamaz, sözünü kesemezsin.')
        return mic

    def _mic_opened(self, mic) -> 'None':
        self.mic_info = {'path': getattr(mic, 'path', ''), 'device': getattr(mic, 'device_name', '')}
        log(f'mikrofon açık: {self.mic_info['path'] or '?'} · “{self.mic_info['device'] or 'varsayılan'}”')
        if self._mic_problem:
            log(f'mikrofon yeniden açıldı (önceki sorun: {self._mic_problem})')
            self.listener.on_transcript('sys', 'Mikrofon açıldı; seni duyuyorum.')
        self._mic_problem, self._mic_fails = '', 0
        getattr(self.listener, 'on_mic_status', (lambda *_a: None))('ok', '')

    def _log_mic_summary(self, mic, peaks: 'list[float]') -> 'None':
        arr = np.array(peaks)
        log(f'mikrofon seviye özeti ({len(peaks)} parça, {getattr(mic, 'path', '?')} · “{getattr(mic, 'device_name', '') or 'varsayılan'}”): ortanca {np.median(arr):.4f}, %90 {np.percentile(arr, 90):.4f}, en yüksek {arr.max():.4f}')

    def _end_barge(self, gate: 'BargeGate') -> 'None':
        '''Asistan sustu (ya da mikrofon kapandı): söz kesme süzgeci ve kısılan ses baştan.'''

        if gate.active or gate.is_open:
            if gate.is_open and self._speaker is not None:
                self._speaker.duck(False)
            gate.end()

    async def _end_stream(self, session, sent: 'float') -> 'float':
        """Mikrofon sesi modele gitmeyi bıraktı (asistan konuşmaya başladı, söz kesme kapısı kapandı, mikrofon kapandı).
        Son ses STREAM_END içinde gittiyse sunucuya akışın bittiği bir kez söylenir: elindeki yarım sesi bekletmeden
        işler, sonraki sözle birleştirmez (Gemini'nin önerisi; telefon uygulaması da gönderiyor). Yeni ses gelince akış
        kendiliğinden yeniden açılır. 0 döner: bir sonraki gönderime dek yeniden söylenmez."""

        if time.monotonic() - sent < STREAM_END:
            try:
                await session.send_realtime_input(audio_stream_end=True)
            except Exception as exc:
                log('ses akışı sonu gönderilemedi:', exc)
            return 0.0
        return 0.0

    async def _pump_remote(self, session) -> 'None':
        """Telefonun mikrofonu → model. Asistan konuşurken gitmez (Mac'teki gibi; telefon da susturur)."""

        q = self._remote_q
        if q is None:
            await asyncio.Event().wait()
        while not q.empty():
            q.get_nowait()
        last_level = sent = 0.0
        pcm = await q.get()
        now = time.monotonic()
        if self.remote_mic_on and not self._speaking and not now - self._last_audio < SPEAK_TAIL + REMOTE_TAIL and not self.scene_hold:
            if self.story_hold or self.asleep:
                if sent:
                    sent = await self._end_stream(session, sent)
        level = devices.peak(pcm)
        if level > VOICE_PEAK:
            self._last_voice = now
        if now - last_level > LEVEL_EVERY:
            last_level = now
            self.listener.on_level(level)
        await session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=f'audio/pcm;rate={devices.MIC_RATE}'))
        sent = time.monotonic()

    async def _without_mic(self, exc: 'Exception') -> 'None':
        '''Mikrofon açılamadı. Oturum yine de sürer: kullanıcı yazarak konuşur. Sistemin giriş aygıtı değişince
        (mikrofon takıldı) ses yeniden açılır.

        Windows (9 Ekim takipçi raporu: üç aygıtla da "mikrofonu algılamadı", metin hep "bulunamadı" diyordu): hatanın
        türü (engellendi, başka uygulamada, yok, açılamadı) ayrılır ve doğru metin bir kez söylenir, rozet ekranda kalır.
        Her hata günlüğe. İzin anahtarı açılınca hemen, yoksa MIC_RETRY aralıkla yeniden denenir (yeniden başlatmadan).
        Döndüğünde çağıran (_open_mic) yeniden dener.'''

        before = await asyncio.to_thread(devices.default_devices)
        if not paths.IS_WIN:
            if not self._no_mic_said:
                self._no_mic_said = True
                log('mikrofon açılamadı:', exc)
                self.listener.on_transcript('sys', permissions.fallback('no_mic', 'Mikrofon bulunamadı; yazarak konuşabilirsin. Mikrofon takılınca kendiliğinden açılır.'))
            await asyncio.sleep(3.0)
            if not self.mic_enabled:
                raise MicToggle('mikrofon kapandı')
            now = await asyncio.to_thread(devices.default_devices)
            if now and before and now != before and now[0] != -1:
                raise AudioRestart('mikrofon bulundu')
        from ..audio import win_aec
        errors = [e for e in (win_aec.last_error, f'{type(exc).__name__}: {exc}') if e]
        kind, badge, text = await asyncio.to_thread(permissions.mic_problem, errors)
        self._mic_fails += 1
        if kind != self._mic_problem or self._mic_fails % 20 == 1:
            log(f'mikrofon açılamadı ({kind}, {self._mic_fails}. deneme):', ' | '.join(errors)[:400])
        if kind != self._mic_problem:
            self._mic_problem = kind
            getattr(self.listener, 'on_mic_status', (lambda *_a: None))(kind, badge)
            if kind == 'blocked':
                if await asyncio.to_thread(permissions.media_status, 'audio') == 'denied':
                    permissions.open_pane('microphone')
            self.listener.on_transcript('error', text)
        denied = await asyncio.to_thread(permissions.media_status, 'audio') == 'denied'
        start = time.monotonic()
        await asyncio.sleep(3.0)
        if not self.mic_enabled:
            raise MicToggle('mikrofon kapandı')
        if self._audio_dirty:
            reason, self._audio_dirty = self._audio_dirty, ''
            raise MicToggle(reason)
        now = await asyncio.to_thread(devices.default_devices)
        if now and before and now != before and now[0] != -1:
            raise AudioRestart('mikrofon bulundu')
        if denied:
            if await asyncio.to_thread(permissions.media_status, 'audio') != 'denied':
                log('mikrofon izni verildi: yeniden deneniyor')
                return
        if time.monotonic() - start >= MIC_RETRY:
            pass

    def _warn_mic(self) -> 'None':
        '''Mikrofon açıldı ama izin kapalı (sıfır gelecek): izin sayfası ve açıklama, bir kez.'''

        if self._mic_warned:
            return
        self._mic_warned = True
        if permissions.media_status('audio') == 'denied':
            permissions.open_pane('microphone')
            self.listener.on_transcript('error', permissions.explain('microphone'))
            self._mic_problem = 'blocked'
            getattr(self.listener, 'on_mic_status', (lambda *_a: None))('blocked', 'MİKROFON ERİŞİLEMİYOR')
            return
        self._warn_silent(self._mic, zeros=True)

    def _warn_silent(self, mic, zeros: 'bool') -> 'None':
        '''Mikrofon açık ama aygıttan ses gelmiyor (tam sıfır ya da SILENT_AFTER boyunca SILENT_PEAK altı). Aygıtın adı
        söylenir: yanlış aygıt seçili olabilir. Her aygıt için bir kez (aygıt değişince yeniden uyarılabilir).'''

        name = getattr(mic, 'device_name', '') if mic is not None else ''
        key = f'sessiz:{getattr(mic, 'device_id', '') or name}'
        if key in self._mic_said:
            return
        self._mic_said.add(key)
        log(f'mikrofondan ses gelmiyor ({'tam sıfır' if zeros else 'çok kısık'}): “{name or '?'}”')
        if not paths.IS_WIN:
            self.listener.on_transcript('error', permissions.fallback('microphone', 'Mikrofondan hiç ses gelmiyor. Mikrofon sessize alınmış ya da seçili giriş aygıtı yanlış olabilir (Sistem Ayarları › Ses › Giriş).'))
            return
        where = f'“{name}” aygıtını' if name else "Windows'un varsayılan giriş aygıtını"
        self.listener.on_transcript('error', f'JARVIS şu an {where} dinliyor ve oradan ses gelmiyor' + (' (sessize alınmış ya da erişimi engellenmiş olabilir).' if zeros else '.') + " Doğru mikrofon bu değilse Ayarlar › SES › MİKROFON'dan seç; buysa Windows'ta Ayarlar › Sistem › Ses › Giriş'te sesinin açık olduğuna bak.")

    def _webcam_failed(self) -> 'None':
        self.listener.on_webcam(False)
        if permissions.media_status('video') == 'denied':
            permissions.open_pane('camera')
            self.listener.on_transcript('error', permissions.explain('camera'))
            return
        self.listener.on_transcript('error', permissions.fallback('camera', 'Kamera açılamadı. macOS izin sorduysa onayla ve kamerayı yeniden aç; başka bir uygulama kamerayı kullanıyor da olabilir.'))

    async def _watch_audio(self) -> 'None':
        '''Ses aygıtı koparsa ya da sistemin varsayılan aygıtı değişirse yeniden aç.'''

        if not self.audio_io:
            await asyncio.Event().wait()
        opened = devices.pa_defaults() or await asyncio.to_thread(devices.default_devices)
        ticks = 0
        await asyncio.sleep(1.0)
        ticks += 1
        now = time.monotonic()
        for name, dev in ('mikrofon', self._mic), ('hoparlör', self._speaker):
            last = getattr(dev, 'last_callback', None)
            if last is None:
                continue
            if not now - last > AUDIO_STALL:
                continue
            if paths.IS_WIN and dev is self._mic and getattr(dev, 'path', '') == 'yankı engellemeli':
                await self._dsp_stalled(dev, now - last)
            raise AudioRestart(f'{name} yanıt vermiyor')
        chosen = devices.selected_mic() if paths.IS_WIN else ''
        using_chosen = bool(chosen) and getattr(self._mic, 'device_id', '') == chosen
        if chosen:
            if not using_chosen and self._mic is not None:
                if ticks % 5 == 0:
                    from ..audio import win_aec
                    if any((d['id'] == chosen for d in await asyncio.to_thread(win_aec.endpoints))):
                        raise AudioRestart('seçili mikrofon takıldı')
        if self.audio_io and self._speaker is None and self._speaker_failed and ticks % 30 == 0:
            self._audio_reset = True
            raise MicToggle('hoparlör yeniden deneniyor')
        current = await asyncio.to_thread(devices.default_devices)
        if self._speaker_failed and opened and current and opened[1] == -1 and current[1] != -1:
            raise AudioRestart('hoparlör bulundu')
        if opened is not None and current is not None:
            if -1 in current or -1 in opened:
                opened = opened if opened and -1 not in opened else current
        mine = (lambda d: d[1:]) if using_chosen else (lambda d: d)
        if mine(current) != mine(opened):
            await asyncio.sleep(1.5)
            again = await asyncio.to_thread(devices.default_devices)
            if again is not None:
                if mine(again) == mine(opened):
                    log('varsayılan ses aygıtı bir an değişip geri döndü; ses yeniden açılmadı')
            raise AudioRestart('ses aygıtı değişti')

    async def _dsp_stalled(self, mic, gap: 'float') -> 'None':
        """Yankı engellemeli mikrofon çalışırken sustu. DSP'nin hatası sayılır (ikinciden sonra o çalışmada düz yol);
        ama uyku/uyanma (çok uzun boşluk), çıkarılan mikrofon ya da susan hoparlör DSP'nin suçu değil."""

        from ..audio import win_aec
        speaker_ok = now_ok = True
        last_spk = getattr(self._speaker, 'last_callback', None)
        if last_spk is not None:
            speaker_ok = time.monotonic() - last_spk < AUDIO_STALL
        if gap > AUDIO_STALL + 5.0:
            now_ok = False
        present = any((d['id'] == getattr(mic, 'device_id', '') for d in await asyncio.to_thread(win_aec.endpoints)))
        if speaker_ok and now_ok and present:
            win_aec.note_failure('çalışırken sustu')
            return
        log(f'yankı engelleme sustu ({gap:.1f} sn; aygıt {'var' if present else 'çıkarılmış'}, hoparlör {'sağlam' if speaker_ok else 'sustu'}): DSP hatası sayılmadı')

    async def _pump_speaker(self, audio_out: 'asyncio.Queue') -> 'None':
        '''Modelin sesi: bu Mac'in hoparlörüne ya da (sesi açıksa) telefona.

        Hoparlör yoksa (test: JARVIS_SILENT) ya da ses telefona gidiyorsa "konuşuyor" durumu
        gelen sesin süresine göre tutulur; sahneler, beklemeler ve mikrofonun ne zaman
        açılacağı gerçek kullanımdaki gibi zamanlansın.
        '''

        speaker = None
        if self.audio_io:
            try:
                speaker = await _open_device(devices.Speaker, self.mic_enabled)
                if self._speaker_failed:
                    self._speaker_failed = False
                    log('hoparlör yeniden açıldı')
                    self.listener.on_transcript('sys', 'Hoparlör açıldı; sesim yeniden duyulacak.')
            except Exception as exc:
                if not self._speaker_failed:
                    log('hoparlör açılamadı:', exc)
                self._speaker_failed = True
                if 'hoparlor' not in self._mic_said:
                    self._mic_said.add('hoparlor')
                    self.listener.on_transcript('error', 'Hoparlör açılamadı; asistanın sesi duyulmayacak, cevaplar sohbette yazılı görünür. ' + ("Windows'ta Ayarlar › Sistem › Ses › Çıkış'ta etkin bir hoparlör seçili olmalı. " if paths.IS_WIN else '') + f'({str(exc)[:120]})')
        self._speaker = speaker
        self._gaps_seen = 0
        carry, self._unplayed = self._unplayed if self._carry_audio else b'', b''
        self._carry_audio = False
        if carry and speaker is not None:
            speaker.write(carry)
        until = 0.0
        try:
            try:
                chunk = await asyncio.wait_for(audio_out.get(), timeout=0.05)
                if chunk is None:
                    end = getattr(speaker, 'end_of_speech', None)
                    if end is not None:
                        end()
            except asyncio.TimeoutError:
                pass
        finally:
            self._speaker = None
            if speaker is not None:
                unplayed = getattr(speaker, 'unplayed', None)
                self._unplayed = unplayed() if unplayed is not None else b''
                speaker.close()
        try:
            if self._story_quiet():
                pass
            pcm = self.fx.process(chunk)
            sink = self.remote_sink
            if sink is not None or speaker is None:
                if sink is not None:
                    sink(pcm)
                else:
                    self.audio_bytes += len(pcm)
                now = time.monotonic()
                until = max(until, now) + len(pcm) / (devices.SPEAKER_RATE * 2)
            else:
                speaker.write(self._louder(pcm))
            now = time.monotonic()
            tail = SPEAK_TAIL + (REMOTE_TAIL if self.remote_sink is not None else 0.0)
            if speaker is None or not speaker.pending():
                if now < until:
                    self._last_audio = now
                    self._set_speaking(True)
                elif self._speaking and now - self._last_audio > tail:
                    self._set_speaking(False)
        except asyncio.TimeoutError:
            pass
        finally:
            self._speaker = None
            if speaker is not None:
                unplayed = getattr(speaker, 'unplayed', None)
                self._unplayed = unplayed() if unplayed is not None else b''
                speaker.close()

    def _louder(self, pcm: 'bytes') -> 'bytes':
        """Ayarlar › Ses › Asistanın sesi (0–150 %). %100'ün üstünde tepeler kırpılmaz, yumuşakça sınırlanır;
        altında taşma olmaz, ses düz kısılır (sınırlayıcı tepeleri boşuna bükmesin)."""

        if abs(self.voice_gain - 1.0) < 0.01 or not pcm:
            return pcm
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if self.voice_gain < 1.0:
            return (samples * self.voice_gain).astype(np.int16).tobytes()
        samples *= self.voice_gain / 32768.0
        fx.soft_limit(samples)
        return (samples * 32767.0).astype(np.int16).tobytes()

    async def _pump_webcam(self, session) -> 'None':
        last = None
        await asyncio.sleep(WEBCAM_EVERY if self.webcam.active else 0.3)
        if not self.webcam.active:
            pass
        frame = self.webcam.latest()
        if frame is not None:
            pass
        if frame is last:
            pass
        last = frame
        await session.send_realtime_input(video=types.Blob(data=frame, mime_type='image/jpeg'))

    async def _pump_receive(self, session, audio_out: 'asyncio.Queue') -> 'None':
        heard = []
        said = []
        turn_audio = turn_interrupted = turn_tool = creator_named = False
        last_tool = False
        story_turn = False
        held = None
        held_at = heard_at = 0.0
        played = False
        dropped = False
        def play(chunk: 'bytes') -> 'None':
            nonlocal played, dropped
            if not played:
                played = True
                self._log_latency(heard_at)
            if not self._muted():
                audio_out.put_nowait(chunk)
                return
            if not dropped:
                dropped = True
                log(f'model sesi atıldı ({self._mute_reason()})')

        def release() -> 'None':
            nonlocal held
            for chunk in held or ():
                play(chunk)
            held = None

        def recheck(mark: 'list') -> 'None':
            if held is mark:
                if self.session is session:
                    if _silence_verdict(''.join(said), time.monotonic() - held_at):
                        release()

        async for response in session.receive():
            if self._heard_cut:
                heard, self._heard_cut = [], False
            if response.data or response.tool_call:
                self._replied(bool(response.data))
            if response.data:
                if not self._hushed:
                    if not turn_audio:
                        if self._may_stay_silent(last_tool or turn_tool):
                            held, held_at = [], time.monotonic()
                            for wait in SILENCE_WAIT, SILENCE_HOLD:
                                asyncio.get_running_loop().call_later(wait + 0.01, recheck, held)
                    turn_audio = True
                    self._turn_open = True
                    if held is not None:
                        held.append(response.data)
                        if _silence_verdict(''.join(said), time.monotonic() - held_at):
                            release()
                    else:
                        play(response.data)
            update = getattr(response, 'session_resumption_update', None)
            if update and getattr(update, 'resumable', False) and update.new_handle:
                self._resume_handle = update.new_handle
            cancelled = getattr(response, 'tool_call_cancellation', None)
            if cancelled and cancelled.ids:
                self._cancelled_calls.update(cancelled.ids)
                if self._running_calls & set(cancelled.ids) and not self._speaking and not self._tools_busy():
                    self.listener.on_state('listening' if self.mic_enabled else 'paused')
            sc = response.server_content
            if sc:
                if sc.interrupted:
                    turn_interrupted = True
                    held = None
                    while not audio_out.empty():
                        audio_out.get_nowait()
                    self._unplayed = b''
                    if self._speaker is not None:
                        self._speaker.clear()
                    self.fx.reset()
                    getattr(self.listener, 'on_audio_cut', (lambda: None))()
                    if self._held_live and said:
                        said[-1] = said[-1].rstrip() + '…'
                    if self._held_live or self._pass_next:
                        self._end_held()
                heard_now = sc.input_transcription.text if sc.input_transcription else ''
                if heard_now and self.story_hold and not self._hold_pass:
                    heard_now = ''
                if heard_now:
                    heard.append(heard_now)
                    self._heard_now = ''.join(heard)
                    heard_at = heard_at or time.monotonic()
                    if not turn_audio and not turn_tool and self._last_voice > self._turn_done_at and not self.scene_active:
                        self._owe('ses')
                    self._turn_open = True
                    self._user_turns += 1
                    if not self.scene_active:
                        self._mute_until = 0.0
                if sc.output_transcription and sc.output_transcription.text:
                    self._replied()
                if sc.interrupted or sc.turn_complete:
                    self._turn_ended()
                if sc.output_transcription and sc.output_transcription.text and not self._muted():
                    said.append(sc.output_transcription.text)
                    self._turn_open = True
                    if not creator_named and _CREATOR_RE.search(''.join(said)) and about.asked(self._said_now(heard)):
                        creator_named = True
                        getattr(self.listener, 'on_creator', (lambda: None))()
                if held is not None:
                    text = ''.join(said)
                    if sc.turn_complete and text.strip() and not _unsilenced(text):
                        log(f'model sustu: sessizlik sesi çalınmadı ({sum(map(len, held)) / 2 / devices.SPEAKER_RATE:.1f} sn)')
                        held, turn_audio = None, False
                    elif sc.turn_complete or _silence_verdict(text, time.monotonic() - held_at):
                        release()
                if sc.turn_complete:
                    audio_out.put_nowait(None)
                    self._turn_open = False
                    self._turn_done_at = time.monotonic()
                    you, ai = _clean(''.join(heard)), _written(_clean(''.join(said)))
                    glitch = bool(CONTROL_TOKEN_RE.search(''.join(said)))
                    heard, said = [], []
                    if ai and _SYSTEM_NOTE.search(ai):
                        ai = _unnoted(ai)
                        log('modelin sözündeki sistem notu süzüldü')
                    if ai and '&' in ai:
                        ai = html.unescape(ai)
                    if ai and (_SILENCE.search(ai) or _ZERO_WIDTH.search(ai) or not _unsilenced(ai)):
                        ai = _unsilenced(ai)
                        log('model sustu (sessizlik işareti süzüldü)' if not ai else 'modelin sözündeki sessizlik işareti süzüldü')
                    self._heard_now = ''
                    if time.monotonic() < self._mute_until and not self.scene_active:
                        self._mute_until = 0.0
                    scene_turn = self._scene_turn and self._scene_out
                    if scene_turn:
                        self._scene_turn = self._scene_out = turn_tool and not turn_audio
                    if not self._held_live:
                        if self.story_hold and not self._hold_pass:
                            pass
                    self._end_held()
                    if you:
                        self.listener.on_transcript('you', you)
                    if ai:
                        self.listener.on_transcript('ai', ai if ai.endswith('…') else ai + '…')
                    log('hikâye: sayfa açıkken gelen tur duyulmadı')
                    you = ai = ''
                    self._expect_reply, turn_audio = (turn_tool := False), False
                    self._retries = 0
                    if self._pass_next:
                        self._end_held()
                    elif self._hold_pass and self._pass_used and not turn_tool:
                        self._hold_pass = False
                    if ai and not story_turn and not scene_turn and self.persona.key == 'ultron' and story.ultron_offline() and story.says_offline(ai):
                        getattr(self.listener, 'on_net_refused', (lambda: None))()
                    story_turn = story_turn and turn_tool and not turn_audio
                    if you:
                        self.listener.on_transcript('you', you)
                        if self._voice_top:
                            log(f'kullanıcı sesi tepe {self._voice_top:.2f}')
                            self._voice_top = 0.0
                    if ai:
                        self.tool_reply = turn_tool or last_tool
                        self.listener.on_transcript('ai', ai)
                    self._note_exchange(you, ai)
                    if you:
                        self._last_request = you
                    await self._after_turn(session, bool(you), turn_audio or turn_tool, turn_interrupted, glitch)
                    gaps = self._speaker.gaps if self._speaker is not None else self._gaps_seen
                    line = devices.turn_report(self._speaker, gaps - self._gaps_seen) if turn_audio else None
                    if line:
                        log(line)
                    elif gaps != self._gaps_seen:
                        log(f'hoparlör tamponu {gaps - self._gaps_seen} kez boşaldı (ses geç geldi)')
                    self._gaps_seen = gaps
                    last_tool = turn_tool
                    turn_audio = turn_interrupted = turn_tool = creator_named = played = False
                    heard_at = 0.0
                    dropped = False
            if response.tool_call:
                turn_tool = True
                if held is not None:
                    release()
                self._story_drop()
                story_turn = story_turn or any((c.name in STORY_TOOLS for c in response.tool_call.function_calls))
                audio_out.put_nowait(None)
                request = _clean(''.join(heard)) or self._last_request
                task = asyncio.create_task(self._answer_tools(session, response.tool_call.function_calls, request, {'said': self._tool_said(heard), 'ask': self._ask_mark()}))
                self._tool_tasks.add(task)
                task.add_done_callback(self._tool_tasks.discard)
            go_away = getattr(response, 'go_away', None)
            if not go_away:
                continue
            if self._go_away_task is not None:
                continue
            left = _seconds(go_away.time_left, 10.0)
            log(f'sunucu oturumu yenileyecek ({left:.0f} sn)')
            self._go_away_task = asyncio.create_task(self._reconnect_when_idle(left))

    def _may_stay_silent(self, after_tool: 'bool') -> 'bool':
        '''Bu tur yalnızca duyulan söze cevap mı (yazı, ek notu, selam, duyuru, sahne sözü ya da araç sonucu değil;
        sorusu beklenen bir ekin sorusu da değil): model söz ona söylenmediyse susmayı seçebilir; sesi yazısı gelene
        dek tutulur (_pump_receive, SILENCE_WAIT).'''

        return not (after_tool or self._expect_reply or self._proactive_turn or self.scene_active or self._loose_files is not None)

    def _said_now(self, heard: 'list[str]') -> 'str':
        '''Kullanıcının bu turdaki sözü: duyulan, yoksa (yazdıysa) yazılan. Yazılandan sonra ses duyulduysa o eskidir.'''

        text, turn = self._typed
        if _clean(''.join(heard)):
            if turn == self._user_turns:
                return text
        return ''

    def _tool_said(self, heard: 'list[str]') -> 'str':
        '''SAID_TOOLS'a giden söz: bu turda duyulan ya da yazılan. Araç, bir önceki aracın sonucundan sonra ayrı turda
        gelirse son istek; ama kullanıcı o turdan beri konuştuysa değil: yeni sözün dökümü geç gelince önceki söz
        ("Alp'e yaz") onun yerine geçmesin, boş kalsın (telefonda da yalnızca bu turun sözü).'''

        if self._said_now(heard):
            if self._last_voice <= self._turn_done_at:
                return self._last_request
        return ''

    def _ask_mark(self) -> 'str':
        '''Kullanıcının son isteğinin izi: yeni bir yazı ya da mikrofonda yeni ses değiştirir. Dökümden bağımsız (o
        geç gelip büyüyebilir); aynı istekten gelen iki araç çağrısını tanımak için (app._chip_picker_story).'''

        return f'{self._typed[1]}:{self._last_voice:.3f}'

    def _note_exchange(self, you: 'str', ai: 'str') -> 'None':
        '''Kendiliğinden konuşma için: kim, ne zaman, ne dedi.'''

        now = time.monotonic()
        if you:
            self.last_user_at = self.last_exchange = now
            self.last_user_text = you
        if ai:
            self.last_exchange = now
            self.last_ai_text = ai
            self.last_ai_proactive = self._proactive_turn and not you
            if self.last_ai_proactive:
                self.proactive_said[self.persona.key] = ai
        if you or ai:
            self._proactive_turn = False

    def _idle(self) -> 'bool':
        if self.story_hold:
            return False
        now = time.monotonic()
        return not self._turn_open and not self._speaking and not self._tool_tasks and not self._expect_reply and now - self._last_audio > SPEAK_TAIL and now - self._last_voice > 1.0

    async def _reconnect_when_idle(self, left: 'float') -> 'None':
        deadline = time.monotonic() + max(1.0, left - 5.0)
        quiet_since = None
        while time.monotonic() < deadline:
            if self._idle():
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= 0.8:
                    break
            quiet_since = None
            await asyncio.sleep(0.2)
        log('oturum yenileniyor (sunucu isteği)')
        self._signal_restart()

    async def _after_turn(self, session, user_spoke: 'bool', answered: 'bool', interrupted: 'bool', glitch: 'bool'=False) -> 'None':
        '''Cevap beklenen bir tur (yazı, ek, not, selam) sessiz bittiyse modeli bir kez daha dene. Yalnızca sesle
        gelen söz yanıtsız kaldıysa denenmez: model bilerek susmuş olabilir (glitch: bozuk simgeyle sustuysa
        denenir).'''

        if self.scene_active:
            replied = self._user_turns > self._scene_mark
            self._scene_mark = self._user_turns
            self._retries = 0
            self._expect_reply = False
            getattr(self.listener, 'on_scene_turn', (lambda _r: None))(replied)
            return
        if answered:
            self._retries = 0
            self._expect_reply = False
            self._loose_files = None
            return
        if interrupted:
            if not answered:
                log('tur kesildi, cevabın sesi gelmeden')
            self._expect_reply = False
            return
        if not user_spoke and not self._expect_reply:
            return
        if not self._expect_reply and not glitch and self._loose_files is None:
            log('model sustu: duyulan söze yanıt yok (yeniden denenmedi)')
            self._retries = 0
            if self._owed_voice and not self._owed_items:
                self._paid()
            return
        if self._retries < SILENT_RETRIES:
            self._retries += 1
            self._expect_reply = True
            request = self._last_request or 'son söylediğin'
            text = RETRY_NOTE.format(request=request) if self._retries == 1 else request
            if self._retries == 1 and story.ruins():
                text = RUINS_RETRY.format(request=request)
            log(f'sessiz tur → yeniden deneme {self._retries}')
            self._owe('yeniden deneme', request if self._last_request else None)
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': text}]}, turn_complete=True)
            return
        log('sessiz tur → tekrar denemede de yanıt yok')
        self._retries = 0
        self._expect_reply = False
        self.listener.on_sfx('error')
        self.listener.on_transcript('error', 'Buna yanıt üretemedim. Bir kez daha söyler misin?')

    async def _answer_tools(self, session, calls, request: 'str'='', extra: 'dict | None'=None) -> 'None':
        if self.story_hold or self._held_live:
            log('hikâye: sayfa açıkken araç çağrısı yapılmadı:', ', '.join((c.name for c in calls)))
            try:
                pass
            except Exception as exc:
                log('araç yanıtı gönderilemedi:', exc)
            try:
                await session.send_tool_response(function_responses=[types.FunctionResponse(id=c.id, name=c.name, response={'result': HOLD_TOOL}) for c in calls])
            except Exception as exc:
                log('araç yanıtı gönderilemedi:', exc)
            return
        if story.ruins():
            log('harabe: araç çağrısı yapılmadı:', ', '.join((c.name for c in calls)))
            try:
                pass
            except Exception as exc:
                log('araç yanıtı gönderilemedi:', exc)
            try:
                await session.send_tool_response(function_responses=[types.FunctionResponse(id=c.id, name=c.name, response={'result': RUINS_TOOL}) for c in calls])
            except Exception as exc:
                log('araç yanıtı gönderilemedi:', exc)
            return
        extra = dict(extra or {'said': request})
        extra['kill'] = any((call.name == 'offer_disable_others' for call in calls))
        async def in_order(group) -> 'list':
            done = []
            for call in group:
                if call.id not in self._cancelled_calls:
                    done.append(await self._run_tool(call, extra))
            return done

        alone = [call for call in calls if call.name in PARALLEL_TOOLS]
        groups = await asyncio.gather(in_order([call for call in calls if call.name not in PARALLEL_TOOLS]), *(in_order([call]) for call in alone))
        replies = [(r, images) for group in groups for r, images in group if r.id not in self._cancelled_calls]
        if not replies:
            return
        results = ' '.join((str((r.response or {}).get('result', '')).strip() for r, _i in replies))[:2000]
        self._owe('araç', TOOL_DONE_NOTE.format(request=request or 'son söylediği', results=results))
        try:
            if any((images for _r, images in replies)):
                await self._send_tool_images(session, replies)
            else:
                await session.send_tool_response(function_responses=[r for r, _images in replies])
        except Exception as exc:
            log('araç yanıtı gönderilemedi:', exc)
        self._restamp()

    async def _send_tool_images(self, session, replies) -> 'None':
        """Görselli araç yanıtı (read_file: fotoğraf, taranmış PDF).

        Gemini Live araç yanıtında görseli kabul ediyor (3.8'de denendi: model resmi
        doğru anlattı), ama SDK'nın send_tool_response'u görselin baytlarını JSON'a
        çeviremiyor. Bu yüzden ileti burada elle, base64 ile yazılıyor. Olmazsa
        yanıt görselsiz gider; model yalnızca metni görür.
        """

        payload = [{'id': r.id, 'name': r.name, 'response': r.response, 'parts': [{'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(jpeg).decode()}} for jpeg in images]} for r, images in replies]
        try:
            await session._ws.send(json.dumps({'tool_response': {'functionResponses': payload}}))
            log(f'araç yanıtı {sum((len(i) for _r, i in replies))} görselle gönderildi')
        except AttributeError:
            r
            _images = session
            await None(function_responses=None)

    async def _run_tool(self, call, extra: 'dict | None'=None) -> 'tuple[types.FunctionResponse, list[bytes]]':
        name, args = call.name, dict(call.args or {})
        if name in SAID_TOOLS and extra:
            args.update(extra)
        self.listener.on_state('thinking', name)
        ctx = ToolContext(focus_panel=self.listener.on_panel, set_webcam=self.set_webcam, show_map=getattr(self.listener, 'on_map', (lambda _s: None)), app_action=getattr(self.listener, 'on_app_action', (lambda _n, _a: 'Yapılamıyor.')), show_files=getattr(self.listener, 'on_files', (lambda _p, _m: None)))
        running = call.id or f'{name}:{id(call)}'
        self._running_calls.add(running)
        try:
            result, ok = await asyncio.wait_for(asyncio.to_thread(registry.call, name, args, ctx), TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            log('araç zaman aşımı:', name)
            result, ok = f"{name} {int(TOOL_TIMEOUT)} saniyede bitmedi ve yarıda bırakıldı; sonucu sana gelmeyecek. Kullanıcıya bunu kısaca söyle, 'sonra bildireceğim' deme; isterse yeniden denesin.", False
        self._running_calls.discard(running)
        tool = registry.tools.get(name)
        if tool and tool.quiet:
            log('gizli araç', name, result[:80])
        else:
            self.listener.on_tool(name, ok, result[:160])
            if not ok:
                self.listener.on_sfx('error')
            elif tool and tool.success_sfx:
                self.listener.on_sfx('done')
        if not self._tools_busy():
            self.listener.on_state('speaking' if self._speaking else 'listening' if self.mic_enabled else 'paused')
        return types.FunctionResponse(id=call.id, name=name, response={'result': result}), list(ctx.images)


# WARNING: Decompyle incomplete

'''Mikrofon ve hoparlör.

macOS'ta ikisi birlikte küçük bir Swift yardımcısında (jarvis_voice_helper) çalışır: Apple'ın yankı
engellemesi (Voice Processing I/O, FaceTime'ın kullandığı birim) asistanın kendi sesini mikrofondan siler.
Böylece kullanıcı asistan konuşurken de duyulur ve sözünü kesebilir. Yardımcı açılamazsa (derlenemedi,
aygıt desteklemiyor) sounddevice'a (PortAudio) dönülür; o zaman yankı engelleme yoktur ve asistan
konuşurken mikrofon susturulur (`echo_cancelled` False); bu, sohbete bir kez söylenir (`voice_error`). Windows'ta
yankıyı Windows'un yerleşik Voice Capture DSP'si siler (win_aec.py); hoparlör yine sounddevice.

sounddevice, PortAudio'yu kendi içinde getirir: macOS'ta Homebrew, Windows'ta
ayrı bir kurulum gerekmez. V3'teki PyAudio + `brew install portaudio`
zincirinin yerini alır.

İkisi de geri çağırma (callback) tabanlıdır: ses kartı veriyi kendisi ister.
Bloklayan read/write yoktur, bu yüzden oturum yenilenirken akışı kapatmak her
an güvenlidir ve "şu an ses çalıyor mu" sorusunun cevabı tamponun gerçek
doluluğudur, tahmin değil.

Biçimler Gemini Live'ın beklediği gibidir:
  mikrofon → 16 kHz, mono, 16 bit
  hoparlör ← 24 kHz, mono, 16 bit
'''

from __future__ import annotations
import asyncio
import ctypes
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
import numpy as np
import sounddevice as sd
from .. import paths, settings
from ..log import log
MIC_RATE = 16000
SPEAKER_RATE = 24000
CHUNK = 1024
PREBUFFER = 0.2
PREBUFFER_WAIT = 0.3
GAP = 1.0

def Microphone(loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue', plain: 'bool'=False):
    '''Her parça bir asyncio kuyruğuna düşer. Yavaş olabilir (yardımcı açılır): iş parçacığında çağır.
    plain=True: yankı engelleme olmadan (Windows: DSP bu bilgisayarda ses vermediyse).'''

    voice = None if plain else voice_io()
    if voice is not None:
        return _VoiceMic(voice, loop, queue)
    if paths.IS_WIN:
        mic_id = selected_mic()
        if not plain:
            if aec_wanted():
                from . import win_aec
                mic = win_aec.open_mic(loop, queue, mic_id)
                if mic is not None:
                    return mic
        return _PortMic(loop, queue, mic_id)
    return _PortMic(loop, queue)

def aec_wanted() -> 'bool':
    '''Windows: yankı engelleme açık mı (Ayarlar › SES › YANKI ENGELLEME; JARVIS_NO_AEC=1 de kapatır).'''

    return os.environ.get('JARVIS_NO_AEC') != '1' and settings.get('aec_enabled', True) is not False

def selected_mic() -> 'str':
    '''Windows: Ayarlar › SES › MİKROFON'da seçilen aygıtın kimliği ("" = Windows varsayılanı).'''

    return str(settings.get('mic_device') or '')

def _pa_input(mic_id: 'str') -> 'int | None':
    """Seçilen aygıtın PortAudio'daki (MME) sırası. MME adları 31 harfte kesilir: adın başıyla eşleşir. Bulunamazsa
    None (Windows varsayılanı)."""

    if not mic_id:
        return
    from . import win_aec
    name = win_aec.name_of(mic_id)
    if not name:
        return
    try:
        host = sd.default.hostapi
        for i, dev in enumerate(sd.query_devices()):
            if dev['hostapi'] != host:
                continue
            if not dev['max_input_channels'] > 0:
                continue
            if not dev['name']:
                continue
            if not name.startswith(dev['name'].rstrip()):
                continue
            return i
        return
    except Exception:
        pass

def Speaker(echo: 'bool'=True):
    """Yazılan ses bir tampona eklenir ve çalınır. Yavaş olabilir: iş parçacığında çağır. echo=False (MİKROFON
    kapalı): Mac'te yankı engelleyen yardımcı kullanılmaz; o mikrofonu da açık tuttuğu için macOS'un göstergesi yanardı."""

    voice = voice_io() if echo else None
    if voice is not None:
        return _VoiceSpeaker(voice)
    if paths.IS_WIN:
        from . import win_aec
        return win_aec.Speaker()
    return _PortSpeaker()

class _PortMic:
    '''PortAudio mikrofonu (yankı engelleme yok).'''

    echo_cancelled = False
    path = 'düz'
    def __init__(self, loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue', mic_id: 'str'='') -> 'None':
        self.last_callback = time.monotonic()
        device = _pa_input(mic_id) if paths.IS_WIN else None
        self.device_id = mic_id if device is not None else ''
        try:
            self.device_name = str(sd.query_devices(device, kind='input')['name']) if device is not None else str(sd.query_devices(kind='input')['name'])
        except Exception:
            self.device_name = ''
        def callback(indata, _frames, _time, _status):
            self.last_callback = time.monotonic()
            data = bytes(indata)
            try:
                loop.call_soon_threadsafe(_offer, queue, data)
                return
            except RuntimeError:
                return

        self.stream = sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype='int16', device=device, blocksize=CHUNK, callback=callback)
        self.stream.start()
        self.last_callback = time.monotonic()

    def close(self) -> 'None':
        try:
            self.stream.stop()
            self.stream.close()
            return
        except Exception:
            return


def test_mic(seconds: 'float'=3.0) -> 'dict':
    """Ayarlar › SES › MİKROFONU DENE, JARVIS'in mikrofonu açık değilken: seçili aygıtı düz yoldan kısa süre açar.
    Açılamazsa PortAudio'nun hatası yükselir (çağıran türünü ayırır)."""

    device = _pa_input(selected_mic()) if paths.IS_WIN else None
    peaks = []
    def callback(indata, _frames, _time, _status):
        peaks.append(peak(bytes(indata)))

    with sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype='int16', device=device, blocksize=CHUNK, callback=callback):
        time.sleep(seconds)
    try:
        name = str(sd.query_devices(device, kind='input')['name']) if device is not None else str(sd.query_devices(kind='input')['name'])
    except Exception:
        name = ''
    if paths.IS_WIN and name:
        try:
            from . import win_aec
            chosen = selected_mic() if device is not None else ''
            full = win_aec.name_of(chosen) if chosen else win_aec.describe().get('mic', '')
            if full and full.startswith(name.rstrip()):
                name = full
        except Exception:
            pass
    out = {'peak': max(peaks, default=0.0), 'chunks': len(peaks), 'path': 'düz', 'device': name}
    if paths.IS_WIN and selected_mic() and device is None:
        out['note'] = 'seçili aygıt bulunamadı (çıkarılmış ya da JARVIS açıldıktan sonra takılmış); varsayılan denendi'
    return out

def _offer(queue: 'asyncio.Queue', data: 'bytes') -> 'None':
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(data)

class _PortSpeaker:
    '''PortAudio hoparlörü: ses kartı tampondan çeker (boşalınca biraz biriktirip devam eder).'''

    echo_cancelled = False
    def __init__(self) -> 'None':
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.last_callback = time.monotonic()
        self._playing = False
        self._since = 0.0
        self._dry_at = -GAP
        self.gaps = 0
        prebuffer = int(PREBUFFER * SPEAKER_RATE) * 2
        def callback(outdata, frames, _time, _status):
            self.last_callback = (now := time.monotonic())
            need = frames * 2
            take = b''
            with self._lock:
                if not self._playing:
                    if self._buf:
                        if len(self._buf) >= prebuffer or now - self._since >= PREBUFFER_WAIT:
                            self._playing = True
                if self._playing:
                    take = bytes(self._buf[:need])
                    del self._buf[:need]
                    if not self._buf:
                        self._playing = False
                        self._dry_at = now
            if take:
                take = self._on_play(take, now)
            outdata[:len(take)] = take
            if len(take) < need:
                outdata[len(take):] = b'\x00' * (need - len(take))

        self.stream = sd.RawOutputStream(samplerate=SPEAKER_RATE, channels=1, dtype='int16', callback=callback)
        self.stream.start()

    def _on_play(self, take: 'bytes', _now: 'float') -> 'bytes':
        """Ses kartına giden parça (Windows'ta söz kesme için kısılır ve ölçülür: win_aec.Speaker)."""

        return take

    def write(self, pcm: 'bytes') -> 'None':
        with self._lock:
            if not self._buf and not self._playing:
                self._since = time.monotonic()
                if self._since - self._dry_at < GAP:
                    self.gaps += 1
            self._buf.extend(pcm)

    def pending(self) -> 'int':
        with self._lock:
            return len(self._buf)

    def unplayed(self) -> 'bytes':
        '''Tamponda henüz çalınmamış ses (Windows: aygıt değişince yeni hoparlörde sürer; gemini_live._pump_speaker).'''

        with self._lock:
            return bytes(self._buf)

    def clear(self) -> 'None':
        with self._lock:
            self._buf.clear()
            self._playing = False
            self._dry_at = -GAP

    def duck(self, _on: 'bool') -> 'None':
        pass

    def warm(self) -> 'bool':
        return True

    def close(self) -> 'None':
        try:
            self.stream.stop()
            self.stream.close()
            return
        except Exception:
            return


VOICE_EXE = 'jarvis-voice-helper'
VOICE_READY_WAIT = 6.0
VOICE_GRACE = 6.0
VOICE_RETRY = 300.0
WARM_SAMPLES = int(3.0 * SPEAKER_RATE)
DUCK = 0.35
_voice: 'VoiceIO | None' = None
_voice_lock = threading.Lock()
_voice_failed_at = -VOICE_RETRY
voice_error = ''

def voice_io() -> 'VoiceIO | None':
    '''Açık yardımcı (kullanıcı sayısı bir artırılmış olarak) ya da None (eski ses yolu).'''

    global _voice, _voice_failed_at, voice_error
    if sys.platform != 'darwin' or os.environ.get('JARVIS_NO_AEC') == '1':
        return
    with _voice_lock:
        if _voice is not None and _voice.alive:
            _voice.attach()
            return _voice
        _voice = None
        if time.monotonic() - _voice_failed_at < VOICE_RETRY:
            return
        try:
            _voice = VoiceIO(_voice_binary())
        except Exception as exc:
            _voice_failed_at = time.monotonic()
            voice_error = str(exc) or type(exc).__name__
            log('yankı engelleme açılamadı, eski ses yolu kullanılıyor:', exc)
            return
        voice_error = ''
        _voice.attach()
        return _voice

def _drop_voice() -> 'None':
    global _voice, _voice_failed_at
    with _voice_lock:
        voice, _voice = _voice, None
        _voice_failed_at = -VOICE_RETRY
    if voice is not None:
        voice.close()

def _voice_binary() -> 'Path':
    """JARVIS.app'te hazır derlenmiş gelir; kaynaktan çalışırken ilk kullanımda derlenir."""

    if paths.FROZEN:
        exe = paths.BUNDLED_HELPERS / f'{paths.VOICE_HELPER}.app' / 'Contents' / 'MacOS' / VOICE_EXE
        if not exe.exists():
            raise RuntimeError('ses yardımcısı uygulama paketinde yok')
        return exe
    src = paths.HELPERS_SRC / 'jarvis_voice_helper.swift'
    plist = paths.HELPERS_SRC / 'jarvis_voice_helper.plist'
    contents = paths.HELPERS_BUILD / f'{paths.VOICE_HELPER}.app' / 'Contents'
    exe = contents / 'MacOS' / VOICE_EXE
    if exe.exists() and exe.stat().st_mtime >= max(src.stat().st_mtime, plist.stat().st_mtime):
        return exe
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    (contents / 'Info.plist').write_bytes(plist.read_bytes())
    cache = paths.DATA_DIR / '.swift-cache'
    cache.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'CLANG_MODULE_CACHE_PATH': str(cache), 'SWIFT_MODULE_CACHE_PATH': str(cache)}
    done = subprocess.run(['swiftc', '-O', str(src), '-o', str(exe)], capture_output=True, text=True, timeout=180, env=env)
    if done.returncode != 0:
        raise RuntimeError('ses yardımcısı derlenemedi: ' + (done.stderr or done.stdout).strip()[-300:])
    return exe

class VoiceIO:
    """Yardımcı süreç: çerçeveli standart giriş/çıkış (biçim jarvis_voice_helper.swift'in başında)."""

    def __init__(self, binary: 'Path') -> 'None':
        self.proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.alive = True
        self.info = {}
        self.last_mic = self.last_status = time.monotonic()
        self.gaps = 0
        self.played = 0
        self.low = None
        self.target = 0
        self.speaker = None
        self.mic_sink = None
        self._users = 0
        self._close_timer = None
        self._wlock = threading.Lock()
        self._epoch = 0
        self._sent = 0
        self._status = (0, 0, 0)
        self._renders = -1
        self._error = ''
        self._ready = threading.Event()
        threading.Thread(target=self._reader, daemon=True, name='ses-yardimcisi').start()
        if not self._ready.wait(VOICE_READY_WAIT) or self._error or not self.alive:
            self.close()
            raise RuntimeError(self._error or 'ses yardımcısı yanıt vermedi')
        log('yankı engelleme açık:', self.info)

    def _reader(self) -> 'None':
        out = self.proc.stdout
        try:
            head = out.read(5)
            if len(head) < 5:
                pass
            else:
                kind, size = head[:1], struct.unpack('<I', head[1:])[0]
                data = out.read(size) if size else b''
                if len(data) < size:
                    pass
                elif kind == b'M':
                    self.last_mic = time.monotonic()
                    sink = self.mic_sink
                    if sink is not None:
                        sink(data)
                elif kind == b'S' and len(data) >= 24:
                    epoch, received, pending, renders, gaps, played = struct.unpack('<6I', data[:24])
                    self._status = epoch, received, pending
                    if renders != self._renders:
                        self._renders = renders
                        self.last_status = time.monotonic()
                    self.gaps, self.played = gaps, played
                    if len(data) >= 32:
                        low, self.target = struct.unpack('<2I', data[24:32])
                        if low != 4294967295:
                            self.low = low if self.low is None else min(self.low, low)
                elif kind == b'R':
                    pass
            try:
                self.info = json.loads(data or b'{}')
            except ValueError:
                pass
            else:
                self._ready.set()
                if kind == b'E':
                    self._error = data.decode('utf-8', 'replace')
                    log('ses yardımcısı:', self._error)
                    self._ready.set()
        except (OSError, ValueError):
            pass
        self.alive = False
        self.last_mic = self.last_status = 0.0
        self._ready.set()

    def _send(self, kind: 'bytes', payload: 'bytes'=b'') -> 'None':
        if not self.alive:
            return
        try:
            with self._wlock:
                self.proc.stdin.write(kind + struct.pack('<I', len(payload)) + payload)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            self.alive = False

    def play(self, pcm: 'bytes') -> 'None':
        self._sent += len(pcm) // 2
        self._send(b'P', pcm)

    def pending_samples(self) -> 'int':
        epoch, received, pending = self._status
        if epoch != self._epoch & 4294967295:
            return self._sent
        return pending + max(0, self._sent - received)

    def clear(self) -> 'None':
        self._epoch += 1
        self._sent = 0
        self._send(b'C', struct.pack('<I', self._epoch & 4294967295))

    def gain(self, value: 'float') -> 'None':
        self._send(b'G', struct.pack('<f', value))

    def end_of_speech(self) -> 'None':
        self._send(b'D')

    def attach(self) -> 'None':
        self._users += 1
        if self._close_timer is not None:
            self._close_timer.cancel()
            self._close_timer = None

    def detach(self) -> 'None':
        with _voice_lock:
            self._users -= 1
            if self._users > 0 or not self.alive:
                return
            timer = threading.Timer(VOICE_GRACE, self._close_if_unused)
            timer.daemon = True
            self._close_timer = timer
            timer.start()

    def _close_if_unused(self) -> 'None':
        global _voice
        with _voice_lock:
            if self._users > 0:
                return
            if _voice is self:
                _voice = None
        self.close()

    def close(self) -> 'None':
        self.alive = False
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class _VoiceMic:
    echo_cancelled = True
    def __init__(self, voice: 'VoiceIO', loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue') -> 'None':
        self._voice = voice
        self._closed = False
        def sink(data: 'bytes') -> 'None':
            try:
                loop.call_soon_threadsafe(_offer, queue, data)
                return
            except RuntimeError:
                return

        self._sink = sink
        voice.mic_sink = sink

    @property
    def last_callback(self) -> 'float':
        return self._voice.last_mic

    def close(self) -> 'None':
        if self._closed:
            return
        self._closed = True
        if self._voice.mic_sink is self._sink:
            self._voice.mic_sink = None
        self._voice.detach()


class _VoiceSpeaker:
    echo_cancelled = True
    def __init__(self, voice: 'VoiceIO') -> 'None':
        self._voice = voice
        self._closed = False
        self._ducked = False
        self._gaps0 = voice.gaps
        self._wrote = 0
        voice.speaker = self

    @property
    def last_callback(self) -> 'float':
        return self._voice.last_status

    @property
    def gaps(self) -> 'int':
        return self._voice.gaps - self._gaps0

    def write(self, pcm: 'bytes') -> 'None':
        self._wrote += len(pcm)
        self._voice.play(pcm)

    def pending(self) -> 'int':
        return self._voice.pending_samples() * 2

    def buffer_report(self) -> 'tuple[int | None, int] | None':
        '''Son çağrıdan beri: tamponun söz ortasındaki en düşük doluluğu ve yardımcının ön tamponu (ms). Bu arada
        hoparlöre ses yazılmadıysa (ses telefona gitti) None.'''

        wrote, self._wrote = self._wrote, 0
        low = self._voice.low
        self._voice.low = None
        if not wrote:
            return
        return None if low is None else low * 1000 // SPEAKER_RATE, self._voice.target * 1000 // SPEAKER_RATE

    def clear(self) -> 'None':
        self._voice.clear()
        self._ducked = False

    def end_of_speech(self) -> 'None':
        '''Yazılan ses bir sözün sonu (tur bitti, araç çağrıldı): tampon boşalınca ardından gelen sessizlik doğal,
        ses geç gelmiş sayılmaz (yardımcı ön tamponu büyütmez).'''

        self._voice.end_of_speech()

    def duck(self, on: 'bool') -> 'None':
        '''Kullanıcı araya girdi: asistanın sesini kıs (sunucu sözü kesene ya da vazgeçilene dek).'''

        if on != self._ducked:
            self._ducked = on
            self._voice.gain(DUCK if on else 1.0)

    def warm(self) -> 'bool':
        '''Yankı engelleme uyum sağladı mı (ilk birkaç saniyelik çalmada asistanın izi daha güçlü).'''

        return self._voice.played >= WARM_SAMPLES

    def close(self) -> 'None':
        if self._closed:
            return
        self._closed = True
        if self._voice.speaker is self:
            self._voice.clear()
            self._voice.speaker = None
        self._voice.detach()


def turn_report(speaker, gaps: 'int') -> 'str | None':
    '''Mac, yankı engellemeli yardımcı: bir sesli turun hoparlör özeti (günlüğe; gemini_live her turda bir kez).
    Ses kesik geldiyse sebebi görünsün: JARVIS arkadayken macOS onu yavaşlatabiliyor, tampon söz ortasında
    boşaldıysa ses geç gelmiştir. Başka hoparlörde ya da bu turda ses çalınmadıysa None.'''

    report = getattr(speaker, 'buffer_report', None) if paths.IS_MAC else None
    numbers = report() if report is not None else None
    if numbers is None:
        return
    low, target = numbers
    front = {True: 'evet', False: 'hayır'}.get(app_in_front(), '?')
    return f'hoparlör: önde {front}, boşalma {gaps}, en az tampon {'-' if low is None else f'{low} ms'}, ön tampon {target} ms'

def app_in_front() -> 'bool | None':
    """Mac: JARVIS en öndeki (etkin) uygulama mı; bilinemezse None. NSRunningApplication'ın özellikleri her iş
    parçacığından okunabilir."""

    if not paths.IS_MAC:
        return
    try:
        import objc
        from AppKit import NSRunningApplication
        with objc.autorelease_pool():
            return bool(NSRunningApplication.currentApplication().isActive())
    except Exception:
        return

def peak(pcm: 'bytes') -> 'float':
    '''0..1 arası tepe seviyesi — ekrandaki ses çubukları için.'''

    if not pcm:
        return 0.0
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size:
        return float(np.abs(samples).max()) / 32768.0
    return 0.0

def reset() -> 'None':
    '''Aygıt listesini yeniler. PortAudio listeyi yalnızca açılışta okur; sonradan
    takılan kulaklığı görmesi için yeniden başlatılır. Açık akış olmamalı.
    Yankı engellemeli yardımcı da kapatılır: yeniden açılınca yeni aygıtı kullanır.'''

    global _pa_defaults
    _drop_voice()
    try:
        sd._terminate()
    except Exception:
        pass
    sd._initialize()
    _pa_defaults = _defaults_now()

def _defaults_now():
    if sys.platform == 'win32':
        return default_devices()

def pa_defaults() -> 'tuple | None':
    """Windows: PortAudio'nun başlatıldığı andaki varsayılan aygıtlar (hoparlör bu aygıtta açılır, sonradan değişse
    de). gemini_live._watch_audio farkı görünce sesi yeniden açar; yankı engelleme (win_aec) de o an Core Audio'nun
    varsayılanını dinlediği için ikisi aynı aygıtta buluşur. Başka sistemlerde None."""

    return _pa_defaults

def default_devices() -> 'tuple | None':
    """Sistemin o anki varsayılan (giriş, çıkış) aygıtı (yoksa -1); değişince ses oraya taşınır.

    macOS'ta CoreAudio'ya, Windows'ta Core Audio'ya doğrudan sorulur, çünkü PortAudio'nun listesi açılıştan
    sonra güncellenmez. Başka sistemlerde None (değişiklik izlenmez).
    """

    if sys.platform == 'win32':
        from . import win_aec
        return win_aec.default_ids()
    if sys.platform != 'darwin':
        return
    try:
        return _coreaudio_default(b'dIn '), _coreaudio_default(b'dOut')
    except (OSError, AttributeError):
        return

class _PropertyAddress(ctypes.Structure):
    _fields_ = [('selector', ctypes.c_uint32), ('scope', ctypes.c_uint32), ('element', ctypes.c_uint32)]

_coreaudio = None

def _coreaudio_default(selector: 'bytes') -> 'int':
    global _coreaudio
    if _coreaudio is None:
        _coreaudio = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
    address = _PropertyAddress(int.from_bytes(selector, 'big'), int.from_bytes(b'glob', 'big'), 0)
    device, size = ctypes.c_uint32(0), ctypes.c_uint32(4)
    status = _coreaudio.AudioObjectGetPropertyData(1, ctypes.byref(address), 0, None, ctypes.byref(size), ctypes.byref(device))
    if status == 0:
        return device.value
    return -1

def input_available() -> 'bool':
    try:
        return sd.query_devices(kind='input') is not None
    except Exception:
        return False

_pa_defaults = _defaults_now()

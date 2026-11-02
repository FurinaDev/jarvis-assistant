'''Medya (Windows): play_media (Spotify, YouTube) ve media_control (duraklat/sonraki/ne çalıyor, ses düzeyi).

Spotify: Mağaza paketindeki `spotify_cli.exe` (Spotify'ın kendi komut satırı aracı: arama, çalma, ne çalıyor;
masaüstü uygulaması açık ve giriş yapılmış olmalı). Aramanın en iyi sonucunun türüne göre şarkı, sanatçı ya da
çalma listesi çalınır; şarkıda adı sorguya en çok uyan seçilir (Spotify'ın ilk sırası bazen başka şarkı).
Testçi raporu (11 Ekim, "Spotify'ı açıyor ama çalamıyor, uygulama hatası"): aracın çıkış kodu artık okunuyor (çöken
araç başarı sayılmıyordu), çökme kutusu açılmıyor, bütün çalma tek bir süre bütçesinde (model aracı 30 sn'de keser),
paket yolu çökerse Windows'un takma adı (WindowsApps › spotify_cli.exe) deneniyor, aynı anda ikinci çalma isteği
beklemiyor. Spotify çalamazsa YouTube kendiliğinden açılmaz (Alp, 12 Ekim): model nedenini söyler, isterse kullanıcı
YouTube'u ister. Günlükte "spotify-hata: …" (sorgu yazılmaz; TEŞHİS'e girer).
Apple Music'in Windows'ta yönetilecek bir arayüzü yok.

media_control: Windows'un ortak medya oturumu (GSMTC; PowerShell'den WinRT, ~0,3 sn): hangi uygulama çalıyorsa
(Spotify, tarayıcıda YouTube, Apple Music) onu duraklatır, sürdürür, atlar. Ses düzeyi Core Audio'dan (ctypes).
'''

from __future__ import annotations
import ctypes
import json
import os
import re
import msvcrt
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import winreg
from ctypes import wintypes
from pathlib import Path
import psutil
from ..log import log
from .win_shell import run_powershell
_PACKAGES = 'Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\CurrentVersion\\AppModel\\Repository\\Packages'
START_WAIT = 25.0
BUDGET = 24.0
_CRASH = 3221225472
_NO_BOXES = 3
_busy = threading.Lock()
_want = ''
LOGIN_WAIT = 8.0
_use_alias = False

def _fold(text: 'str') -> 'str':
    text = unicodedata.normalize('NFKD', (text or '').replace('ı', 'i').replace('İ', 'i'))
    return ''.join((c for c in text if not unicodedata.combining(c))).casefold()

def _words(text: 'str') -> 'list[str]':
    return [w for w in re.split('[^\\w]+', _fold(text)) if w]

def _spotify_dirs() -> 'list[Path]':
    """Spotify'ın kurulu olabileceği klasörler: çalışan süreç, Mağaza paketi, klasik kurulum."""

    dirs = []
    for proc in psutil.process_iter(['name', 'exe']):
        if (proc.info['name'] or '').lower() != 'spotify.exe':
            continue
        if not proc.info['exe']:
            continue
        dirs.append(Path(proc.info['exe']).parent)
        break
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES) as key:
            names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
            for name in sorted((n for n in names if n.startswith('SpotifyAB.SpotifyMusic_')), reverse=True):
                with winreg.OpenKey(key, name) as sub:
                    dirs.append(Path(winreg.QueryValueEx(sub, 'PackageRootFolder')[0]))
    except OSError:
        pass
    dirs.append(Path(os.environ.get('APPDATA', '')) / 'Spotify')
    return dirs

def _alias() -> 'Path':
    '''Mağaza paketinin yürütme takma adı: aracı paket kimliğiyle başlatır (paket klasöründen doğrudan çalıştırınca
    kimlik yok; testçideki çökmenin nedeni bu olabilir).'''

    return Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WindowsApps' / 'spotify_cli.exe'

def _spotify_cli() -> 'str | None':
    if _use_alias and _alias().is_file():
        return str(_alias())
    return next((str(d / 'spotify_cli.exe') for d in _spotify_dirs() if (d / 'spotify_cli.exe').is_file()), None)

def spotify_summary() -> 'str':
    '''TEŞHİSİ KOPYALA için (win_diag.lines): kurulum türü, sürüm, komut aracı. Spotify açılmaz.'''

    try:
        dirs = _spotify_dirs()
    except Exception:
        return '?'
    store = next((d for d in dirs if 'SpotifyAB.SpotifyMusic_' in d.name if (d / 'Spotify.exe').is_file()), None)
    if store:
        version = store.name.split('_')[1] if store.name.count('_') >= 1 else '?'
        tools = [n for n, ok in (('paket', (store / 'spotify_cli.exe').is_file()), ('takma ad', _alias().is_file()))
             if ok]
        return f'Mağaza {version} · komut aracı: {', '.join(tools) or 'yok'}'
    if any(((d / 'Spotify.exe').is_file() for d in dirs)):
        tool = 'var' if any(((d / 'spotify_cli.exe').is_file() for d in dirs)) else 'yok (yalnızca arama sayfası açılır)'
        return f'spotify.com kurulumu · komut aracı: {tool}'
    return 'kurulu değil'

def spotify_installed() -> 'bool':
    return any(((d / 'Spotify.exe').is_file() for d in _spotify_dirs()))

def _first_line(data: 'bytes') -> 'str':
    text = data.decode('utf-8', 'replace').strip()
    if text:
        return text.splitlines()[0][:160]
    return ''

def _run(exe: 'str', args: 'list[str]', timeout: 'float') -> 'tuple[int | None, bytes, bytes]':
    '''Aracı çalıştırır; çökerse Windows'un "uygulama hatası" kutusu açılmaz. (çıkış kodu | None: süre doldu).'''

    old = msvcrt.GetErrorMode()
    msvcrt.SetErrorMode(old | _NO_BOXES)
    try:
        proc = subprocess.Popen([exe, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        msvcrt.SetErrorMode(old)
    try:
        out, err = proc.communicate(timeout=max(0.5, timeout))
    except subprocess.TimeoutExpired:
        try:
            kids = psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            kids = []
        proc.kill()
        for kid in kids:
            try:
                kid.kill()
            except psutil.Error:
                continue
    return proc.returncode, out, err

def _cli(exe: 'str', *args: 'str', timeout: 'float'=12) -> 'tuple[dict | None, str, str]':
    '''(JSON sonuç, hata metni, tür). Tür: ok | closed (Spotify kapalı) | error | crash | timeout. Çıkış kodu
    okunur: çöken araç ya da boş çıktı başarı sayılmaz. Paket yolundaki araç çökerse takma adla bir kez denenir.'''

    global _use_alias
    try:
        rc, out, err = _run(exe, [*args, '--format', 'json'], timeout)
    except OSError as exc:
        return None, str(exc)[:160], 'error'
    if rc is None:
        return (None, 'Spotify zamanında cevap vermedi', 'timeout')
    if rc >= _CRASH or rc < 0:
        alias = _alias()
        if not _use_alias:
            if alias.is_file() and Path(exe) != alias:
                _use_alias = True
                log(f'spotify-hata: {args[0]} çöktü rc=0x{rc & 4294967295:08X}; takma adla yeniden')
                return _cli(str(alias), *args, timeout=timeout)
        return None, f"Spotify'ın komut aracı çöktü (0x{rc & 4294967295:08X})", 'crash'
    if rc != 0:
        why = _first_line(err) or _first_line(out) or f'çıkış kodu {rc}'
        return None, why, 'closed' if 'not running' in why.lower() else 'error'
    text = out.decode('utf-8', 'replace').strip()
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return None, f'anlaşılmayan cevap: {text[:80]}', 'error'
    if isinstance(data, dict):
        if data.get('error') or data.get('success') is False:
            detail = data.get('error')
            detail = detail.get('message', '') if isinstance(detail, dict) else detail
            return None, str(detail or 'Spotify isteği reddetti')[:160], 'error'
    if isinstance(data, dict):
        return data, '', 'ok'
    return {'result': data}, '', 'ok'

def _spotify_running() -> 'bool':
    return any(((p.info['name'] or '').lower() == 'spotify.exe' for p in psutil.process_iter(['name'])))

def _ready(exe: 'str', end: 'float') -> 'tuple[bool, str]':
    '''Spotify açık ve giriş yapılmış mı; kapalıysa açılır ve `end`e (monotonic) kadar beklenir.'''

    status, why, kind = _cli(exe, 'status', timeout=min(6, end - time.monotonic()))
    if status and status.get('running') and status.get('logged_in'):
        return (True, '')
    if kind in ('crash', 'timeout', 'error'):
        _note('status', why)
        if kind != 'error' or _spotify_running():
            return False, f"Hata: Spotify'a ulaşılamadı ({why})."
    if not status or not status.get('running'):
        if not _spotify_running():
            os.startfile('spotify:')
        bad, limit, login_until = 0, min(end - 4, time.monotonic() + START_WAIT), 0.0
        while time.monotonic() < limit:
            time.sleep(0.8)
            status, why, kind = _cli(exe, 'status', timeout=min(6, end - time.monotonic()))
            if status and status.get('running') and status.get('logged_in'):
                time.sleep(1.0)
                return (True, '')
            if status and status.get('running'):
                login_until = login_until or min(limit, time.monotonic() + LOGIN_WAIT)
                if time.monotonic() >= login_until:
                    break
                bad = 0
                continue
            bad = bad + 1 if kind in ('crash', 'timeout') else 0
            if bad >= 2:
                _note('status', why)
                return False, f"Hata: Spotify'a ulaşılamadı ({why})."
    if status and status.get('running') and not status.get('logged_in'):
        return (False, "Hata: Spotify açık ama giriş yapılmamış. Kullanıcı Spotify'da hesabına girmeli.")
    _note('status', why or 'açılmadı')
    return (False, 'Hata: Spotify açılamadı ya da cevap vermiyor.')

def _note(step: 'str', why: 'str', query: 'str'='') -> 'None':
    """Günlüğe (TEŞHİS'e girer): sorgu yazılmaz."""

    text = (why or '').replace(query, '…') if query else why or ''
    log(f'spotify-hata: {step} {text[:120]}')

_KINDS = {'artists': ('artists', 'artist'), 'playlists': ('playlists', 'playlist'), 'albums': ('albums', 'album'), 'shows': ('shows', 'podcast'), 'audioepisodes': ('episodes', 'bölüm'), 'episodes': ('episodes', 'bölüm'), 'audiobooks': ('audiobooks', 'sesli kitap')}

def _pick(found: 'dict', query: 'str') -> 'tuple[str, str, str] | None':
    '''(uri, ekrandaki ad, tür). Sorgu "sanatçı + şarkı adı"ysa o şarkı; yoksa Spotify'ın en iyi sonuç türü
    (yalnızca "Duman" denince adı Duman olan başka birinin şarkısı değil, Duman grubu).'''

    words = set(_words(query))
    tracks = found.get('tracks') or []
    def score(t: 'dict') -> 'tuple[bool, int]':
        name = set(_words(t.get('name', '')))
        artists = set(_words(' '.join(t.get('artists') or [])))
        rest = words - name
        return bool(name) and name <= words and bool(rest) and rest <= artists, len(words & (name | artists))

    best = max(tracks, key=score, default=None)
    if best and score(best)[0]:
        return best['uri'], f'{best['name']} — {', '.join(best.get('artists') or [])}', 'track'
    for kind in found.get('categories_order') or []:
        if kind == 'tracks' and best:
            return best['uri'], f'{best['name']} — {', '.join(best.get('artists') or [])}', 'track'
        key, label = _KINDS.get(kind, (kind, kind))
        items = found.get(key) or []
        if kind not in _KINDS:
            continue
        if not items:
            continue
        if not items[0].get('uri'):
            continue
        return items[0]['uri'], items[0].get('name') or query, label
    if best:
        return best['uri'], f'{best['name']} — {', '.join(best.get('artists') or [])}', 'track'

_GIVE_UP = " Aynı isteği tekrar deneme ve YouTube'u kendiliğinden açma; kullanıcıya nedenini kısaca söyle, isterse YouTube'dan açabileceğini sor."

def play_spotify(query: 'str', autoplay: 'bool'=True) -> 'str':
    global _want
    exe = _spotify_cli()
    if not exe:
        if not spotify_installed():
            return 'Hata: Spotify yüklü görünmüyor.'
        os.startfile('spotify:search:' + urllib.parse.quote(query))
        return f"Spotify içinde '{query}' araması açıldı. Kullanıcıya ilk sonuca tıklamasını söyle."
    end = time.monotonic() + BUDGET
    if not _busy.acquire(blocking=False):
        if _fold(query) == _want:
            return "Spotify'da aynı çalma isteği hâlâ sürüyor; birkaç saniye içinde çalmaya başlar. Bu isteği tekrar çağırma, sonucu bekle."
        _want = _fold(query)
        if not _busy.acquire(timeout=max(0.0, end - time.monotonic() - 8)):
            return f"Hata: Spotify önceki isteği başlatırken '{query}' çalınamadı. Kullanıcıya birkaç saniye sonra yeniden istemesini söyle."
    _want = _fold(query)
    try:
        return _play(exe, query, autoplay, end)
    finally:
        _busy.release()

def _replaced(query: 'str') -> 'bool':
    '''Bu istek sürerken başka bir şarkı istendi mi.'''

    return _want != _fold(query)

def _play(exe: 'str', query: 'str', autoplay: 'bool', end: 'float') -> 'str':
    ok, why = _ready(exe, end)
    if not ok:
        return why + _GIVE_UP
    exe = _spotify_cli() or exe
    if end - time.monotonic() < 3:
        _note('süre', 'Spotify açılırken süre doldu')
        return 'Hata: Spotify zamanında açılmadı.' + _GIVE_UP
    if _replaced(query):
        return 'Hata: yerine yeni bir çalma isteği geldi; bu istek bırakıldı.'
    found, err, kind = _cli(exe, 'search', query, '--limit', '8', timeout=min(12, end - time.monotonic()))
    if found is None:
        _note('search', err, query)
        return f"Hata: Spotify'da arama yapılamadı ({err.replace(query, '…')})." + _GIVE_UP
    chosen = _pick(found, query)
    if not chosen:
        return f"Spotify'da '{query}' için bir sonuç çıkmadı. Kullanıcıya başka bir ad ya da YouTube'u öner."
    uri, label, kind = chosen
    log(f'spotify: {query!r} → {kind} {label} ({uri})')
    if not autoplay:
        _, err, _k = _cli(exe, 'navigate', uri, timeout=min(8, end - time.monotonic()))
        if err:
            _note('navigate', err, query)
            return f"Hata: Spotify'da açılamadı ({err})." + _GIVE_UP
        return f"Spotify'da açıldı: {label}"
    if _replaced(query):
        return 'Hata: yerine yeni bir çalma isteği geldi; bu istek bırakıldı.'
    if end - time.monotonic() < 2:
        _note('süre', 'aramadan sonra süre doldu')
        return 'Hata: Spotify zamanında cevap vermedi.' + _GIVE_UP
    _, err, _k = _cli(exe, 'play', uri, timeout=min(12, end - time.monotonic()))
    if err:
        _note('play', err, query)
        return f"Hata: Spotify'da çalınamadı ({err})." + _GIVE_UP
    stop = min(end, time.monotonic() + 4)
    while time.monotonic() < stop:
        time.sleep(0.5)
        now, _e, _k = _cli(exe, 'now-playing', timeout=max(0.5, min(5, end - time.monotonic())))
        current = (now or {}).get('currently_playing') or {}
        if current.get('is_playing'):
            if kind != 'track' or current.get('uri') == uri:
                playing = current.get('description') or label
                if kind == 'track':
                    return f"Spotify'da çalıyor: {playing}" + ''
                return None + f' ({label})'
    _note('doğrulama', 'çalma komutu gitti ama başlamadı')
    return f"Hata: Spotify'a '{label}' çalma komutu gitti ama çalma başlamadı. Kullanıcıya Spotify'a bakmasını söyle (başka bir cihazda çalıyor olabilir). Aynı isteği tekrar deneme ve YouTube'u kendiliğinden açma."

def play_media(query: 'str', provider: 'str'='auto', autoplay: 'bool'=True) -> 'str':
    if not query or not query.strip():
        return 'Çalınacak içerik belirtilmedi.'
    provider = (provider or 'auto').strip().lower()
    if provider in {'youtube music', 'yt', 'youtube'}:
        from .win_browser import browser_control
        return browser_control('play_youtube', query=query) or 'YouTube açıldı.'
    if provider in {'apple music', 'music', 'apple_music'}:
        return "Apple Music Windows'ta yönetilemiyor (arama ve çalma yapılamaz). Kullanıcıya Spotify ya da YouTube'dan çalmayı öner."
    if provider == 'spotify' or spotify_installed():
        result = play_spotify(query, autoplay)
        if provider == 'spotify' or 'yüklü görünmüyor' not in result:
            return result
    from .win_browser import browser_control
    return browser_control('play_youtube', query=query) or 'YouTube açıldı.'

_GSMTC = '\n$action = \'__ACTION__\'\nAdd-Type -AssemblyName System.Runtime.WindowsRuntime\n$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq \'AsTask\' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq \'IAsyncOperation`1\' })[0]\nfunction Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); if ($t.Wait(5000)) { $t.Result } else { $null } }\n$M = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime]\n$PT = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType=WindowsRuntime]\nfunction Info($s) {\n  $p = Await ($s.TryGetMediaPropertiesAsync()) $PT\n  @{ app = $s.SourceAppUserModelId; title = $p.Title; artist = $p.Artist; status = [string]$s.GetPlaybackInfo().PlaybackStatus }\n}\n$mgr = Await ($M::RequestAsync()) $M\n$all = @($mgr.GetSessions())\nif (-not $all.Count) { \'{"none":true}\'; return }\n$playing = @($all | Where-Object { [string]$_.GetPlaybackInfo().PlaybackStatus -eq \'Playing\' })\n$cur = $mgr.GetCurrentSession(); if (-not $cur) { $cur = $all[0] }\n$target = if ($playing.Count -and $action -ne \'play\') { $playing[0] } else { $cur }\n$done = $true\nswitch ($action) {\n  \'pause\'    { $done = $playing.Count -gt 0; foreach ($s in $playing) { $null = Await ($s.TryPauseAsync()) ([bool]) } }\n  \'play\'     { $done = Await ($target.TryPlayAsync()) ([bool]) }\n  \'toggle\'   { $done = Await ($target.TryTogglePlayPauseAsync()) ([bool]) }\n  \'next\'     { $done = Await ($target.TrySkipNextAsync()) ([bool]) }\n  \'previous\' { $done = Await ($target.TrySkipPreviousAsync()) ([bool]) }\n}\nif ($action -ne \'now_playing\') { Start-Sleep -Milliseconds 700 }\n@{ done = $done; playing = $playing.Count; info = (Info $target) } | ConvertTo-Json -Compress\n'

def _app_label(aumid: 'str') -> 'str':
    '''Oturumun uygulama kimliği → görünen ad ("SpotifyAB.SpotifyMusic_…!Spotify" → "Spotify").'''

    try:
        from .win_apps import _index
        hit = next((a.name for a in _index() if a.app_id.lower() == aumid.lower()), None)
        if hit:
            return hit
    except Exception:
        pass
    if '!' in aumid:
        return aumid.split('!')[-1]
    return Path(aumid).stem or aumid

def _session(action: 'str') -> 'dict | str':
    code, out = run_powershell(_GSMTC.replace('__ACTION__', action), timeout=15)
    if code is None:
        return 'Hata: medya oturumu cevap vermedi.'
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        log('medya oturumu okunamadı:', out.strip()[:200])
        return 'Hata: çalan medya okunamadı.'

def _describe(info: 'dict') -> 'str':
    title = ' — '.join((x for x in (info.get('title'), info.get('artist')) if x)) or 'bilinmeyen parça'
    return f'{title} ({_app_label(info.get('app') or '')})'

_STATUS = {'Playing': 'çalıyor', 'Paused': 'duraklatılmış', 'Stopped': 'durmuş', 'Changing': 'değişiyor', 'Opened': 'açık', 'Closed': 'kapalı'}

def _transport(action: 'str') -> 'str':
    result = _session(action)
    if isinstance(result, str):
        return result
    if result.get('none'):
        if action == 'now_playing':
            return 'Şu an çalan bir şey yok.'
        return 'Kontrol edilecek bir medya yok (hiçbir uygulama çalmıyor). Yeni bir şey çalmak için play_media kullan.'
    info = result.get('info') or {}
    what = _describe(info)
    state = _STATUS.get(info.get('status'), info.get('status') or '')
    if action == 'now_playing':
        return f'Şu an: {what}, {state}.'
    if action == 'pause' and not result.get('playing'):
        return f'Zaten çalan bir şey yok; son oturum: {what}, {state}.'
    if not result.get('done'):
        return f'Hata: {_app_label(info.get('app') or '')} bu komutu kabul etmedi. Şu an: {what}, {state}.'
    verb = {'pause': 'Duraklatıldı', 'play': 'Devam ediyor', 'toggle': 'Tamam', 'next': 'Sonraki parça', 'previous': 'Önceki parça'}[action]
    return f'{verb}: {what}, {state}.'

class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

def _guid(text: 'str') -> '_GUID':
    import uuid
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
    return g

_ole32 = ctypes.WinDLL('ole32')
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.c_long
_CLSID_ENUMERATOR = 'BCDE0395-E52F-467C-8E3D-C4579291692E'
_IID_ENUMERATOR = 'A95664D2-9614-4F35-A746-DE8DB63617E6'
_IID_ENDPOINT_VOLUME = '5CDF2C82-841E-4546-9722-0CF74078229A'

def _method(obj: 'ctypes.c_void_p', index: 'int', *argtypes):
    '''COM nesnesinin sanal tablosundaki `index`. yöntem (ilk bağımsız değişken nesnenin kendisi).'''

    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
    return lambda *args: fn(obj, *args)

class _Endpoint:
    """Varsayılan hoparlörün IAudioEndpointVolume'ü (with içinde)."""

    def __enter__(self):
        self.owned = _ole32.CoInitializeEx(None, 2) in (0, 1)
        self.objs = []
        try:
            return self._open()
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _open(self):
        enum, device, volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if _ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_ENUMERATOR)), None, 23, ctypes.byref(_guid(_IID_ENUMERATOR)), ctypes.byref(enum)) or not enum.value:
            raise OSError('ses aygıtları okunamadı')
        self.objs.append(enum)
        if _method(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(0, 1, ctypes.byref(device)) or not device.value:
            raise OSError('hoparlör bulunamadı')
        self.objs.append(device)
        if _method(device, 3, ctypes.POINTER(_GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(_guid(_IID_ENDPOINT_VOLUME)), 23, None, ctypes.byref(volume)) or not volume.value:
            raise OSError('ses denetimi açılamadı')
        self.objs.append(volume)
        self.ep = volume
        return self

    def __exit__(self, *exc):
        for obj in reversed(self.objs):
            _method(obj, 2)()
        if self.owned:
            _ole32.CoUninitialize()

    def level(self) -> 'int':
        value = ctypes.c_float()
        _method(self.ep, 9, ctypes.POINTER(ctypes.c_float))(ctypes.byref(value))
        return round(value.value * 100)

    def set_level(self, percent: 'int') -> 'None':
        _method(self.ep, 7, ctypes.c_float, ctypes.c_void_p)(max(0, min(100, percent)) / 100, None)

    def muted(self) -> 'bool':
        value = wintypes.BOOL()
        _method(self.ep, 15, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(value))
        return bool(value.value)

    def set_muted(self, on: 'bool') -> 'None':
        _method(self.ep, 14, wintypes.BOOL, ctypes.c_void_p)(on, None)


def _volume(action: 'str', level: 'int | None') -> 'str':
    try:
        with _Endpoint() as ep:
            if action == 'mute':
                ep.set_muted(True)
                return 'Bilgisayarın sesi kapatıldı (benim sesim de duyulmaz).'
            if action == 'unmute':
                ep.set_muted(False)
                return f'Bilgisayarın sesi açıldı: %{ep.level()}.'
            if action == 'volume_get':
                return f'Ses düzeyi %{ep.level()}' + (', sessizde.' if ep.muted() else '.')
            now = ep.level()
            if action == 'volume_set':
                if level is None:
                    return 'Hata: ses düzeyi belirtilmedi (0-100).'
                target = level
            else:
                step = level if level else level if 0 < level <= 100 else 10
                target = now + step if action == 'volume_up' else now - step
            ep.set_level(target)
            if ep.muted() and action in ('volume_set', 'volume_up') and target > 0:
                ep.set_muted(False)
            return f'Ses düzeyi %{ep.level()}.'
    except OSError as exc:
        return f'Hata: ses ayarlanamadı ({exc}).'

TRANSPORT = {'next', 'play', 'pause', 'toggle', 'previous', 'now_playing'}
VOLUME = {'mute', 'unmute', 'volume_up', 'volume_get', 'volume_set', 'volume_down'}
_ALIASES = {'stop': 'pause', 'resume': 'play', 'skip': 'next', 'prev': 'previous', 'status': 'now_playing', 'playpause': 'toggle', 'play_pause': 'toggle'}

def media_control(action: 'str', level: 'int | None'=None) -> 'str':
    action = (action or '').strip().lower().replace('-', '_')
    action = _ALIASES.get(action, action)
    if action in TRANSPORT:
        return _transport(action)
    if action in VOLUME:
        return _volume(action, level)
    return f"Hata: bilinmeyen işlem '{action}'. Geçerli: {', '.join(sorted(TRANSPORT | VOLUME))}."

# WARNING: Decompyle incomplete

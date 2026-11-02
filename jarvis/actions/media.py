'''
Medya oynatma — YouTube, Spotify Desktop ve Apple Music/Music uygulaması.

Not:
- Spotify kendi AppleScript komutuyla çalınır (yalnızca Otomasyon izni).
- Music kitaplıkta bulamazsa arama kutusuna tuşla yazılır: bunun için Erişilebilirlik izni gerekir.
'''

from __future__ import annotations
import os
import subprocess
import time
import urllib.parse
from .. import permissions
from .browser import browser_control
SPOTIFY_APP = '/Applications/Spotify.app'
MUSIC_APP = '/System/Applications/Music.app'

def _run_osascript(script: 'str', timeout: 'int'=16) -> 'tuple[bool, str]':
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, f'AppleScript çalıştırılamadı: {exc}'
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip() or 'Bilinmeyen AppleScript hatası'
        return False, permissions.describe_failure(detail)
    return True, (result.stdout or '').strip()

def _copy_to_clipboard(text: 'str') -> 'tuple[bool, str]':
    try:
        subprocess.run(['pbcopy'], input=text, text=True, check=True, timeout=5)
        return (True, 'ok')
    except Exception as exc:
        return False, f'Panoya kopyalanamadı: {exc}'

def _app_exists(path: 'str') -> 'bool':
    return os.path.exists(path)

def _play_youtube(query: 'str') -> 'str':
    return browser_control('play_youtube', query=query)

def _spotify_now() -> 'tuple[str, str, float, str]':
    '''(durum, şarkı adresi, konum sn, "Sanatçı — Şarkı"); Spotify cevap vermezse durum boş.'''

    ok, out = _run_osascript('tell application "Spotify"\n    set playerState to player state as text\n    try\n        set trackUrl to spotify url of current track\n        set trackTitle to (artist of current track) & " — " & (name of current track)\n        set trackPos to player position\n    on error\n        set trackUrl to ""\n        set trackTitle to ""\n        set trackPos to 0\n    end try\n    return playerState & linefeed & trackUrl & linefeed & (trackPos as text) & linefeed & trackTitle\nend tell\n', timeout=6)
    parts = out.split('\n') if ok else []
    if len(parts) < 4:
        return ('', '', 0.0, '')
    try:
        pos = float(parts[2].replace(',', '.'))
    except ValueError:
        pos = 0.0
    return parts[0].strip(), parts[1].strip(), pos, parts[3].strip()

def _play_spotify(query: 'str', autoplay: 'bool'=True) -> 'str':
    '''Spotify'ın kendi komutuyla aramanın ilk sonucunu çalar: `play track "spotify:search:…"`.
    Tuş göndermez (eskiden gönderiyordu; Spotify'ın yeni arayüzünde tutmuyordu), bu yüzden
    Erişilebilirlik izni gerekmez, yalnızca Otomasyon. Çalmanın gerçekten başladığı doğrulanır.'''

    if not _app_exists(SPOTIFY_APP):
        return 'Spotify yüklü görünmüyor.'
    uri = f'spotify:search:{urllib.parse.quote(query.strip())}'
    if not autoplay:
        try:
            subprocess.run(['open', uri], check=True, timeout=10)
        except Exception as exc:
            return f'Spotify açılamadı: {exc}'
        return f"Spotify içinde '{query}' araması açıldı."
    running = subprocess.run(['pgrep', '-x', 'Spotify'], capture_output=True).returncode == 0
    if not running:
        subprocess.run(['open', '-g', '-a', 'Spotify'], check=False, timeout=10)
        end = time.monotonic() + 12
        while time.monotonic() < end and not _spotify_now()[0]:
            time.sleep(0.5)
        time.sleep(1.5)
    before_state, before_url, _, _ = _spotify_now()
    for _ in range(3):
        ok, detail = _run_osascript(f'tell application "Spotify" to play track "{uri}"', timeout=8)
        if not ok:
            return f"Spotify'da çalınamadı: {detail}"
        for _ in range(6):
            time.sleep(0.5)
            state, url, pos, title = _spotify_now()
            if state != 'playing':
                continue
            if url == before_url and before_state == 'playing' and not pos < 5:
                pass
            else:
                return f"Spotify'da çalıyor: {title or query}"
                continue
    subprocess.run(['open', uri], check=False, timeout=10)
    return f"Spotify'da '{query}' araması açıldı ama çalma başlamadı. Kullanıcıya Spotify'da ilk sonuca tıklamasını söyle."

def _play_music_app(query: 'str', autoplay: 'bool'=True) -> 'str':
    if not _app_exists(MUSIC_APP):
        return 'Apple Music / Music uygulaması bulunamadı.'
    if autoplay:
        escaped_query = query.replace('\\', '\\\\').replace('"', '\\"')
        script = f'set queryText to "{escaped_query}"\ntell application "Music"\n    activate\n    try\n        set foundTracks to (search library playlist 1 for queryText only songs)\n        if (count of foundTracks) > 0 then\n            set targetTrack to item 1 of foundTracks\n            play targetTrack\n            return "PLAYED"\n        end if\n    end try\nend tell\nreturn "NOT_FOUND"\n'
        ok, detail = _run_osascript(script, timeout=18)
        if ok and 'PLAYED' in detail:
            return f'Music uygulamasında oynatılıyor: {query}'
    ok_clip, detail_clip = _copy_to_clipboard(query.strip())
    if not ok_clip:
        return detail_clip
    script = 'tell application "Music" to activate\ndelay 1.0\ntell application "System Events"\n    keystroke "f" using {command down}\n    delay 0.3\n    keystroke "a" using {command down}\n    delay 0.1\n    keystroke "v" using {command down}\n    delay 1.1\n    key code 36\n    delay 0.7\n    key code 125\n    delay 0.2\n    key code 36\nend tell\n'
    ok, detail = _run_osascript(script, timeout=16)
    if ok:
        if autoplay:
            return f"Music uygulamasında '{query}' için arama yapıldı ve ilk sonuç açıldı."
        return f"Music uygulamasında '{query}' araması açıldı."
    search_url = f'music://music.apple.com/search?term={urllib.parse.quote(query.strip())}'
    try:
        subprocess.run(['open', search_url], check=False, timeout=10)
    except Exception:
        pass
    return f'Music uygulamasında doğrudan oynatma tamamlanamadı: {detail}. Arama açıldı: {query}'

def play_media(query: 'str', provider: 'str'='auto', autoplay: 'bool'=True) -> 'str':
    if not query or not query.strip():
        return 'Çalınacak içerik belirtilmedi.'
    normalized_provider = (provider or 'auto').strip().lower()
    if normalized_provider in {'youtube music', 'yt'}:
        normalized_provider = 'youtube'
    elif normalized_provider in {'apple music', 'music', 'apple_music'}:
        normalized_provider = 'apple_music'
    if normalized_provider == 'spotify':
        return _play_spotify(query, autoplay=autoplay)
    if normalized_provider == 'apple_music':
        return _play_music_app(query, autoplay=autoplay)
    if normalized_provider == 'youtube':
        return _play_youtube(query)
    if _app_exists(SPOTIFY_APP):
        result = _play_spotify(query, autoplay=autoplay)
        if 'yüklü görünmüyor' not in result and 'açılamadı' not in result:
            return result
    result = _play_music_app(query, autoplay=autoplay)
    if 'bulunamadı' not in result:
        return result
    return _play_youtube(query)

TRANSPORT = {'next', 'play', 'pause', 'toggle', 'previous', 'now_playing'}
VOLUME = {'mute', 'unmute', 'volume_up', 'volume_get', 'volume_set', 'volume_down'}
_ALIASES = {'stop': 'pause', 'resume': 'play', 'skip': 'next', 'prev': 'previous', 'status': 'now_playing', 'playpause': 'toggle', 'play_pause': 'toggle'}
_PLAYERS = (('Spotify', "Spotify'da"), ('Music', "Müzik'te"))
_BROWSERS = ('Google Chrome', 'Safari', 'Arc', 'Microsoft Edge', 'Brave Browser', 'Firefox')
_KEYS = {'toggle': 16, 'play': 16, 'pause': 16, 'next': 17, 'previous': 18}
_VERBS = {'pause': 'duraklattım', 'play': 'sürdürdüm', 'toggle': 'duraklatıp sürdürdüm', 'next': 'sonrakine geçtim', 'previous': 'öncekine döndüm'}

def media_control(action: 'str', level: 'int | None'=None) -> 'str':
    action = (action or '').strip().lower().replace('-', '_')
    action = _ALIASES.get(action, action)
    if action in TRANSPORT:
        return _transport(action)
    if action in VOLUME:
        return _volume(action, level)
    return f"Hata: bilinmeyen işlem '{action}'. Geçerli: {', '.join(sorted(TRANSPORT | VOLUME))}."

def _running(app: 'str') -> 'bool':
    ok, out = _run_osascript(f'application "{app}" is running', timeout=5)
    return ok and out.strip() == 'true'

def _player(app: 'str') -> 'tuple[str, str]':
    '''(durum, "Sanatçı — Şarkı") ya da çalışmıyorsa ("", "").'''

    if not _running(app):
        return ('', '')
    ok, out = _run_osascript(f'tell application "{app}"\n    set ps to player state as string\n    set info to ""\n    try\n        set info to (artist of current track) & " — " & (name of current track)\n    end try\n    return ps & "|" & info\nend tell', timeout=8)
    if not ok or '|' not in out:
        return ('', '')
    state, info = out.split('|', 1)
    return state.strip().lower(), info.strip()

def _transport(action: 'str') -> 'str':
    players = [(app, label, *_player(app)) for app, label in _PLAYERS]
    playing = [p for p in players if p[2] == 'playing']
    paused = [p for p in players if p[2] == 'paused']
    if action == 'now_playing':
        if playing:
            return '; '.join((f'{label} çalıyor: {info or 'bilinmeyen parça'}' for _a, label, _s, info in playing))
        if paused:
            return f'Şu an çalan yok; {paused[0][1]} duraklatılmış: {paused[0][3] or 'bilinmeyen parça'}.'
        return "Spotify'da ve Müzik'te çalan bir şey yok. Tarayıcıda (YouTube) çalıyorsa ne olduğunu göremiyorum."
    target = None
    if action in ('pause', 'next', 'previous'):
        target = playing[0] if playing else paused[0] if paused and action != 'pause' else None
    elif action in ('play', 'toggle'):
        target = playing[0] if playing and action == 'toggle' else paused[0] if paused else None
    if target:
        app, label, _state, _info = target
        command = {'pause': 'pause', 'play': 'play', 'toggle': 'playpause', 'next': 'next track', 'previous': 'previous track'}[action]
        ok, detail = _run_osascript(f'tell application "{app}" to {command}', timeout=8)
        if not ok:
            return f'Hata: {app} yönetilemedi. {detail}'
        if action in ('next', 'previous'):
            time.sleep(0.6)
            now = _player(app)[1]
            if now:
                return f'{label} {_VERBS[action]}' + f': {now}.'
            return None + '.'
        return f'{label} {_VERBS[action]}.'
    if action == 'pause' and not playing:
        if any((p[2] for p in players)):
            return "Spotify'da ve Müzik'te zaten çalan bir şey yok."
    if any((_running(b) for b in _BROWSERS)):
        need = permissions.require_accessibility()
        if need:
            return need
        _media_key(_KEYS[action])
        return f'Tarayıcıdaki oynatıcıya medya tuşu gönderdim ({_VERBS[action]}); YouTube gibi bir sitede çalıyorsa etkiler, sonucu göremiyorum.'
    return 'Şu an çalan ya da duraklatılmış bir müzik yok. Yeni bir şey çalmak için play_media kullan.'

def _media_key(key: 'int') -> 'None':
    """macOS'un medya tuşu (oynat/duraklat, sonraki, önceki): basılıp bırakılır."""

    import AppKit
    import Quartz
    for down in (True, False):
        flags = 2560 if down else 2816
        event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(AppKit.NSEventTypeSystemDefined, (0, 0), flags, 0, 0, None, 8, key << 16 | (10 if down else 11) << 8, -1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event.CGEvent())

def _volume(action: 'str', level: 'int | None') -> 'str':
    ok, out = _run_osascript('set v to get volume settings\nreturn ((output volume of v) as string) & "|" & ((output muted of v) as string)', timeout=5)
    if not ok or '|' not in out:
        return f'Hata: ses düzeyi okunamadı. {out}'.strip()
    raw, muted = out.split('|', 1)
    try:
        current = int(float(raw))
    except ValueError:
        return 'Hata: bu çıkış aygıtının ses düzeyi ayarlanamıyor (ör. HDMI ya da harici ses kartı).'
    muted_now = muted.strip() == 'true'
    if action == 'volume_get':
        return f'Ses düzeyi %{current}' + (' (sessizde).' if muted_now else '.')
    if action in ('mute', 'unmute'):
        _run_osascript(f'set volume output muted {'true' if action == 'mute' else 'false'}', timeout=5)
        if action == 'mute':
            return 'Ses kapatıldı (sessiz).'
        return f'Ses açıldı (%{current}).'
    step = abs(int(level)) if level else 10
    target = {'volume_set': level if level is not None else current, 'volume_up': current + step, 'volume_down': current - step}[action]
    target = max(0, min(100, int(target)))
    ok, detail = _run_osascript(f'set volume output volume {target}\nset volume output muted false', timeout=5)
    if not ok:
        return f'Hata: ses düzeyi ayarlanamadı. {detail}'
    return f'Ses düzeyi %{target}.'

# WARNING: Decompyle incomplete

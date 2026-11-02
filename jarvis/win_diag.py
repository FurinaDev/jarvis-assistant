"""Windows teşhis günlüğü: açılışta bir kez, ses sorunlarını uzaktan anlamak için (9 Ekim 2026 takipçi raporu).

Takipçinin bilgisayarında mikrofon üç aygıtla da çalışmadı ama günlükte aygıtın adı bile yoktu. Artık açılışta
jarvis.log'a bir satır: Windows sürümü ve mimarisi, PortAudio sürümü, varsayılan ses aygıtlarının adları (konsol ve
görüşme rolleri), mikrofon izni, yankı engelleme ayarı, seçili mikrofon ve kurulu antivirüs (Güvenlik Merkezi'nden,
salt okunur). Kişisel bilgi yok: aygıt ve ürün adları.

Yalnızca Windows'ta, ayrı bir iş parçacığında çağrılır (app.App._begin).
"""

from __future__ import annotations
import os
import platform
import subprocess
from . import settings
from .log import log
_CREATE_NO_WINDOW = 134217728

def antivirus() -> 'list[str]':
    """Güvenlik Merkezi'ne kayıtlı antivirüs ürünleri (Windows Server'da yok: boş liste)."""

    try:
        done = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', 'Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction SilentlyContinue | ForEach-Object { $_.displayName }'], capture_output=True, timeout=10, creationflags=_CREATE_NO_WINDOW)
        text = done.stdout.decode('utf-8', errors='replace') if done.stdout else ''
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        return [line.strip() for line in text.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []

def lines() -> 'list[str]':
    '''TEŞHİSİ KOPYALA için Windows ve ses aygıtı satırları (jarvis/diagnostics.py).'''

    from .audio import devices
    from .audio import win_aec
    from . import win_permissions
    edition = getattr(platform, 'win32_edition', (lambda: ''))() or '?'
    arch = os.environ.get('PROCESSOR_ARCHITECTURE', platform.machine())
    try:
        pa = devices.sd.get_portaudio_version()[1]
    except Exception:
        pa = '?'
    names = win_aec.describe()
    mics = win_aec.endpoints(win_aec._CAPTURE)
    chosen = devices.selected_mic()
    chosen_name = next((m['name'] for m in mics if m['id'] == chosen), '(çıkarılmış)') if chosen else 'varsayılan'
    av = antivirus()
    return [f'Windows {platform.release()} ({platform.version()}, {edition}, {arch}) · {pa}', f'Varsayılan mikrofon: “{names.get('mic') or '?'}” (görüşme: “{names.get('mic_comm') or '?'}”)', f'Hoparlör: “{names.get('speaker') or '?'}” (görüşme: “{names.get('speaker_comm') or '?'}”)', f'Seçili mikrofon: {chosen_name} · yankı engelleme {'açık' if devices.aec_wanted() else 'kapalı'}{' (iki hatadan sonra bu açılışta kapalı)' if win_aec.disabled() else ''}{f' · son DSP hatası: {win_aec.last_error[:120]}' if win_aec.last_error else ''}', f'Windows izni: mikrofon {win_permissions.status('microphone')}, kamera {win_permissions.status('camera')} · engel: {win_permissions.blocker('microphone') or 'yok'}', 'Antivirüs: ' + (', '.join(av) if av else '(bilgi yok)'), 'Spotify: ' + _spotify(), *_bluetooth()]

def _bluetooth() -> 'list[str]':
    """Hangi ses aygıtı Bluetooth (9.4: AirPods'un mikrofonu sesi telefon kalitesine düşürüyor; önce veri)."""

    try:
        from .audio import win_aec
        rep = win_aec.audio_report()
    except Exception as exc:
        return [f'Ses aygıtı türleri: ? ({type(exc).__name__})']
    def show(items: 'list[dict]', default: 'str') -> 'str':
        return ', '.join((f'“{d['name']}” ({d['form']}{' · BLUETOOTH' if d['bt'] else ''}{' · varsayılan' if d['id'] == default else ''})' for d in items)) or 'yok'

    mic_bt = any((d['bt'] and d['id'] == rep['default_mic'] for d in rep['mic']))
    out = [f'Mikrofon türleri: {show(rep['mic'], rep['default_mic'])}', f'Hoparlör türleri: {show(rep['speaker'], rep['default_speaker'])}']
    if mic_bt:
        out.append('UYARI: varsayılan mikrofon Bluetooth; Windows kulaklığı eller serbest kipine (HFP) geçirir, ses telefon kalitesine düşer.')
    return out

def _spotify() -> 'str':
    try:
        from .actions import win_media
        return win_media.spotify_summary()
    except Exception as exc:
        return f'? ({type(exc).__name__})'

def startup_report() -> 'None':
    try:
        from .audio import devices
        from .audio import win_aec
        from . import win_permissions
        release, build = platform.release(), platform.version()
        edition = getattr(platform, 'win32_edition', (lambda: ''))() or '?'
        arch = os.environ.get('PROCESSOR_ARCHITECTURE', platform.machine())
        try:
            pa = devices.sd.get_portaudio_version()[1]
        except Exception:
            pa = '?'
        else:
            names = win_aec.describe()
            mics = win_aec.endpoints(win_aec._CAPTURE)
            chosen = devices.selected_mic()
            chosen_name = next((m['name'] for m in mics if m['id'] == chosen), '(çıkarılmış)') if chosen else 'varsayılan'
            blocker = win_permissions.blocker('microphone') or 'yok'
            log(f'teşhis: Windows {release} ({build}, {edition}, {arch}) · {pa} · mikrofon “{names.get('mic', '?')}” (görüşme: “{names.get('mic_comm', '?')}”), hoparlör “{names.get('speaker', '?')}” (görüşme: “{names.get('speaker_comm', '?')}”) · etkin giriş aygıtı {len(mics)} · izin engeli: {blocker} · yankı engelleme {'açık' if devices.aec_wanted() else 'kapalı'} · seçili mikrofon: {chosen_name} · mikrofon ayarı {'açık' if settings.get('mic_enabled', True) is not False else 'KAPALI'}')
            av = antivirus()
            if av:
                log('teşhis: antivirüs:', ', '.join(av))
                return
            None(None, '(bilgi yok)')
    except Exception as exc:
        log('teşhis günlüğü yazılamadı:', exc)

# WARNING: Decompyle incomplete

'''macOS izinleri: bir özellik izne takılınca doğru Sistem Ayarları sayfasını açar.

JARVIS izni kendisi veremez. Anahtarı açmak kullanıcıya kalır; macOS bunu bir
uygulamanın yapmasına izin vermez. Yapabildiğimiz şey:
  1. Hatanın hangi izinden kaynaklandığını anlamak (`detect`)
  2. Sistem Ayarları'nda tam o sayfayı açmak (`open_pane`)
  3. Listede hangi uygulamanın anahtarını açacağını söylemek (`explain`)

Hangi uygulama? macOS izni işlemi başlatan uygulamaya bağlar. JARVIS.app'te
bu JARVIS'in kendisidir; BASLAT.command ile açılınca "Terminal" olur, VS
Code'dan açılınca "Visual Studio Code". Takvim, anımsatıcılar ve ekran okuma
ise kendi küçük yardımcı uygulamalarıyla çalıştığı için izin onların adına
verilir.
'''

from __future__ import annotations
import ctypes
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from . import paths
from .log import log
if paths.IS_WIN:
    from . import win_permissions as _win
PANE_URL = 'x-apple.systempreferences:com.apple.preference.security?{anchor}'
REOPEN_AFTER = 45.0

@dataclass(frozen=True)
class Permission:
    label: 'str'
    anchor: 'str'
    owner: 'str' = ''

PERMISSIONS = {'accessibility': Permission('Erişilebilirlik (uygulamaları denetleme)', 'Privacy_Accessibility'), 'automation': Permission('Otomasyon', 'Privacy_Automation'), 'microphone': Permission('Mikrofon', 'Privacy_Microphone'), 'camera': Permission('Kamera', 'Privacy_Camera'), 'contacts': Permission('Kişiler', 'Privacy_Contacts'), 'files': Permission('Dosyalar ve Klasörler', 'Privacy_FilesAndFolders'), 'screen': Permission('Ekran kaydı', 'Privacy_ScreenCapture', '' if paths.FROZEN else paths.SCREEN_HELPER), 'calendar': Permission('Takvim', 'Privacy_Calendars', '' if paths.FROZEN else paths.CALENDAR_HELPER), 'reminders': Permission('Anımsatıcılar', 'Privacy_Reminders', '' if paths.FROZEN else paths.CALENDAR_HELPER)}
_PATTERNS = [('automation', re.compile('-1743|not authori[sz]ed to send apple events|otomasyon izni', re.I)), ('accessibility', re.compile('assistive access|not allowed to send keystrokes|-25211|eri[sş]ilebilirlik izni', re.I)), ('calendar', re.compile('takvim eri[sş]im izni', re.I)), ('reminders', re.compile('an[ıi]msat[ıi]c[ıi] eri[sş]im izni', re.I)), ('screen', re.compile('ekran kayd[ıi] izni', re.I)), ('camera', re.compile('kamera izni', re.I)), ('microphone', re.compile('mikrofon izni', re.I))]
_TARGET_RE = re.compile('send apple events to ([^.\\n]+?)[.\\n]', re.I)
_last_opened: 'dict[str, float]' = {}
_lock = threading.Lock()
_host: 'str | None' = None

def detect(text: 'str') -> 'str | None':
    for kind, pattern in _PATTERNS:
        if not pattern.search(text or ''):
            continue
        return kind

def host_app() -> 'str':
    '''macOS'un izinleri bağladığı uygulamanın adı (örn. "Terminal").'''

    global _host
    if _host is None:
        _host = _find_host() or 'Terminal'
    return _host

def _find_host() -> 'str | None':
    try:
        import psutil
        pid = os.getpid()
        try:
            fn = ctypes.CDLL(None).responsibility_get_pid_responsible_for_pid
            fn.restype, fn.argtypes = ctypes.c_int, [ctypes.c_int]
            pid = fn(pid) or pid
        except (AttributeError, OSError):
            pass
        else:
            for proc in [psutil.Process(pid), *psutil.Process(pid).parents()]:
                exe = proc.exe()
                if '.app/' in exe:
                    return os.path.basename(exe.split('.app/')[0])
    except Exception:
        return

def accessibility_granted() -> 'bool':
    if not paths.IS_MAC:
        return True
    try:
        lib = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except OSError:
        return True

def media_status(kind: 'str') -> 'str':
    '''Mikrofon ("audio") / kamera ("video") izni: granted | denied | unknown.'''

    if paths.IS_WIN:
        return _win.media_status(kind)
    if not paths.IS_MAC:
        return 'granted'
    try:
        import objc
        objc.loadBundle('AVFoundation', {}, bundle_path='/System/Library/Frameworks/AVFoundation.framework')
        device = objc.lookUpClass('AVCaptureDevice')
        status = device.authorizationStatusForMediaType_('soun' if kind == 'audio' else 'vide')
    except Exception:
        return 'unknown'
    return {3: 'granted', 2: 'denied', 1: 'denied'}.get(int(status), 'unknown')

def open_pane(kind: 'str') -> 'bool':
    """Sistem Ayarları'nda ilgili sayfayı açar (kısa sürede tekrar açmaz)."""

    if paths.IS_WIN:
        return _win.open_settings(kind)
    perm = PERMISSIONS.get(kind)
    if perm is None or not paths.IS_MAC:
        return False
    with _lock:
        now = time.monotonic()
        if now - _last_opened.get(kind, -REOPEN_AFTER) < REOPEN_AFTER:
            return False
        _last_opened[kind] = now
    try:
        subprocess.run(['open', PANE_URL.format(anchor=perm.anchor)], check=False, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return False
    log('izin sayfası açıldı', perm.label)
    return True

def explain(kind: 'str', detail: 'str'='') -> 'str':
    if paths.IS_WIN:
        return f'{EXPLAINED} {_win.explain(kind)}'
    perm = PERMISSIONS[kind]
    owner = perm.owner or host_app()
    if kind == 'automation':
        target = _TARGET_RE.search(detail or '')
        sub = f' altındaki “{target.group(1).strip()}”' if target else ' altındaki ilgili uygulamanın'
        step = f'listede “{owner}”{sub} anahtarını aç'
    elif kind == 'accessibility':
        step = f'listede “{owner}” anahtarını aç (listede yoksa + düğmesiyle ekle'
        if paths.FROZEN:
            step += '; açık görünüyorsa − ile kaldırıp + ile yeniden ekle'
        step += ')'
    elif perm.owner:
        step = f'listede “{owner}” anahtarını aç (listede yoksa isteği tekrarla, macOS izin soracak)'
    elif paths.FROZEN and kind == 'screen':
        step = f'listede “{owner}” anahtarını aç (açık görünüyorsa − ile kaldırıp isteği tekrarla)'
    else:
        step = f'listede “{owner}” anahtarını aç'
    tail = " Sonra JARVIS'i yeniden başlat." if kind in ('microphone', 'camera') else ' Sonra isteği tekrarla.'
    return f"{EXPLAINED} Sistem Ayarları'nda {perm.label} izni sayfasını açtım: {step}.{tail}"

EXPLAINED = 'İzin gerekiyor.'

def describe_failure(detail: 'str') -> 'str':
    '''Bir hata izinden kaynaklanıyorsa sayfayı açar ve anlaşılır açıklama döner.'''

    if EXPLAINED in (detail or '') or not paths.IS_MAC:
        return detail
    kind = detect(detail)
    if kind is None:
        return detail
    open_pane(kind)
    return explain(kind, detail)

def handle_tool_result(text: 'str') -> 'tuple[str, bool]':
    '''Araç sonucunu izin açısından elden geçirir → (metin, izin mi gerekti).'''

    if EXPLAINED in (text or ''):
        return text, True
    fixed = describe_failure(text)
    return fixed, fixed is not text

def require_accessibility() -> 'str | None':
    '''Tuş gönderen otomasyonlardan önce: izin yoksa açıklama döner (sayfa açılır).'''

    if accessibility_granted():
        return
    open_pane('accessibility')
    return explain('accessibility')

ROWS = ('microphone', 'camera', 'files', 'contacts', 'calendar', 'reminders', 'screen', 'accessibility', 'automation')
_asked: 'set[str]' = set()

def status(kind: 'str') -> 'str':
    if paths.IS_WIN:
        return _win.status(kind)
    if not paths.IS_MAC:
        return 'granted'
    try:
        if kind in ('microphone', 'camera'):
            return {'granted': 'granted', 'denied': 'denied'}.get(media_status('audio' if kind == 'microphone' else 'video'), 'ask')
        if kind == 'contacts':
            import Contacts
            value = int(Contacts.CNContactStore.authorizationStatusForEntityType_(Contacts.CNEntityTypeContacts))
            return {0: 'ask', 1: 'denied', 2: 'denied'}.get(value, 'granted')
        if kind == 'files':
            return _files_status()
        if kind in ('calendar', 'reminders'):
            import objc
            objc.loadBundle('EventKit', {}, bundle_path='/System/Library/Frameworks/EventKit.framework')
            store = objc.lookUpClass('EKEventStore')
            value = int(store.authorizationStatusForEntityType_(0 if kind == 'calendar' else 1))
            return {0: 'ask', 1: 'denied', 2: 'denied'}.get(value, 'granted')
        if kind == 'screen':
            import Quartz
            if Quartz.CGPreflightScreenCaptureAccess():
                return 'granted'
            return 'denied' if 'screen' in _asked else 'ask'
        if kind == 'accessibility':
            if accessibility_granted():
                return 'granted'
            return 'denied' if 'accessibility' in _asked else 'ask'
    except Exception as exc:
        log('izin durumu okunamadı', kind, exc)
        return 'ask'
    return 'first_use'

def statuses() -> 'dict[str, str]':
    if paths.IS_WIN:
        return _win.statuses()
    return {kind: status(kind) for kind in ROWS}

def rows() -> 'tuple[str, ...]':
    '''Bu işletim sisteminde gösterilen izin satırları (HUD bunları çizer).'''

    if paths.IS_WIN:
        return _win.ROWS
    return ROWS

def mic_problem(errors: 'list[str]') -> 'tuple[str, str, str]':
    '''Mikrofon açılamadı: (tür, rozet, açıklama). Windows'ta tür blocked | busy | none | unreachable
    (win_permissions.MIC_PROBLEMS); başka sistemlerde her zaman "none".'''

    if paths.IS_WIN:
        kind = _win.mic_problem(errors)
        badge, text = _win.MIC_PROBLEMS[kind]
        return kind, badge, text
    return ('none', 'MİKROFON YOK', 'Mikrofon bulunamadı; yazarak konuşabilirsin. Mikrofon takılınca kendiliğinden açılır.')

def open_mic_help(kind: 'str') -> 'bool':
    '''Mikrofon rozetine basıldı: engelde gizlilik sayfası, aygıt sorunlarında ses ayarları.'''

    if paths.IS_WIN:
        if kind in ('none', 'busy'):
            return _win.open_settings('sound', force=True)
        return None('microphone', force=True)
    return open_pane('microphone')

def fallback(kind: 'str', mac_text: 'str') -> 'str':
    """Çalışırken çıkan uyarının bu işletim sistemindeki metni (Mac'te aynen mac_text)."""

    if paths.IS_WIN:
        return _win.FALLBACK.get(kind, mac_text)
    return mac_text

def request(kind: 'str') -> 'str':
    """macOS'un izin sorusunu gösterir (cevabı bekler); soru daha önce sorulduysa ayar sayfasını açar."""

    if paths.IS_WIN:
        return _win.request(kind)
    if kind not in ROWS or not paths.IS_MAC:
        return status(kind)
    now = status(kind)
    if now == 'granted':
        return now
    if now == 'denied' or kind == 'automation' or kind in _asked:
        _last_opened.pop(kind, None)
        open_pane(kind)
        return now
    _asked.add(kind)
    log('izin isteniyor', kind)
    try:
        if kind in ('microphone', 'camera'):
            _request_media('soun' if kind == 'microphone' else 'vide')
        elif kind == 'contacts':
            _request_contacts()
        elif kind == 'files':
            _request_files()
        elif kind == 'calendar':
            from .actions import calendar
            calendar.request_access()
        elif kind == 'reminders':
            from .actions import reminders
            reminders.request_access()
        elif kind == 'screen':
            if not paths.FROZEN:
                open_pane(kind)
            else:
                import Quartz
                Quartz.CGRequestScreenCaptureAccess()
        elif kind == 'accessibility':
            _ax_prompt()
    except Exception as exc:
        log('izin istenemedi', kind, exc)
        open_pane(kind)
    return status(kind)

def _request_media(media: 'str') -> 'None':
    import objc
    objc.loadBundle('AVFoundation', {}, bundle_path='/System/Library/Frameworks/AVFoundation.framework')
    objc.registerMetaDataForSelector(b'AVCaptureDevice', b'requestAccessForMediaType:completionHandler:', {'arguments': {3: {'callable': {'retval': {'type': b'v'}, 'arguments': {0: {'type': b'^v'}, 1: {'type': b'Z'}}}}}})
    done = threading.Event()
    objc.lookUpClass('AVCaptureDevice').requestAccessForMediaType_completionHandler_(media, (lambda _ok: done.set()))
    done.wait(180)

def _request_contacts() -> 'None':
    import Contacts
    done = threading.Event()
    Contacts.CNContactStore.alloc().init().requestAccessForEntityType_completionHandler_(Contacts.CNEntityTypeContacts, (lambda _ok, _error: done.set()))
    done.wait(180)

FOLDERS = ('Desktop', 'Documents', 'Downloads')

def _files_status() -> 'str':
    from . import settings
    if not settings.get('files_asked'):
        return 'ask'
    home = os.path.expanduser('~')
    for name in FOLDERS:
        try:
            os.listdir(os.path.join(home, name))
        except PermissionError:
            return 'denied'
        except OSError:
            continue
    return 'granted'

def _request_files() -> 'None':
    from . import settings
    home = os.path.expanduser('~')
    for name in FOLDERS:
        try:
            os.listdir(os.path.join(home, name))
        except OSError:
            continue
    settings.save({'files_asked': True})

def _ax_prompt() -> 'None':
    '''Erişilebilirlik: macOS'un "Sistem Ayarları'nı aç" sorusu; JARVIS listeye (kapalı) eklenir.'''

    import objc
    from Foundation import NSBundle
    found = {}
    bundle = NSBundle.bundleWithPath_('/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework')
    objc.loadBundleFunctions(bundle, found, [('AXIsProcessTrustedWithOptions', b'Z@')])
    found['AXIsProcessTrustedWithOptions']({'AXTrustedCheckOptionPrompt': True})

# WARNING: Decompyle incomplete

'''Uygulama açma ve kapatma (Windows): open_app ve close_app araçları.

Açma: Başlat menüsündeki uygulamaların listesi (shell:AppsFolder: Türkçe görünen ad, başlatma kimliği, exe
hedefi) okunur, istenen ad esnek eşlenir ("Spotify'ı", "hesap makinası", "chrome"). Uygulama zaten açıksa
penceresi öne getirilir, değilse Başlat menüsündeki gibi başlatılır. Modelin yazdığı metin hiçbir zaman doğrudan
çalıştırılmaz: yalnızca listede (ya da App Paths kaydında) bulunan uygulamalar açılır.

Kapatma: uygulamanın pencerelerine "kapat" iletisi gider (pencerenin X düğmesi gibi; kaydedilmemiş belge varsa
uygulama sorar). "Zorla" denirse süreçleri sonlandırılır. JARVIS'in kendisi, onu başlatan ve onun açtığı süreçler
ve Windows bileşenleri asla kapatılmaz.
'''

from __future__ import annotations
import ctypes
import difflib
import json
import os
import re
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import psutil
from ..log import log
from .win_shell import run_powershell
INDEX_TTL = 600.0

@dataclass(frozen=True)
class StartApp:
    name: 'str'
    app_id: 'str'
    target: 'str' = ''
    @property
    def packaged(self) -> 'bool':
        return '!' in self.app_id

    @property
    def family(self) -> 'str':
        if self.packaged:
            return self.app_id.split('!')[0].lower()
        return ''


SETTINGS = StartApp('Ayarlar', 'ms-settings:')
EXPLORER = StartApp('Dosya Gezgini', 'Microsoft.Windows.Explorer', 'explorer.exe')
_CALC = ('Microsoft.WindowsCalculator_8wekyb3d8bbwe!App', 'hesap makinesi', 'calculator')
_NOTEPAD = ('Microsoft.WindowsNotepad_8wekyb3d8bbwe!App', 'not defteri', 'notepad')
_TERMINAL = ('Microsoft.WindowsTerminal_8wekyb3d8bbwe!App', 'terminal', 'windows powershell', 'komut istemi')
_OUTLOOK = ('Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows', 'outlook', 'outlook new')
_ALIASES: 'dict[str, tuple[str, ...]]' = {**dict.fromkeys(('hesap makinesi', 'hesap makinasi', 'calculator', 'calc'), _CALC), **dict.fromkeys(('not defteri', 'notepad', 'textedit'), _NOTEPAD), **dict.fromkeys(('ayarlar', 'settings', 'system settings', 'system preferences', 'sistem ayarlari', 'windows ayarlari'), ('<ayarlar>',)), **dict.fromkeys(('finder', 'dosya gezgini', 'gezgin', 'explorer', 'file explorer', 'windows gezgini'), ('<gezgin>',)), **dict.fromkeys(('gorev yoneticisi', 'task manager', 'activity monitor', 'aktivite monitoru'), ('gorev yoneticisi', 'task manager')), **dict.fromkeys(('vscode', 'vs code', 'code', 'visual studio code'), ('visual studio code',)), **dict.fromkeys(('terminal', 'iterm', 'iterm2', 'komut satiri', 'komut istemi', 'cmd', 'powershell'), _TERMINAL), **dict.fromkeys(('store', 'app store', 'magaza', 'microsoft store'), ('microsoft store',)), **dict.fromkeys(('mail', 'posta', 'e posta', 'outlook', 'calendar', 'takvim'), _OUTLOOK), **dict.fromkeys(('photos', 'fotograflar', 'preview', 'onizleme'), ('fotograflar', 'photos')), **dict.fromkeys(('notes', 'notlar', 'yapiskan notlar', 'sticky notes'), ('yapiskan notlar', 'sticky notes')), **dict.fromkeys(('music', 'muzik'), ('apple music', 'medya oynatici', 'media player', 'spotify')), **dict.fromkeys(('safari', 'tarayici', 'browser', 'internet', 'web tarayicisi'), ('<tarayici>',)), 'zoom': ('zoom workplace', 'zoom')}
_NEVER_CLOSE = {'memory compression', 'dwm', 'smss', 'csrss', 'lsass', 'ctfmon', 'sihost', 'system', 'audiodg', 'conhost', 'dllhost', 'lockapp', 'msmpeng', 'spoolsv', 'svchost', 'wininit', 'explorer', 'registry', 'services', 'winlogon', 'wudfhost', 'searchapp', 'taskhostw', 'searchhost', 'fontdrvhost', 'openconsole', 'runtimebroker', 'textinputhost', 'shellexperiencehost', 'applicationframehost', 'securityhealthservice', 'securityhealthsystray', 'startmenuexperiencehost'}
_SELF_WORDS = {'bu asistan', 'friday', 'jarvis', 'ultron', 'asistan'}
_index_lock = threading.Lock()
_index_cache: 'tuple[float, list[StartApp]]' = 0.0, []
_TR = str.maketrans('çğıöşüâîû', 'cgiosuaiu')

def _norm(text: 'str') -> 'str':
    '''Karşılaştırma için sade biçim: Türkçe küçük harf, harf eki ("Spotify'ı"), aksan ve noktalama atılır.'''

    s = (text or '').replace('İ', 'i').replace('I', 'ı').lower()
    s = re.sub("['’`´][a-zçğıöşü]{1,4}$", '', s.strip())
    s = s.translate(_TR)
    s = re.sub('\\.exe\\b|\\(r\\)|\\(tm\\)|™|®', ' ', s)
    s = re.sub('\\b(uygulamasi|uygulamasini|uygulamayi|uygulama|programi|programini|program|app)\\b', ' ', s)
    s = re.sub('[^a-z0-9+#]+', ' ', s)
    return ' '.join(s.split())

_INDEX_PS = "$a = (New-Object -ComObject Shell.Application).NameSpace('shell:AppsFolder').Items(); @($a | ForEach-Object { [pscustomobject]@{n=$_.Name; id=$_.Path; t=$_.ExtendedProperty('System.Link.TargetParsingPath')} }) | ConvertTo-Json -Compress"

def _index(refresh: 'bool'=False) -> 'list[StartApp]':
    global _index_cache
    with _index_lock:
        at, apps = _index_cache
        if apps and not refresh and time.monotonic() - at < INDEX_TTL:
            return apps
        apps = _read_apps_folder() or _read_start_menu()
        _index_cache = time.monotonic(), apps
        return apps

def _read_apps_folder() -> 'list[StartApp]':
    code, out = run_powershell(_INDEX_PS, timeout=15)
    if code != 0:
        log('uygulama listesi okunamadı', code, out[:200])
        return []
    try:
        data = json.loads(out.strip() or '[]')
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [StartApp(str(d.get('n') or ''), str(d.get('id') or ''), str(d.get('t') or '')) for d in data if d.get('n') if d.get('id')]

def _read_start_menu() -> 'list[StartApp]':
    '''Yedek: Başlat menüsü klasörlerindeki kısayollar (adlar İngilizce olabilir).'''

    roots = [Path(os.environ.get('APPDATA', '')) / 'Microsoft\\Windows\\Start Menu\\Programs', Path(os.environ.get('ProgramData', '')) / 'Microsoft\\Windows\\Start Menu\\Programs']
    return [StartApp(p.stem, '', str(p)) for root in roots if root.is_dir() for p in root.rglob('*.lnk')]

def _junk(app: 'StartApp') -> 'bool':
    '''Uygulama olmayan girdiler: web bağlantıları, belgeler, kaldırıcılar.'''

    low = app.app_id.lower()
    return low.startswith(('http://', 'https://')) or low.endswith(('.html', '.htm', '.chm', '.txt', '.url', '.pdf', '.rtf')) or bool(re.search('\\b(uninstall|unins|unistall|kaldir|readme|manual|help|yardim|website|faq)\\b', _norm(app.name)))

def _rank(app: 'StartApp') -> 'tuple':
    """Aynı adlı birden çok girdi: paketli > exe'si belli > kısa ad > 32 bit olmayan."""

    return not app.packaged, not app.target, len(app.name), 'x86' in app.name.lower() or '32' in app.name

def _ident(app: 'StartApp') -> 'str':
    '''Kimlikteki ve exe adındaki İngilizce ad ("Microsoft.WindowsCalculator" → "calculator" içerir).'''

    exe = Path(app.target).stem if app.target else ''
    return re.sub('[^a-z0-9]', '', f'{app.family or app.app_id} {exe}'.lower())

def _match(q: 'str', apps: 'list[StartApp]') -> 'StartApp | None':
    def best(found: 'list[StartApp]') -> 'StartApp | None':
        if found:
            return min(found, key=_rank)

    compact = q.replace(' ', '')
    hit = best([a for a in apps if _norm(a.name) in (q,) if _norm(a.name).replace(' ', '') == compact])
    if hit:
        return hit
    pool = [a for a in apps if not _junk(a)]
    if len(compact) >= 5:
        hit = best([a for a in pool if compact in _ident(a)])
        if hit:
            return hit
    word = re.compile(f'\\b{re.escape(q)}\\b')
    hit = best([a for a in pool if word.search(_norm(a.name))])
    if hit:
        return hit
    if len(q) >= 4:
        hit = best([a for a in pool if _norm(a.name).startswith(q)])
        if hit:
            return hit
    names = {_norm(a.name): a for a in sorted(pool, key=_rank, reverse=True)}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.78)
    if close:
        return names[close[0]]

def _candidate(cand: 'str', apps: 'list[StartApp]') -> 'StartApp | None':
    if cand == '<ayarlar>':
        return SETTINGS
    if cand == '<gezgin>':
        return next((a for a in apps if a.app_id == EXPLORER.app_id), EXPLORER)
    if cand == '<tarayici>':
        browser = _default_browser()
        if browser:
            return _match(_norm(browser), apps)
        return
    if '!' in cand:
        return next((a for a in apps if a.app_id.lower() == cand.lower()), None)
    return next((a for a in sorted(apps, key=_rank) if _norm(a.name) == cand), None)

def find_app(name: 'str') -> 'StartApp | None':
    q = _norm(name)
    if not q:
        return
    apps = _index()
    for cand in _ALIASES.get(q, ()):
        hit = _candidate(cand, apps)
        if not hit:
            continue
        return hit
    hit = _match(q, apps)
    if hit is None and time.monotonic() - _index_cache[0] > 5:
        hit = _match(q, _index(refresh=True))
    return hit

def _default_browser() -> 'str':
    '''Varsayılan tarayıcının adı ("Google Chrome"). UserChoice kaydı yeni Windows'ta eski değeri gösterebiliyor.'''

    shlwapi = ctypes.WinDLL('shlwapi')
    size = wintypes.DWORD(260)
    buf = ctypes.create_unicode_buffer(260)
    hr = shlwapi.AssocQueryStringW(4096, 4, 'https', None, buf, ctypes.byref(size))
    if hr == 0:
        return buf.value
    return ''

def _app_path(name: 'str') -> 'str | None':
    '''Başlat menüsünde olmayan ama App Paths'e kayıtlı program ("chrome" → chrome.exe).'''

    exe = re.sub('[^a-z0-9._-]', '', _norm(name).replace(' ', '')) + '.exe'
    for hive in winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE:
        try:
            with winreg.OpenKey(hive, f'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe}') as key:
                path = str(winreg.QueryValue(key, None) or '').strip('"')
            if path and os.path.isfile(path):
                return path
        except OSError:
            continue

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_dwm = ctypes.WinDLL('dwmapi')
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
for _fn in ('IsWindowVisible', 'IsWindow', 'IsIconic', 'SetForegroundWindow', 'GetWindowTextLengthW'):
    getattr(_user32, _fn).argtypes = [wintypes.HWND]
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetApplicationUserModelId.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_uint32), wintypes.LPWSTR]

def _class(hwnd: 'int') -> 'str':
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _pid(hwnd: 'int') -> 'int':
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

def _app_windows() -> 'list[tuple[int, int, str]]':
    """Alt+Tab'da görünen pencereler: (hwnd, pid, sınıf). Mağaza uygulamalarında pid, çerçevenin (ApplicationFrameHost)
    değil içindeki asıl uygulamanın."""

    found = []
    def each(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, 4):
            return True
        if _user32.GetWindowLongW(hwnd, -20) & 128 or not _user32.GetWindowTextLengthW(hwnd):
            return True
        cloaked = ctypes.c_int(0)
        _dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True
        cls, pid = _class(hwnd), _pid(hwnd)
        if cls == 'ApplicationFrameWindow':
            core = _user32.FindWindowExW(hwnd, None, 'Windows.UI.Core.CoreWindow', None)
            if core:
                pid = _pid(core)
        found.append((hwnd, pid, cls))
        return True

    _user32.EnumWindows(_WNDENUMPROC(each), 0)
    return found

def _family(pid: 'int') -> 'str':
    '''Mağaza uygulamasının paket ailesi (küçük harf); paketli değilse boş.'''

    handle = _kernel32.OpenProcess(4096, False, pid)
    if not handle:
        return ''
    try:
        size = ctypes.c_uint32(512)
        buf = ctypes.create_unicode_buffer(512)
        if _kernel32.GetApplicationUserModelId(handle, ctypes.byref(size), buf) != 0:
            _kernel32.CloseHandle(handle)
            return ''
    finally:
        _kernel32.CloseHandle(handle)
    try:
        return buf.value.split('!')[0].lower()
    finally:
        _kernel32.CloseHandle(handle)

def _exe(pid: 'int') -> 'str':
    try:
        return os.path.normcase(psutil.Process(pid).exe())
    except (psutil.Error, OSError):
        return ''

def _owns(app: 'StartApp', pid: 'int') -> 'bool':
    if app.packaged:
        return _family(pid) == app.family
    return bool(app.target) and _exe(pid) == os.path.normcase(os.path.normpath(app.target))

def _front(hwnd: 'int') -> 'None':
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, 9)
    _user32.SetForegroundWindow(hwnd)
    if _user32.GetForegroundWindow() != hwnd:
        fg = _user32.GetForegroundWindow()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = _kernel32.GetCurrentThreadId()
        if fg_thread and fg_thread != me and _user32.AttachThreadInput(me, fg_thread, True):
            try:
                _user32.BringWindowToTop(hwnd)
                _user32.SetForegroundWindow(hwnd)
            finally:
                _user32.AttachThreadInput(me, fg_thread, False)
    if _user32.GetForegroundWindow() != hwnd:
        _user32.SwitchToThisWindow(hwnd, True)

_OWN_HELPERS = {'msedgewebview2.exe'}
_OWN_HELPERS.add('cloudflared.exe')

def _protected() -> 'set[int]':
    """JARVIS'in kendisi, onu başlatanlar (konsol, BASLAT.bat) ve kendi yardımcı süreçleri."""

    me = psutil.Process()
    pids = {me.pid}
    try:
        pass
    except psutil.Error:
        return pids
    try:
        pids |= {p.pid for p in me.parents()}
    except psutil.Error:
        return pids
    try:
        pids |= {p.pid for p in me.children(recursive=True) if (p.name() or '').lower() in _OWN_HELPERS}
    except psutil.Error:
        pass
    return pids

def open_app(app_name: 'str') -> 'str':
    name = (app_name or '').strip()
    if not name:
        return 'Uygulama adı belirtilmedi.'
    app = find_app(name)
    if app is None:
        exe = _app_path(name)
        if exe:
            try:
                os.startfile(exe)
            except OSError as exc:
                return f"'{name}' açılamadı: {exc}"
            return f'{Path(exe).stem} açıldı.'
        return f"'{name}' bulunamadı veya açılamadı."
    if app is SETTINGS:
        os.startfile('ms-settings:')
        return 'Ayarlar açıldı.'
    for hwnd, pid, cls in _app_windows():
        if app.app_id == EXPLORER.app_id:
            if cls == 'CabinetWClass':
                pass
        elif _owns(app, pid):
            _front(hwnd)
            return f'{app.name} öne getirildi.'
    try:
        if '://' in app.app_id:
            os.startfile(app.app_id)
        elif app.app_id:
            os.startfile('shell:AppsFolder\\' + app.app_id)
        else:
            os.startfile(app.target)
    except OSError as exc:
        return f'{app.name} açılamadı: {exc}'
    return f'{app.name} açıldı.'

def close_app(app_name: 'str', force: 'bool'=False) -> 'str':
    name = (app_name or '').strip()
    if not name:
        return 'Kapatılacak uygulamanın adı belirtilmedi.'
    q = _norm(name)
    if q in _SELF_WORDS:
        return 'Bu asistanın kendisi; kapatmak için quit_app aracını kullan.'
    app = find_app(name)
    protected = _protected()
    if app is not None:
        if any((_owns(app, pid) for pid in protected)):
            return 'Bu asistanın kendisi; kapatmak için quit_app aracını kullan.'
    windows = _app_windows()
    if app is not None:
        if app.app_id == EXPLORER.app_id:
            folders = [h for h, _pid, cls in windows if cls == 'CabinetWClass']
            for h in folders:
                _user32.PostMessageW(h, 16, 0, 0)
            return 'Dosya Gezgini pencereleri kapatıldı.' if folders else 'Açık Dosya Gezgini penceresi yok.'
    label = app.name if app else name
    procs = _matching(app, q, protected, {pid for _h, pid, _c in windows})
    if procs is None:
        return f'{label} bir sistem bileşeni; kapatmıyorum.'
    if not procs:
        return f'{label} şu anda açık değil.'
    pids = {p.pid for p in procs}
    if force:
        return _terminate(label, procs)
    targets = [h for h, pid, _c in windows if pid in pids]
    if not targets:
        return f'{label} arka planda çalışıyor (penceresi yok); tamamen kapatmak için zorla kapat de.'
    for h in targets:
        if _user32.PostMessageW(h, 16, 0, 0):
            continue
        if ctypes.get_last_error() == 5:
            return f'{label} yönetici yetkisiyle çalışıyor; kapatılamadı.'
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and any((_user32.IsWindow(h) and _user32.IsWindowVisible(h) for h in targets)):
        time.sleep(0.15)
    if any((_user32.IsWindow(h) and _user32.IsWindowVisible(h) for h in targets)):
        return f'{label} kapanmadı; kaydedilmemiş bir belge için soru soruyor olabilir.'
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and any((psutil.pid_exists(p) for p in pids)):
        time.sleep(0.2)
    if any((psutil.pid_exists(p) for p in pids)):
        return f'{label} penceresi kapandı ama arka planda (bildirim alanında) çalışmaya devam ediyor; tamamen kapatmak için zorla kapat de.'
    return f'{label} kapatıldı.'

def _matching(app: 'StartApp | None', q: 'str', protected: 'set[int]', windowed: 'set[int]') -> 'list[psutil.Process] | None':
    '''Kapatılacak süreçler. Eşleşenlerin hepsi Windows bileşeniyse None.'''

    procs = [p for p in psutil.process_iter(['pid', 'name']) if p.pid not in protected if p.pid]
    stem = {p.pid: _norm((p.info['name'] or '').removesuffix('.exe').removesuffix('.EXE')) for p in procs}
    found = []
    if app is not None:
        found = [p for p in procs if _owns(app, p.pid)]
        if not found:
            keys = {_norm(app.name), _norm(Path(app.target).stem) if app.target else ''} - {''}
            found = [p for p in procs if stem[p.pid] in keys]
    if not found:
        found = [p for p in procs if stem[p.pid] == q]
    if not found:
        if len(q) >= 3:
            found = [p for p in procs if p.pid in windowed if q in stem[p.pid]]
    safe = [p for p in found if (p.info['name'] or '').lower().removesuffix('.exe') not in _NEVER_CLOSE]
    if found and not safe:
        return
    return safe

def _terminate(label: 'str', procs: 'list[psutil.Process]') -> 'str':
    try:
        pass
    except psutil.Error:
        family = set(procs)
    try:
        family = {c for p in procs for c in p.children(recursive=True)} | set(procs)
    except psutil.Error:
        family = set(procs)
    denied = False
    for p in family:
        try:
            p.terminate()
        except psutil.AccessDenied:
            denied = True
            continue
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(list(family), timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.AccessDenied:
            denied = True
            continue
        except psutil.Error:
            continue
    if denied:
        if any((p.is_running() for p in procs)):
            return f'{label} yönetici yetkisiyle çalışıyor; kapatılamadı.'
    return f'{label} zorla kapatıldı.'


"""Windows penceresi: siyah başlık çubuğu, simge, görev çubuğu kimliği, tek örnek, konsolsuz çalışma.

Mac'teki karşılıkları window.py › _style_native (siyah başlık) ve branding.py (Dock adı ve simgesi).
Yalnızca Windows'ta içe aktarılır. En üstte webview ya da clr içe aktarılmaz: attach_streams()
pywebview'dan önce çağrılıyor (jarvis/__main__.py).

Başlık rengi: pywebview (winforms) başlığı sistemin temasına göre boyuyor (koyu temada gri, açık
temada beyaz) ve tema değişince yeniden yazıyor. Onun yöntemini (BrowserForm.update_title_bar_theme)
sınıf düzeyinde bizimkiyle değiştiriyoruz; böylece hem ilk boyamada hem tema değişiminde başlık siyah.
"""

from __future__ import annotations
import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from .. import paths
from ..log import log
BUILD = sys.getwindowsversion().build
HIDE_CAPTION = True
BLACK, INK, FRAME = 0, 16247247, 5456940
ICO = paths.DATA_DIR / 'icon-1.ico'
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
TAG = 'JARVIS.V4.' + hashlib.sha1(str(paths.DATA_DIR).lower().encode('utf-8')).hexdigest()[:12]
CONSOLE_LOG = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / paths.APP_NAME / ('konsol.log' if not os.environ.get('JARVIS_DATA_DIR') else f'konsol-{TAG[-12:]}.log')
WAIT_OTHER = 15.0
_dwm = ctypes.WinDLL('dwmapi')
_dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_dwm.DwmSetWindowAttribute.restype = ctypes.c_long
_uxtheme = ctypes.WinDLL('uxtheme')
_uxtheme.SetWindowThemeAttribute.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_uxtheme.SetWindowThemeAttribute.restype = ctypes.c_long
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
_user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
_user32.GetPropW.restype = wintypes.HANDLE
_user32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
_user32.RemovePropW.restype = wintypes.HANDLE
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
for _name in ('IsIconic', 'IsWindowVisible', 'SetForegroundWindow'):
    getattr(_user32, _name).argtypes = [wintypes.HWND]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_mutex = None
_running = None
RUNNING_MUTEX = 'JARVIS.V4.Calisiyor'

class _HighContrast(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwFlags', wintypes.DWORD), ('lpszDefaultScheme', wintypes.LPWSTR)]

class _WtaOptions(ctypes.Structure):
    _fields_ = [('dwFlags', wintypes.DWORD), ('dwMask', wintypes.DWORD)]

def attach_streams() -> 'None':
    """pythonw ya da paket: konsol yok (sys.stderr None). Çıktılar CONSOLE_LOG'a gider; iş parçacığı
    hataları ve pywebview günlükleri kaybolmaz. Dosya her açılışta sıfırlanır (single_instance'tan sonra
    çağrılmalı: ikinci açılış çalışan JARVIS'in dosyasına dokunmasın)."""

    try:
        CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        stream = open(CONSOLE_LOG, 'w', encoding='utf-8', errors='backslashreplace', buffering=1)
    except OSError:
        stream = open(os.devnull, 'w', encoding='utf-8')
    sys.stdout = sys.stderr = stream

def fatal() -> 'None':
    '''Açılışta yakalanmamış hata: konsol olmayabilir, kullanıcı bir kutu görür; ayrıntı günlükte.'''

    log('açılış hatası:\n' + traceback.format_exc())
    _user32.MessageBoxW(None, 'JARVIS açılamadı.\n\nAyrıntılar veri klasöründeki jarvis.log dosyasında (%APPDATA%\\JARVIS V4).', 'JARVIS', 65552)

def single_instance() -> 'bool':
    '''Bu veri klasörüyle açık bir JARVIS varsa onun penceresini öne getirir ve False döner.

    Kilit, sahibi olan ana iş parçacığıyla yaşar; süreç kapanınca (os._exit) serbest kalır. Öteki JARVIS
    kapanıyorsa (veda sesi, penceresi gizlenmiş) bu açılış onun bitmesini bekleyip devam eder; henüz
    açılıyorsa penceresi görününce onu öne getirir.'''

    global _running, _mutex
    _running = _kernel32.CreateMutexW(None, False, RUNNING_MUTEX)
    _mutex = _kernel32.CreateMutexW(None, True, 'Local\\' + TAG)
    if not _mutex or ctypes.get_last_error() != 183:
        return True
    deadline = time.monotonic() + WAIT_OTHER
    while time.monotonic() < deadline:
        hwnd = _other_window()
        if hwnd:
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, 9)
            _user32.SetForegroundWindow(hwnd)
            return False
        if _kernel32.WaitForSingleObject(_mutex, 250) in (0, 128):
            return True
    return False

def relaunch() -> 'None':
    '''Bu süreç kapanınca JARVIS yeniden açılsın (EN BAŞTAN BAŞLA). Yeni süreç kilidin serbest kalmasını
    bekler (single_instance); bu yüzden önce kapanış başlamış olmalı (closing: pencere işareti kalktı).'''

    if paths.FROZEN:
        cmd = [sys.executable]
    else:
        cmd = [str(Path(sys.executable).with_name('pythonw.exe')), '-m', 'jarvis']
    try:
        subprocess.Popen(cmd, cwd=None if paths.FROZEN else str(paths.PACKAGE_DIR.parent), close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return
    except OSError as exc:
        log('JARVIS yeniden açılamadı', exc)

def closing(window) -> 'None':
    '''Kapanış başladı: pencerenin işareti kalkar. Veda sesi sürerken yapılan yeniden açılış bu pencereyi
    "açık JARVIS" sayıp çıkmasın; kilidin serbest kalmasını (süreç bitince) bekleyip açılsın.'''

    try:
        _user32.RemovePropW(window.native.Handle.ToInt64(), TAG)
        return
    except Exception as exc:
        log('pencere işareti kaldırılamadı', exc)

def _other_window() -> 'int | None':
    """Öteki JARVIS'in görünür penceresi (TAG işaretli)."""

    found = []
    def each(hwnd, _lparam):
        if _user32.GetPropW(hwnd, TAG) and _user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_WNDENUMPROC(each), 0)
    if found:
        return found[0]

def prepare() -> 'None':
    '''branding.apply'dan, pencere oluşmadan önce: görev çubuğu kimliği ve simge dosyası.
    Kimlik sayesinde JARVIS görev çubuğunda "Python" grubuna karışmaz, kendi simgesiyle durur.'''

    try:
        fn = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        fn.argtypes, fn.restype = [wintypes.LPCWSTR], ctypes.c_long
        hr = fn(paths.WIN_APP_ID) & 4294967295
        if hr:
            log(f'görev çubuğu kimliği ayarlanamadı (0x{hr:08X})')
    except (OSError, AttributeError) as exc:
        log('görev çubuğu kimliği ayarlanamadı', exc)
    ensure_icon()
    try:
        import keyring
        log('anahtar deposu:', type(keyring.get_keyring()).__name__)
    except Exception as exc:
        log('anahtar deposu yok:', exc)

def ensure_icon() -> 'str | None':
    if not ICO.exists():
        try:
            paths.ensure_dirs()
            write_ico(ICO)
        except Exception as exc:
            log('simge yazılamadı', exc)
        return str(ICO)
    return str(ICO)

def icon_path() -> 'str | None':
    if ICO.exists():
        return str(ICO)

def write_ico(path: 'Path') -> 'None':
    """Çok boyutlu .ico. Büyük boyutlar branding.render_icon'dan küçültülür; 40 px ve altında halkalar
    sönükleşip kayboluyordu, onlar için sade bir çizim yapılır. W4'te JARVIS.ico da bununla üretilir.
    Kareler BMP: PNG kareli .ico'da .NET'in Icon.ToBitmap'i büyük boyutlarda hata veriyor."""

    from PIL import Image
    from .branding import render_icon
    big = render_icon(1024)
    frames = {s: _small(s) if s <= 40 else big.resize((s, s), Image.Resampling.LANCZOS) for s in ICO_SIZES}
    tmp = path.with_suffix('.tmp')
    frames[256].save(tmp, format='ICO', sizes=[(s, s) for s in ICO_SIZES], append_images=[frames[s] for s in ICO_SIZES if s != 256], bitmap_format='bmp')
    tmp.replace(path)

def _small(size: 'int', ss: 'int'=8):
    '''Küçük boyut için sade halka: tek kalın halka, çekirdek ve beyaz nokta; 8 kat büyük çizilip küçültülür.'''

    from PIL import Image, ImageDraw
    n = size * ss
    c = n / 2
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    def circle(r: 'float', **kw) -> 'None':
        draw.ellipse(c - r, c - r, c + r, c + r, **kw)

    draw.rounded_rectangle((n * 0.04, n * 0.04, n * 0.96, n * 0.96), radius=n * 0.22, fill=(4, 8, 12, 255))
    circle(n * 0.33, outline=(94, 216, 255, 255), width=max(1, round(n * 0.075)))
    circle(n * 0.15, fill=(94, 216, 255, 255))
    circle(n * 0.06, fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.Resampling.LANCZOS)

def install(window) -> 'None':
    """Hud.__init__'ten: pencere görünmeden önce biçimlensin (ilk boyama siyah, yanıp sönme yok)."""

    window.events.before_show += _before_show

def _before_show(window) -> 'None':
    try:
        form = window.native
        cls = type(form)
        if hasattr(cls, 'update_title_bar_theme'):
            cls.update_title_bar_theme = _update_title_bar_theme
        else:
            log("pencere: pywebview'de update_title_bar_theme yok; tema değişince başlık rengi geri dönebilir")
        _style(form.Handle.ToInt64())
        log(f'pencere: siyah başlık (Windows derleme {BUILD})')
    except Exception as exc:
        log('pencere biçimlenemedi', exc)
    try:
        window.native.FormClosing += _on_form_closing
    except Exception as exc:
        log('kapanış kancası eklenemedi', exc)

def _on_form_closing(_sender, args) -> 'None':
    '''Windows kapanıyor ya da kurulum sihirbazı (Restart Manager) JARVIS'i kapatmak istiyor: veda için kapanışı
    ertelemeyiz (Hud._closing ertelerdi), yoksa Windows "JARVIS kapanmayı engelliyor" der, sihirbaz takılır.'''

    if str(args.CloseReason) in ('WindowsShutDown', 'TaskManagerClosing'):
        args.Cancel = False

def _update_title_bar_theme(self) -> 'None':
    """pywebview'in kendi çağrı yerleri (form açılışı ve sistem teması değişimi) buraya gelir."""

    if getattr(self, 'is_fullscreen', False):
        return
    try:
        _style(self.Handle.ToInt64())
        return
    except Exception as exc:
        log('pencere biçimlenemedi', exc)

def is_fullscreen(window) -> 'bool':
    if window.native is not None:
        return bool(getattr(window.native, 'is_fullscreen', False))
    return False

def is_maximized(window) -> 'bool':
    try:
        return bool(_user32.IsZoomed(window.native.Handle.ToInt64()))
    except Exception:
        return False

def maximize(window) -> 'None':
    '''Tam ekrandan çıkınca pencere önceki gibi ekranı kaplasın (pywebview "Normal" boyuta döndürüyor).'''

    try:
        _user32.ShowWindow(window.native.Handle.ToInt64(), 3)
        return
    except Exception as exc:
        log('pencere büyütülemedi', exc)

def restyle(window) -> 'None':
    '''Tam ekrandan çıkınca: pywebview kenar rengini varsayılana döndürüyor.'''

    try:
        form = window.native
        if form is not None:
            if not getattr(form, 'is_fullscreen', False):
                _style(form.Handle.ToInt64())
                return
            return
    except Exception as exc:
        log('pencere biçimlenemedi', exc)

def _set(hwnd: 'int', attr: 'int', value: 'int') -> 'None':
    v = wintypes.DWORD(value)
    _dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

def _high_contrast() -> 'bool':
    hc = _HighContrast(ctypes.sizeof(_HighContrast), 0, None)
    ok = _user32.SystemParametersInfoW(66, ctypes.sizeof(hc), ctypes.byref(hc), 0)
    return bool(ok) and bool(hc.dwFlags & 1)

def _style(hwnd: 'int') -> 'None':
    """Sistem teması ne olursa olsun siyah başlık, beyaz düğmeler. Windows 10'da (22000 altı) renk
    seçilemez: yalnızca koyu gri başlık. Yüksek karşıtlık modunda erişilebilirlik renklerine dokunulmaz."""

    _user32.SetPropW(hwnd, TAG, 1)
    if _high_contrast():
        return
    if BUILD >= 18985:
        _set(hwnd, 20, 1)
    elif BUILD >= 17763:
        _set(hwnd, 19, 1)
    if BUILD >= 22000:
        _set(hwnd, 35, BLACK)
        _set(hwnd, 36, INK)
        _set(hwnd, 34, FRAME)
    if BUILD >= 22621:
        _set(hwnd, 38, 1)
    if HIDE_CAPTION:
        opts = _WtaOptions(3, 3)
        _uxtheme.SetWindowThemeAttribute(hwnd, 1, ctypes.byref(opts), ctypes.sizeof(opts))

def set_clipboard(text: 'str') -> 'bool':
    """Panoya yazı (CF_UNICODETEXT). clip.exe'ye gerek yok: konsolsuz pakette alt süreç sessizce düşebiliyordu."""

    user32, kernel32 = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    data = text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-16-le') + b'\x00\x00'
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(2, len(data))
        if not handle:
            user32.CloseClipboard()
            return False
    finally:
        user32.CloseClipboard()
    try:
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            user32.CloseClipboard()
            return False
    finally:
        user32.CloseClipboard()
    try:
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):
            kernel32.GlobalFree(handle)
            user32.CloseClipboard()
            return False
    finally:
        user32.CloseClipboard()
    return True


"""Ekranı görme (Windows): analyze_screen için etkin pencerenin görüntüsü.

Mac'te bunu Swift yardımcısı yapıyor (screen_vision.py); Windows'ta ctypes yeter. JARVIS öndeyse (kullanıcı ona
konuşurken çoğu zaman öyle) arkasındaki ilk gerçek uygulama penceresi alınır. Görüntü PrintWindow
(PW_RENDERFULLCONTENT) ile alınır: önünde başka pencere olsa da içeriği gelir (Chrome, WebView2, DirectX
pencereleri dahil). Simge durumuna küçültülmüş pencere çizilemez, atlanır. Görüntü araç yanıtının ekinde
konuşan modele gider (Mac'teki ayrı Gemini görüntü isteği yok). Windows'ta ekran kaydı izni yok.
"""

from __future__ import annotations
import ctypes
import os
from ctypes import wintypes
from pathlib import Path
import psutil
from ..log import log
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_gdi32 = ctypes.WinDLL('gdi32')
_dwm = ctypes.WinDLL('dwmapi')
_version = ctypes.WinDLL('version')
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetTopWindow.argtypes = [wintypes.HWND]
_user32.GetTopWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
_user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
_user32.SendMessageTimeoutW.restype = wintypes.LPARAM
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
_GW_OWNER, _GW_HWNDNEXT, _GA_ROOTOWNER = 4, 2, 3
_GWL_EXSTYLE, _WS_EX_TOOLWINDOW, _WS_EX_APPWINDOW, _WS_EX_NOACTIVATE = -20, 128, 262144, 134217728
_DWMWA_EXTENDED_FRAME_BOUNDS, _DWMWA_CLOAKED = 9, 14
_PW_RENDERFULLCONTENT = 2
_PER_MONITOR_V2 = ctypes.c_void_p(-4)
_SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}
_MIN_SIDE = 60

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD), ('bmiColors', wintypes.DWORD * 3)]

def _text(hwnd) -> 'str':
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value

def _class(hwnd) -> 'str':
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _pid(hwnd) -> 'int':
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

def _frame(hwnd) -> 'wintypes.RECT':
    """Pencerenin görünen sınırı (Windows 10/11'deki görünmez kenarlıklar hariç)."""

    rect = wintypes.RECT()
    if _dwm.DwmGetWindowAttribute(hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)):
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect

def _cloaked(hwnd) -> 'bool':
    '''Gizlenmiş pencere (başka sanal masaüstü, askıya alınmış Mağaza uygulaması).'''

    value = wintypes.DWORD()
    _dwm.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return bool(value.value)

def _ours(hwnd) -> 'bool':
    return _pid(hwnd) == os.getpid()

def _usable(hwnd, foreground: 'bool'=False) -> 'bool':
    """Alt+Tab'da görünen türden bir uygulama penceresi mi (öndeki pencerede iletişim kutusu da olur)."""

    if not hwnd or not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd) or _cloaked(hwnd):
        return False
    if _class(hwnd) in _SHELL_CLASSES:
        return False
    ex = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    if not foreground:
        if ex & _WS_EX_NOACTIVATE or ex & _WS_EX_TOOLWINDOW and not ex & _WS_EX_APPWINDOW:
            return False
        if not _text(hwnd):
            return False
        root = _user32.GetAncestor(hwnd, _GA_ROOTOWNER)
        if root and root != hwnd:
            if _ours(root) or not _usable(root):
                return False
    r = _frame(hwnd)
    return r.right - r.left >= _MIN_SIDE and r.bottom - r.top >= _MIN_SIDE

def target_window() -> 'int | None':
    """Öndeki pencere; o JARVIS'se Z sırasında arkasındaki ilk uygulama penceresi."""

    fg = _user32.GetForegroundWindow()
    if fg and not _ours(fg):
        if _usable(fg, foreground=True):
            return fg
    hwnd = _user32.GetTopWindow(None)
    while hwnd:
        if not _ours(hwnd) and _usable(hwnd):
            return hwnd
        hwnd = _user32.GetWindow(hwnd, _GW_HWNDNEXT)

def _describe(exe: 'str') -> 'str':
    '''Uygulamanın görünen adı (exe'nin "Dosya açıklaması": "Google Chrome", "Not Defteri").'''

    size = _version.GetFileVersionInfoSizeW(exe, None)
    if not size:
        return ''
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(exe, 0, size, buf):
        return ''
    ptr, n = ctypes.c_void_p(), wintypes.UINT()
    if not _version.VerQueryValueW(buf, '\\VarFileInfo\\Translation', ctypes.byref(ptr), ctypes.byref(n)) or n.value < 4:
        return ''
    lang, page = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
    key = f'\\StringFileInfo\\{lang:04x}{page:04x}\\FileDescription'
    if not _version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(n)) or not n.value:
        return ''
    return ctypes.wstring_at(ptr.value).strip()

def app_name(hwnd) -> 'str':
    title = _text(hwnd)
    try:
        proc = psutil.Process(_pid(hwnd))
        exe = proc.exe()
    except psutil.Error:
        return ''
    if Path(exe).name.lower() == 'applicationframehost.exe':
        inner = _user32.FindWindowExW(hwnd, None, 'Windows.UI.Core.CoreWindow', None)
        try:
            exe = psutil.Process(_pid(inner)).exe() if inner else exe
        except psutil.Error:
            pass
        if not inner:
            return title
    return _describe(exe) or Path(exe).stem

def responsive(hwnd) -> 'bool':
    '''Pencere iletilere cevap veriyor mu (donmuş uygulamada PrintWindow süresiz bekler).'''

    result = ctypes.c_size_t()
    return bool(_user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 1500, ctypes.byref(result)))

def grab(hwnd):
    '''Pencerenin görüntüsü (PIL, RGB) ya da None. Önünde başka pencere olsa da içeriği gelir.'''

    from PIL import Image
    old = _user32.SetThreadDpiAwarenessContext(_PER_MONITOR_V2)
    screen = memdc = bmp = None
    try:
        win, vis = wintypes.RECT(), _frame(hwnd)
        _user32.GetWindowRect(hwnd, ctypes.byref(win))
        w, h = win.right - win.left, win.bottom - win.top
        if w < _MIN_SIDE or h < _MIN_SIDE:
            if bmp:
                _gdi32.DeleteObject(bmp)
            if memdc:
                _gdi32.DeleteDC(memdc)
            if screen:
                _user32.ReleaseDC(None, screen)
            _user32.SetThreadDpiAwarenessContext(old)
            return
    finally:
        if bmp:
            _gdi32.DeleteObject(bmp)
        if memdc:
            _gdi32.DeleteDC(memdc)
        if screen:
            _user32.ReleaseDC(None, screen)
        _user32.SetThreadDpiAwarenessContext(old)
    try:
        screen = _user32.GetDC(None)
        memdc = _gdi32.CreateCompatibleDC(screen)
        bmp = _gdi32.CreateCompatibleBitmap(screen, w, h)
        prev = _gdi32.SelectObject(memdc, bmp)
        drawn = _user32.PrintWindow(hwnd, memdc, _PW_RENDERFULLCONTENT)
        _gdi32.SelectObject(memdc, prev)
        if not drawn:
            if bmp:
                _gdi32.DeleteObject(bmp)
            if memdc:
                _gdi32.DeleteDC(memdc)
            if screen:
                _user32.ReleaseDC(None, screen)
            _user32.SetThreadDpiAwarenessContext(old)
            return
    finally:
        if bmp:
            _gdi32.DeleteObject(bmp)
        if memdc:
            _gdi32.DeleteDC(memdc)
        if screen:
            _user32.ReleaseDC(None, screen)
        _user32.SetThreadDpiAwarenessContext(old)
    try:
        info = BITMAPINFO(biSize=40, biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        if _gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(info), 0) != h:
            if bmp:
                _gdi32.DeleteObject(bmp)
            if memdc:
                _gdi32.DeleteDC(memdc)
            if screen:
                _user32.ReleaseDC(None, screen)
            _user32.SetThreadDpiAwarenessContext(old)
            return
    finally:
        if bmp:
            _gdi32.DeleteObject(bmp)
        if memdc:
            _gdi32.DeleteDC(memdc)
        if screen:
            _user32.ReleaseDC(None, screen)
        _user32.SetThreadDpiAwarenessContext(old)
    try:
        img = Image.frombuffer('RGB', (w, h), buf.raw, 'raw', 'BGRX', 0, 1)
        box = max(0, vis.left - win.left), max(0, vis.top - win.top), min(w, vis.right - win.left), min(h, vis.bottom - win.top)
    finally:
        if bmp:
            _gdi32.DeleteObject(bmp)
        if memdc:
            _gdi32.DeleteDC(memdc)
        if screen:
            _user32.ReleaseDC(None, screen)
        _user32.SetThreadDpiAwarenessContext(old)
    return img.crop(box) if box[2] - box[0] >= _MIN_SIDE and box[3] - box[1] >= _MIN_SIDE else img.copy()

def capture() -> 'tuple[object, str, str] | str':
    '''(görüntü, uygulama adı, pencere başlığı) ya da kullanıcıya söylenecek hata.'''

    hwnd = target_window()
    if not hwnd:
        return 'Görüntüsü alınacak açık bir pencere yok (hepsi simge durumunda olabilir).'
    owner, title = app_name(hwnd), _text(hwnd)
    if not responsive(hwnd):
        return f'{owner or title or 'Pencere'} yanıt vermiyor (donmuş); görüntüsü alınamadı.'
    img = grab(hwnd)
    if img is None:
        return f'{owner or title or 'Pencere'} penceresinin görüntüsü alınamadı.'
    log(f'ekran: {owner} / {title} ({img.width}×{img.height})')
    return img, owner, title

def analyze_screen(query: 'str', target: 'str'='active_window') -> 'tuple[str, list[bytes]]':
    """(modele giden metin, görseller). Mac'ten farklı olarak görüntü ayrı bir Gemini isteğine gitmez: araç
    yanıtının ekinde konuşan modele gider (read_file'ın fotoğraflarla yaptığı gibi). Ayrı istek yavaştı: ilk
    denemede 30 sn'lik araç sınırını aştı. Ek istek, ek kota ve ikinci bir bekleme yok."""

    from PIL import ImageStat
    from ..attachments import _jpeg
    if (target or 'active_window').strip().lower() != 'active_window':
        return 'Ekran analizi şimdilik yalnızca etkin pencereyi destekliyor.', []
    found = capture()
    if isinstance(found, str):
        return found, []
    img, owner, title = found
    stat = ImageStat.Stat(img)
    if max((high for _low, high in stat.extrema)) <= 8 or sum(stat.mean) / 3 <= 3:
        return "Hata: pencerenin görüntüsü siyah geldi. Korumalı içerik olabilir (DRM'li video, bazı oyunlar ya da şifre alanları); başka bir pencereyle dene.", []
    label = ' / '.join((part for part in (owner, title) if part)) or 'pencere'
    return f'[Etkin pencere: {label}] Bu pencerenin ekran görüntüsü bu yanıtın ekinde. Ona bakarak kullanıcının sorusunu doğrudan cevapla; görünen yazıları, uyarıları ve düğmeleri oku. Emin olmadığın yeri uydurma, okunmuyorsa söyle.', [_jpeg(img)]


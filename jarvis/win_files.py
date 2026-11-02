"""Dosyalar (Windows): bilinen klasörler, gizli dosyalar, Gezgin'de gösterme, panoya dosya, küçük resim.

files.py'nin Windows'a özgü parçaları. Belgeler ve Resimler OneDrive'a taşınmış olabilir: klasörlerin gerçek
yeri Windows'un bilinen klasör API'sinden okunur, ~/Documents'a güvenilmez. OneDrive'da yalnızca bulutta duran
bir dosya açılırsa indirilir; küçük resmi bu yüzden yalnızca Windows'un küçük resim önbelleğinden gelir.
Hepsi ctypes ile (pywin32 yok).
"""

from __future__ import annotations
import ctypes
import os
import subprocess
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from .log import log
_shell32 = ctypes.WinDLL('shell32')
_ole32 = ctypes.WinDLL('ole32')
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_gdi32 = ctypes.WinDLL('gdi32')
_HIDDEN = 6
_CLOUD = 4460544

class GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

def _guid(text: 'str') -> 'GUID':
    g = GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
    return g

_shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHGetKnownFolderPath.restype = ctypes.c_long
_shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
_shell32.ILCreateFromPathW.restype = ctypes.c_void_p
_shell32.ILFree.argtypes = [ctypes.c_void_p]
_shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
_shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long
_shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterClipboardFormatW.restype = wintypes.UINT
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

def _com() -> 'bool':
    """Bu iş parçacığında COM'u açar; kapatılması gerekiyorsa True (başka kipte açıksa dokunulmaz)."""

    return _ole32.CoInitializeEx(None, 2) in (0, 1)

KNOWN = {'desktop': 'B4BFCC3A-DB2C-424C-B029-7FE99A87C641', 'documents': 'FDD39AD0-238F-46AF-ADB4-6C85480369C7', 'downloads': '374DE290-123F-4565-9164-39C4925E467B', 'pictures': '33E28130-4E1E-4676-835A-98395C3BC3BB', 'screenshots': 'B7BEDE81-DF94-4682-A7D8-57A52620B86F', 'public_desktop': 'C4AA340D-F20F-4863-AFEF-F87EF2E6BA25'}

def known_folder(name: 'str') -> 'Path | None':
    """Windows'un bildiği yer (OneDrive'a taşındıysa oradaki); yoksa None."""

    out = ctypes.c_void_p()
    hr = _shell32.SHGetKnownFolderPath(ctypes.byref(_guid(KNOWN[name])), 0, None, ctypes.byref(out))
    try:
        return Path(ctypes.wstring_at(out.value)) if hr == 0 and out.value else None
    finally:
        _ole32.CoTaskMemFree(out)

def hidden(entry: 'os.DirEntry') -> 'bool':
    '''Gizli ya da sistem dosyası, ya da bağlantı noktası (Belgeler'deki eski "My Music" gibi): aranmaz.'''

    try:
        if getattr(entry, 'is_junction', (lambda: False))():
            return True
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & _HIDDEN)
    except OSError:
        return True

def cloud_only(path: 'str | Path') -> 'bool':
    """OneDrive'da yalnızca bulutta duruyor mu (içeriği okunursa indirilir). Öznitelik okumak indirmez."""

    try:
        return bool(os.stat(path, follow_symlinks=False).st_file_attributes & _CLOUD)
    except OSError:
        return False

def reveal(path: 'str') -> 'None':
    """Dosya Gezgini'nde, dosya seçili olarak (o klasör zaten açıksa aynı pencerede)."""

    owned = _com()
    pidl = _shell32.ILCreateFromPathW(str(path))
    try:
        if pidl and _shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0:
            if pidl:
                _shell32.ILFree(pidl)
            if owned:
                _ole32.CoUninitialize()
                return
            return
    finally:
        if pidl:
            _shell32.ILFree(pidl)
        if owned:
            _ole32.CoUninitialize()
    subprocess.Popen(f'explorer /select,"{path}"')

class DROPFILES(ctypes.Structure):
    _fields_ = [('pFiles', wintypes.DWORD), ('pt', wintypes.POINT), ('fNC', wintypes.BOOL), ('fWide', wintypes.BOOL)]

_CF_HDROP = 15
_HWND_MESSAGE = wintypes.HWND(-3)

def copy_file(path: 'str') -> 'bool':
    """Dosyanın kendisini panoya koyar (Gezgin'in Ctrl+C'si gibi): Gezgin'e, WhatsApp'a, Outlook'a Ctrl+V."""

    head = DROPFILES(ctypes.sizeof(DROPFILES), wintypes.POINT(0, 0), False, True)
    drop = bytes(head) + (str(path) + '\x00\x00').encode('utf-16-le')
    effect = (1).to_bytes(4, 'little')
    hwnd = _user32.CreateWindowExW(0, 'STATIC', None, 0, 0, 0, 0, 0, _HWND_MESSAGE, None, None, None)
    try:
        for _ in range(20):
            if _user32.OpenClipboard(hwnd):
                break
            time.sleep(0.05)
        else:
            log('pano açılamadı:', ctypes.get_last_error())
            if hwnd:
                _user32.DestroyWindow(hwnd)
                return False
            return False
    finally:
        if hwnd:
            _user32.DestroyWindow(hwnd)
    try:
        try:
            _user32.EmptyClipboard()
            ok = _put(_CF_HDROP, drop)
            _put(_user32.RegisterClipboardFormatW('Preferred DropEffect'), effect)
        finally:
            _user32.CloseClipboard()
    finally:
        if hwnd:
            _user32.DestroyWindow(hwnd)
    return ok

def _put(fmt: 'int', blob: 'bytes') -> 'bool':
    mem = _kernel32.GlobalAlloc(2, len(blob))
    if not mem:
        return False
    ptr = _kernel32.GlobalLock(mem)
    if not ptr:
        _kernel32.GlobalFree(mem)
        return False
    ctypes.memmove(ptr, blob, len(blob))
    _kernel32.GlobalUnlock(mem)
    if not _user32.SetClipboardData(fmt, mem):
        _kernel32.GlobalFree(mem)
        return False
    return True

_IID_IMAGE_FACTORY = 'BCC18B79-BA16-442F-80C4-8A59C30C463B'
_BIGGER_OK, _THUMB_ONLY, _CACHE_ONLY = 1, 8, 16
_GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP))
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)

class BITMAP(ctypes.Structure):
    _fields_ = [('bmType', wintypes.LONG), ('bmWidth', wintypes.LONG), ('bmHeight', wintypes.LONG), ('bmWidthBytes', wintypes.LONG), ('bmPlanes', wintypes.WORD), ('bmBitsPixel', wintypes.WORD), ('bmBits', ctypes.c_void_p)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD), ('bmiColors', wintypes.DWORD * 3)]

def thumbnail(path: 'str | Path', side: 'int', download: 'bool'=False):
    """Gezgin'in küçük resmi (PIL görseli) ya da None. Yalnızca bulutta duran dosyada önbellekten (indirmez);
    download=True: kullanıcı dosyanın içini istedi, gerekirse OneDrive indirir."""

    if Path(path).suffix.lower() in ('.lnk', '.url', '.pif', '.scf'):
        return
    flags = None | (_BIGGER_OK | _THUMB_ONLY if not download else _CACHE_ONLY if cloud_only(path) else 0)
    owned = _com()
    try:
        factory = ctypes.c_void_p()
        if _shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(_guid(_IID_IMAGE_FACTORY)), ctypes.byref(factory)) != 0 or not factory.value:
            if owned:
                _ole32.CoUninitialize()
                return
            return
    finally:
        if owned:
            _ole32.CoUninitialize()
    try:
        vtable = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        hbm = wintypes.HBITMAP()
        try:
            hr = _GetImage(vtable[3])(factory, wintypes.SIZE(side, side), flags, ctypes.byref(hbm))
        finally:
            _Release(vtable[2])(factory)
        if hr != 0 or not hbm:
            if owned:
                _ole32.CoUninitialize()
                return
            return
    finally:
        if owned:
            _ole32.CoUninitialize()
    try:
        try:
            pass
        finally:
            _gdi32.DeleteObject(hbm)
    finally:
        if owned:
            _ole32.CoUninitialize()
    return _image(hbm)

def _image(hbm):
    from PIL import Image
    bm = BITMAP()
    if not _gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm)):
        return
    w, h = bm.bmWidth, abs(bm.bmHeight)
    info = BITMAPINFO(biSize=40, biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = _user32.GetDC(None)
    try:
        rows = _gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(info), 0)
    finally:
        _user32.ReleaseDC(None, hdc)
    if rows != h:
        return
    img = Image.frombuffer('RGBA', (w, h), buf.raw, 'raw', 'BGRA', 0, 1)
    if img.getextrema()[3][1]:
        return img
    return img.convert('RGB')

# WARNING: Decompyle incomplete

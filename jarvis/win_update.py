'''Windows güncelleyicisi: indirilen kurulumu denetler, JARVIS kapanınca sessizce kurdurur (W3, WINDOWS.md).

Akış (app.py › _update_install): updates.download (SHA-256 burada) → verify → launch → JARVIS kapanır. Kurulum
(scripts/jarvis_win.iss) /GUNCELLEME görünce JARVIS'in kapanmasını bekler (win_window.RUNNING_MUTEX), sessiz kurar ve
JARVIS'i yeniden açar; kuramazsa eski JARVIS'i açar. Sonraki açılışta outcome() sonucu söyler (bekleyen.json).

İmza sertifikası yok: güven GitHub'daki sürüme dayanır. SHA-256 özeti (GitHub'ın verdiği "digest") bozuk indirmeye,
kurulumun sürüm bilgisi yanlış dosyaya karşı denetlenir. requests ile indirilen dosyada "internetten geldi" işareti
olmadığı için SmartScreen sormaz; kurulum kullanıcı klasörüne olduğu için yönetici izni de istenmez (ölçüldü).
'''

from __future__ import annotations
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from . import (VERSION, paths, updates)
from .log import log
MIN_SIZE = 10485760
MAX_SIZE = 419430400
PENDING = 'bekleyen.json'
PENDING_FOR = 86400.0
_BREAKAWAY = 16777216

def install_dir() -> 'Path | None':
    '''Kurulumdan çalışan JARVIS'in klasörü (yanında kaldırıcısı var). dist\\JARVIS'ten ya da kaynaktan çalışan
    kopya güncellenmez (None). "JARVIS Deneme" (build_win.py --deneme, klasöründe "deneme" işareti) yalnızca deneme
    kanalından güncellenir: resmî kurulum onun klasörüne kurulursa gerçek JARVIS'in kaydı oraya taşınırdı.'''

    if not paths.FROZEN:
        return
    folder = Path(sys.executable).resolve().parent
    if not (folder / 'unins000.exe').exists():
        return
    if (folder / 'deneme').exists() and not os.environ.get('JARVIS_UPDATE_FEED'):
        return
    return folder

def _parts(version: 'str') -> 'tuple[int, int, int]':
    nums = [int(x) for x in re.findall('\\d+', version or '')[:3]]
    return tuple(nums + [0] * (3 - len(nums)))

class _FixedInfo(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in ('signature', 'struc_version', 'file_ms', 'file_ls', 'product_ms', 'product_ls', 'flags_mask', 'flags', 'os', 'type', 'subtype', 'date_ms', 'date_ls')]

def file_info(path: 'Path') -> 'tuple[str, str]':
    '''(dosya sürümü "a.b.c.d", ürün adı); okunamazsa boş.'''

    dll = ctypes.WinDLL('version')
    dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    dll.GetFileVersionInfoW.restype = wintypes.BOOL
    dll.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    dll.VerQueryValueW.restype = wintypes.BOOL
    size = dll.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ('', '')
    block = ctypes.create_string_buffer(size)
    if not dll.GetFileVersionInfoW(str(path), 0, size, block):
        return ('', '')
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    version = ''
    if dll.VerQueryValueW(block, '\\', ctypes.byref(ptr), ctypes.byref(length)) and length.value >= ctypes.sizeof(_FixedInfo):
        fixed = ctypes.cast(ptr, ctypes.POINTER(_FixedInfo)).contents
        if fixed.signature == 4277077181:
            version = f'{fixed.file_ms >> 16}.{fixed.file_ms & 65535}.{fixed.file_ls >> 16}.{fixed.file_ls & 65535}'
    name = ''
    if dll.VerQueryValueW(block, '\\VarFileInfo\\Translation', ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 4:
        lang, codepage = (ctypes.c_ushort * 2).from_address(ptr.value)
        key = f'\\StringFileInfo\\{lang:04x}{codepage:04x}\\ProductName'
        if dll.VerQueryValueW(block, key, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
            name = ctypes.wstring_at(ptr.value, length.value).rstrip('\x00').strip()
    return version, name

def verify(setup: 'Path', info: 'dict', official: 'bool') -> 'str | None':
    """İndirilen kurulum kurulabilir mi? Sorun varsa açıklaması (SHA-256'yı updates.download denetledi)."""

    try:
        size = setup.stat().st_size
    except OSError:
        return 'İndirilen dosya bulunamadı.'
    if not MIN_SIZE <= size <= MAX_SIZE:
        return 'İndirilen dosyanın boyutu beklenmedik; kurulmadı.'
    if official and not info.get('sha256'):
        return 'Sürümde dosyanın SHA-256 özeti yok; güvenlik için kurulmadı.'
    version, name = file_info(setup)
    if name not in updates.NAMES:
        return 'İndirilen dosya JARVIS kurulumu değil; kurulmadı.'
    if _parts(version) != _parts(info.get('version', '')):
        return 'İndirilen sürüm duyurulanla aynı değil; kurulmadı.'

def launch(setup: 'Path', version: 'str', folder: 'Path', relaunch: 'bool'=True) -> 'None':
    """Kurulumu JARVIS'ten bağımsız başlatır; JARVIS hemen ardından kapanmalı (kurulum kilidin bırakılmasını bekler)."""

    install_log = updates.CACHE / f'kurulum-{version}.log'
    pending = updates.CACHE / PENDING
    pending.write_text(json.dumps({'version': version, 'log': str(install_log), 'at': time.time()}), encoding='utf-8')
    args = [str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS', '/GUNCELLEME', '/MERGETASKS=!desktopicon', f'/DIR={folder}', f'/LOG={install_log}']
    if not relaunch:
        args.append('/YENIDENACMA')
    env = {k: v for k, v in os.environ.items() if k not in ('JARVIS_UPDATE_AUTO', 'JARVIS_UPDATE_FORCE')}
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        try:
            subprocess.Popen(args, creationflags=flags | _BREAKAWAY, close_fds=True, env=env)
        except OSError:
            subprocess.Popen(args, creationflags=flags, close_fds=True, env=env)
    except OSError as exc:
        pending.unlink(missing_ok=True)
        raise RuntimeError('Kurulum başlatılamadı.') from exc
    log('güncelleme: kurulum başlatıldı, JARVIS kapanınca kurulacak', version)

def outcome() -> 'str | None':
    '''Önceki açılışta başlatılan kurulumun sonucu (yoksa None); kayıt bir kez okunur.'''

    pending = updates.CACHE / PENDING
    try:
        data = json.loads(pending.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    pending.unlink(missing_ok=True)
    if isinstance(data, dict):
        if time.time() - float(data.get('at') or 0) > PENDING_FOR:
            return
    wanted = str(data.get('version') or '')
    try:
        setup_log = Path(str(data.get('log') or '')).read_text(encoding='utf-8', errors='replace')
    except OSError:
        setup_log = ''
    ok = _parts(VERSION) >= _parts(wanted) and (not setup_log or 'Installation process succeeded' in setup_log)
    if ok:
        log('güncelleme kuruldu:', VERSION)
        return f'JARVIS {VERSION} sürümüne güncellendi.'
    log('güncelleme kurulamadı:', wanted, 'günlük:', data.get('log'))
    if 'JARVIS kapanmadı' in setup_log:
        return "Güncelleme kurulamadı: açık başka bir JARVIS var. Hepsini kapatıp Ayarlar › Hakkında'dan yeniden dene."
    return f"Güncelleme kurulamadı; JARVIS {VERSION} sürümünde kaldı. Ayarlar › Hakkında'dan yeniden dene."


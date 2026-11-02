"""Windows: klavye ve fare kaç saniyedir durgun (proactive.system_idle'ın karşılığı; izin gerektirmez).

Kendiliğinden konuşma buna bakarak kullanıcının başında olup olmadığını anlar: su ve mola hatırlatmaları,
sessizlik açılışları boş odaya söylenmez. Yalnızca Windows'ta içe aktarılır.
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes

class _LastInput(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]

_user32 = ctypes.WinDLL('user32')
_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInput)]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_kernel32 = ctypes.WinDLL('kernel32')
_kernel32.GetTickCount64.restype = ctypes.c_ulonglong

def seconds() -> 'float | None':
    '''Son klavye/fare girdisinden bu yana geçen süre (sn); oturum geneli, bütün uygulamalara giden girdi sayılır.'''

    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return
    return ((_kernel32.GetTickCount64() & 4294967295) - info.dwTime & 4294967295) / 1000.0


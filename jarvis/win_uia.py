"""UI Automation (Windows, ctypes): başka bir uygulamanın penceresindeki yazı kutularını okumak.

Chromium/WebView2 içerikleri (WhatsApp masaüstü) .NET'in eski istemcisine (System.Windows.Automation) görünmüyor;
yerel IUIAutomation (CUIAutomation8) görüyor. Yalnızca gereken kadarı: bir pencerenin altındaki yazı kutuları
(Edit), değerleri, odak. Aramayı WebView2'nin kendi penceresinden başlat: WinUI kabuğundan başlayınca ağaç
döngüye girip aynı kutuyu onlarca kez veriyor (WhatsApp'ta 79 kez, 1,4 sn; WebView2 penceresinden 1 kez, 0,02 sn).
Okunan metinler hiçbir yere yazılmaz.
"""

from __future__ import annotations
import ctypes
import uuid
from ctypes import wintypes
_ole32 = ctypes.WinDLL('ole32')
_oleaut32 = ctypes.WinDLL('oleaut32')
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long

class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

class _VARIANT(ctypes.Structure):
    _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort), ('r2', ctypes.c_ushort), ('r3', ctypes.c_ushort), ('val', ctypes.c_void_p), ('val2', ctypes.c_void_p)]

_oleaut32.VariantClear.argtypes = [ctypes.POINTER(_VARIANT)]
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.c_long

def _guid(text: 'str') -> '_GUID':
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
    return g

_CLSID_UIA8 = 'e22ad333-b25f-460c-83d0-0581107395c9'
_CLSID_UIA = 'ff48dba4-60ef-4201-aa87-54103eef594e'
_IID_UIA = '30cbe57d-d9d0-452a-ab13-7ac5ac4825ee'
_VALUE, _FOCUSED, _CONTROL_TYPE, _NAME, _ENABLED = 30045, 30008, 30003, 30005, 30010
_EDIT, _BUTTON = 50004, 50000
_INVOKE_PATTERN = 10000
_DESCENDANTS = 4
_VT_BSTR, _VT_I4, _VT_BOOL = 8, 3, 11

def _method(obj: 'ctypes.c_void_p', index: 'int', *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
    return lambda *args: fn(obj, *args)

def _release(obj: 'ctypes.c_void_p') -> 'None':
    if obj:
        if obj.value:
            _method(obj, 2)()
            obj.value = None

class Element:
    '''IUIAutomationElement (yalnızca kullanılanlar).'''

    def __init__(self, ptr: 'ctypes.c_void_p') -> 'None':
        self.ptr = ptr

    def _prop(self, prop: 'int'):
        v = _VARIANT()
        if _method(self.ptr, 10, ctypes.c_int, ctypes.POINTER(_VARIANT))(prop, ctypes.byref(v)):
            return
        try:
            if v.vt == _VT_BSTR:
                _oleaut32.VariantClear(ctypes.byref(v))
                return ctypes.wstring_at(v.val) if v.val else ''
        finally:
            _oleaut32.VariantClear(ctypes.byref(v))
        try:
            if v.vt == _VT_BOOL:
                _oleaut32.VariantClear(ctypes.byref(v))
                return bool(v.val)
        finally:
            _oleaut32.VariantClear(ctypes.byref(v))
        try:
            if v.vt == _VT_I4:
                _oleaut32.VariantClear(ctypes.byref(v))
                return ctypes.c_int(v.val or 0).value
        finally:
            _oleaut32.VariantClear(ctypes.byref(v))

    def value(self) -> 'str | None':
        '''Yazı kutusunun metni; öğe artık yoksa ya da okunamıyorsa None.'''

        out = self._prop(_VALUE)
        if isinstance(out, str):
            return out

    def focused(self) -> 'bool':
        return self._prop(_FOCUSED) is True

    def name(self) -> 'str':
        out = self._prop(_NAME)
        if isinstance(out, str):
            return out
        return ''

    def enabled(self) -> 'bool':
        return self._prop(_ENABLED) is True

    def focus(self) -> 'bool':
        return _method(self.ptr, 3)() == 0

    def invoke(self) -> 'bool':
        '''Düğmeye bas (InvokePattern; klavye ve odak gerekmez).'''

        pattern = ctypes.c_void_p()
        if _method(self.ptr, 16, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(_INVOKE_PATTERN, ctypes.byref(pattern)) or not pattern.value:
            return False
        try:
            return _method(pattern, 3)() == 0
        finally:
            _release(pattern)

    def release(self) -> 'None':
        _release(self.ptr)


class Uia:
    """with Uia() as uia: ... — iş parçacığında COM'u açar, kapanışta her şeyi bırakır."""

    def __enter__(self) -> "'Uia'":
        self.owned = _ole32.CoInitializeEx(None, 2) in (0, 1)
        self.obj = ctypes.c_void_p()
        self.conds = {}
        try:
            for clsid in _CLSID_UIA8, _CLSID_UIA:
                if _ole32.CoCreateInstance(ctypes.byref(_guid(clsid)), None, 1, ctypes.byref(_guid(_IID_UIA)), ctypes.byref(self.obj)) != 0:
                    continue
                if not self.obj.value:
                    continue
                return self
        except BaseException:
            self.__exit__()
            raise
        try:
            raise OSError('UI Automation açılamadı')
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *exc) -> 'None':
        for cond in self.conds.values():
            _release(cond)
        _release(self.obj)
        if self.owned:
            _ole32.CoUninitialize()

    def _cond(self, control_type: 'int') -> 'ctypes.c_void_p':
        '''IUIAutomation::CreatePropertyCondition(ControlType == …), bir kez kurulur.'''

        if control_type not in self.conds:
            cond, v = ctypes.c_void_p(), _VARIANT()
            v.vt, v.val = _VT_I4, control_type
            if _method(self.obj, 23, ctypes.c_int, _VARIANT, ctypes.POINTER(ctypes.c_void_p))(_CONTROL_TYPE, v, ctypes.byref(cond)) or not cond.value:
                raise OSError('UI Automation koşulu kurulamadı')
            self.conds[control_type] = cond
        return self.conds[control_type]

    def edits(self, hwnd: 'int') -> 'list[Element]':
        '''Pencerenin altındaki bütün yazı kutuları (çağıran release etmeli).'''

        return self._find(hwnd, _EDIT)

    def buttons(self, hwnd: 'int', names: 'set[str]') -> 'list[Element]':
        '''Adı tam olarak `names`ten biri olan düğmeler (büyük/küçük harf fark etmez; çağıran release etmeli).'''

        wanted = {n.casefold() for n in names}
        out = []
        for el in self._find(hwnd, _BUTTON):
            if el.name().strip().casefold() in wanted:
                out.append(el)
            else:
                el.release()
        return out

    def _find(self, hwnd: 'int', control_type: 'int') -> 'list[Element]':
        root, arr = ctypes.c_void_p(), ctypes.c_void_p()
        if _method(self.obj, 6, wintypes.HWND, ctypes.POINTER(ctypes.c_void_p))(hwnd, ctypes.byref(root)) or not root.value:
            return []
        try:
            if _method(root, 6, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(_DESCENDANTS, self._cond(control_type), ctypes.byref(arr)) or not arr.value:
                _release(arr)
                _release(root)
                return []
        finally:
            _release(arr)
            _release(root)
        try:
            count = ctypes.c_int()
            _method(arr, 3, ctypes.POINTER(ctypes.c_int))(ctypes.byref(count))
            out = []
            for i in range(min(count.value, 200)):
                el = ctypes.c_void_p()
                if _method(arr, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(el)) != 0:
                    continue
                if el.value:
                    out.append(Element(el))
        finally:
            _release(arr)
            _release(root)
        return out



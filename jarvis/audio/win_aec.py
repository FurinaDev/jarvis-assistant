'''Windows'ta yankı engellemeli mikrofon: Windows'un yerleşik Voice Capture DSP'si (W3, WINDOWS.md).

Mac'teki Apple yankı engellemesinin karşılığı. DSP (CLSID_CWMAudioAEC, Skype'ın da kullandığı bileşen) "kaynak
kipinde" mikrofonu ve hoparlörün geri döngüsünü kendisi açar, hizalamayı ve saat kaymasını kendisi çözer; çıktısı
16 kHz mono, asistanın sesi silinmiş mikrofon. Hoparlöre giden bütün ses (müzik dahil) silinir. Paket gerekmez
(System32'de), yalnızca ctypes.

Canlı ölçüm (2 Ekim 2026, MSI dizüstü, ses %47): asistanın yankısı 33 dB silindi, kalan iz en çok 0.005 (söz kesme
kapısının tabanı 0.05); kullanıcının sesi asistan konuşurken de 0.14–0.58 düzeyinde geçti, kapı 0.13 sn'de açıldı.

- DSP yalnızca seçilen hoparlörde etkin bir akış varken çıktı verir: JARVIS'in hoparlör akışı oturum boyunca açık.
- Hoparlör (`Speaker`) bugünkü PortAudio hoparlörü; söz kesme için kısma (duck), "uyum sağladı mı" (warm) ve kapıya
  ek taban (echo_floor) eklenir. DSP ara sıra yarım saniyelik 0.06-0.15'lik iz bırakıyor: asistan çalarken kapı,
  çalınan tepeden ve hoparlörün ses düzeyinden tahmin edilen bu izin üstünü bekler (mikrofon sesine dokunulmaz).
- Öz denetim: asistan yüksek sesle konuşurken iz, asistan susarkenki ortam sesinin belirgin üstünde ve çoğu parçada
  kalıyorsa (yanlış hoparlör, kopan aygıt) yankı engelleme "etkisiz" sayılır, asistan konuşurken mikrofon yine susar;
  düzelince söz kesme geri gelir.
DSP açılamazsa (Windows N sürümü, aygıt yok) `Microphone` bugünkü yola döner.
'''

from __future__ import annotations
import asyncio
import ctypes
import threading
import time
import uuid
from collections import deque
from ctypes import wintypes
import numpy as np
from ..log import log
from .devices import (CHUNK, MIC_RATE, SPEAKER_RATE, _offer, _PortSpeaker)
OPEN_WAIT = 5.0
WARM_SAMPLES = SPEAKER_RATE
DUCK = 0.35
AES = 2
RECENT = (0.15, 0.6)
CAL_DB = -11.2
FLOOR_RATIO = 0.15
FLOOR_CAP = 0.12
LOUD = 0.3
PROBE = 64
RESIDUE = 0.02
VOLUME_EVERY = 1.0
_ole32 = ctypes.WinDLL('ole32')
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = []
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.PropVariantClear.argtypes = [ctypes.c_void_p]

class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

def _guid(text: 'str') -> '_GUID':
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
    return g

_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.c_long
_CLSID_AEC = '745057C7-F353-4F2D-A7EE-58434477730E'
_IID_MEDIA_OBJECT = 'D8AD0F58-5494-4102-97C5-EC798E59BCF4'
_IID_PROPERTY_STORE = '886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99'
_IID_MEDIA_BUFFER = '59EFF8B9-938C-4A26-82F2-95CB84CDC837'
_IID_UNKNOWN = '00000000-0000-0000-C000-000000000046'
_FMTID_AEC = '6F52C567-0360-4BD2-9617-CCBF1421C939'
_CLSID_ENUMERATOR = 'BCDE0395-E52F-467C-8E3D-C4579291692E'
_IID_ENUMERATOR = 'A95664D2-9614-4F35-A746-DE8DB63617E6'
_IID_ENDPOINT_VOLUME = '5CDF2C82-841E-4546-9722-0CF74078229A'
_PID_SYSTEM_MODE, _PID_DEVICE_INDEXES, _PID_FEATURE_MODE, _PID_AES, _PID_MIC_GAIN_BOUNDER = 2, 4, 5, 10, 21
_VT_I4, _VT_BOOL, _VT_LPWSTR = 3, 11, 31
_RENDER, _CAPTURE, _CONSOLE, _COMMUNICATIONS, _ACTIVE = 0, 1, 0, 2, 1
_FMTID_DEVICE_NAME, _PID_FRIENDLY_NAME = 'A45C254E-DF1C-4EFD-8020-67D146A850E0', 14
_PID_ENUMERATOR = 24
_FMTID_FORM_FACTOR = '1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E'
_FMTID_CONTAINER = '8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C'
_VT_UI4, _VT_CLSID = 19, 72
_FORMS = {0: 'ağ', 1: 'hoparlör', 2: 'hat', 3: 'kulaklık', 4: 'mikrofon', 5: 'kulaklıklı mikrofon', 6: 'ahize', 7: 'dijital', 8: 'SPDIF', 9: 'HDMI/ekran', 10: 'bilinmiyor'}
_BT_BUSES = ('BTHENUM', 'BTHLE', 'BTHHFENUM', 'BTHLEDEVICE')
_INCOMPLETE = 16777216

def _method(obj, index: 'int', *argtypes):
    '''COM nesnesinin sanal tablosundaki `index`. yöntem (ilk bağımsız değişken nesnenin kendisi).'''

    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
    return lambda *args: fn(obj, *args)

def _release(obj: 'ctypes.c_void_p') -> 'None':
    if obj:
        if obj.value:
            _method(obj, 2)()
            obj.value = None

def _hr(code: 'int') -> 'str':
    return f'0x{code & 4294967295:08X}'

class _Com:
    '''Bu iş parçacığında COM (with içinde); başka kipte zaten açıksa ona dokunmaz.'''

    def __enter__(self):
        self.owned = _ole32.CoInitializeEx(None, 0) in (0, 1)
        return self

    def __exit__(self, *exc):
        if self.owned:
            _ole32.CoUninitialize()


def _enumerator() -> 'ctypes.c_void_p':
    enum = ctypes.c_void_p()
    code = _ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_ENUMERATOR)), None, 23, ctypes.byref(_guid(_IID_ENUMERATOR)), ctypes.byref(enum))
    if code or not enum.value:
        raise OSError(f'ses aygıtları okunamadı ({_hr(code)})')
    return enum

def _device_id(device: 'ctypes.c_void_p') -> 'str':
    text = ctypes.c_void_p()
    if _method(device, 5, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(text)) or not text.value:
        return ''
    try:
        return ctypes.wstring_at(text.value)
    finally:
        _ole32.CoTaskMemFree(text)

def _props(device: 'ctypes.c_void_p', *keys: 'tuple[str, int]') -> 'list':
    '''Aygıtın özellikleri (salt okunur): metin, sayı ya da GUID metni; okunamayan None.'''

    out = [None] * len(keys)
    store = ctypes.c_void_p()
    if _method(device, 4, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(0, ctypes.byref(store)) or not store.value:
        return out
    try:
        get = _method(store, 5, ctypes.POINTER(_PropKey), ctypes.POINTER(_PropVariant))
        for i, (fmtid, pid) in enumerate(keys):
            key, var = _PropKey(_guid(fmtid), pid), _PropVariant()
            if get(ctypes.byref(key), ctypes.byref(var)):
                continue
            try:
                if var.vt == _VT_LPWSTR and var.value:
                    out[i] = ctypes.wstring_at(var.value)
                elif var.vt == _VT_UI4:
                    out[i] = var.value & 4294967295
                elif var.vt == _VT_CLSID and var.value:
                    out[i] = str(uuid.UUID(bytes_le=ctypes.string_at(var.value, 16)))
            finally:
                _ole32.PropVariantClear(ctypes.byref(var))
            continue
    finally:
        _release(store)
    return out

def _device_name(device: 'ctypes.c_void_p') -> 'str':
    '''Aygıtın Windows'ta görünen adı (ör. "Mikrofon (Realtek(R) Audio)"); okunamazsa boş.'''

    return _props(device, (_FMTID_DEVICE_NAME, _PID_FRIENDLY_NAME))[0] or ''

def _default_device(enum: 'ctypes.c_void_p', flow: 'int', role: 'int'=_CONSOLE) -> 'ctypes.c_void_p':
    device = ctypes.c_void_p()
    if _method(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(flow, role, ctypes.byref(device)) or not device.value:
        device.value = None
    return device

def _default_id(enum: 'ctypes.c_void_p', flow: 'int') -> 'str':
    device = _default_device(enum, flow)
    if not device.value:
        return ''
    try:
        return _device_id(device)
    finally:
        _release(device)

def endpoints(flow: 'int'=_CAPTURE) -> 'list[dict]':
    '''Etkin aygıtlar (Ayarlar › SES › MİKROFON seçicisi): [{"id", "name"}], DSP'nin sırasıyla.'''

    out = []
    try:
        with _Com():
            enum = _enumerator()
    except Exception as exc:
        log('ses aygıtları listelenemedi:', exc)
        return out
    try:
        pass
    finally:
        _release(enum)
        try:
            coll = ctypes.c_void_p()
            if _method(enum, 3, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(flow, _ACTIVE, ctypes.byref(coll)) or not coll.value:
                _release(enum)
                return out
        except Exception as exc:
            log('ses aygıtları listelenemedi:', exc)
            return out
    try:
        count = wintypes.UINT()
        _method(coll, 3, ctypes.POINTER(wintypes.UINT))(ctypes.byref(count))
        for i in range(count.value):
            device = ctypes.c_void_p()
            if _method(coll, 4, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(device)):
                continue
            try:
                out.append({'id': _device_id(device), 'name': _device_name(device) or f'Aygıt {i + 1}'})
            finally:
                _release(device)
    finally:
        try:
            _release(coll)
        finally:
            _release(enum)
    _release(enum)
    try:
        pass
    except Exception as exc:
        log('ses aygıtları listelenemedi:', exc)
    return out

def describe() -> 'dict[str, str]':
    '''Varsayılan aygıtların adları (teşhis günlüğü ve uyarılar): mic, mic_comm, speaker, speaker_comm.'''

    names = {}
    try:
        with _Com():
            enum = _enumerator()
    except Exception as exc:
        log('ses aygıtlarının adları okunamadı:', exc)
        return names
    try:
        for key, flow, role in ('mic', _CAPTURE, _CONSOLE), ('mic_comm', _CAPTURE, _COMMUNICATIONS), ('speaker', _RENDER, _CONSOLE), ('speaker_comm', _RENDER, _COMMUNICATIONS):
            device = _default_device(enum, flow, role)
            if device.value:
                try:
                    names[key] = _device_name(device) or '(adsız)'
                finally:
                    _release(device)
            else:
                names[key] = '(yok)'
    finally:
        _release(enum)
    try:
        pass
    except Exception as exc:
        log('ses aygıtlarının adları okunamadı:', exc)
    return names

def _bluetooth_containers() -> 'set[str]':
    '''Bluetooth aygıtlarının kap kimlikleri (kayıt defteri, salt okunur, yönetici izni gerekmez). Ses uç noktasının
    sayacı Intel'in Bluetooth ses boşaltmalı sürücülerinde BTHENUM değil INTELAUDIO çıkabiliyor; kap kimliği aynı
    kalır. FormFactor tek başına yetmez: USB kulaklık da "kulaklıklı mikrofon" (5).'''

    import winreg
    found = set()
    for bus in _BT_BUSES:
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f'SYSTEM\\CurrentControlSet\\Enum\\{bus}')
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as device:
                        for j in range(winreg.QueryInfoKey(device)[0]):
                            try:
                                try:
                                    with winreg.OpenKey(device, winreg.EnumKey(device, j)) as inst:
                                        found.add(str(winreg.QueryValueEx(inst, 'ContainerID')[0]).strip('{}').lower())
                                except OSError:
                                    continue
                            finally:
                                if not None:
                                    pass
                except OSError:
                    continue
                try:
                    pass
                except OSError:
                    continue
        continue
    return found

def audio_report() -> 'dict':
    '''TEŞHİSİ KOPYALA için (win_diag.lines): etkin uçlar türleri ve Bluetooth olup olmadıklarıyla, varsayılanlar.
    {"mic": [...], "speaker": [...], "default_mic", "default_speaker"}; her uç {"id","name","bt","form","bus"}.
    Bluetooth kulaklığın mikrofonu açılınca Windows kulaklığı "eller serbest"e (HFP) geçirir: ses telefon kalitesine
    düşer (testçi raporu 9.4, AirPods).'''

    report = {'mic': [], 'speaker': [], 'default_mic': '', 'default_speaker': ''}
    try:
        bt = _bluetooth_containers()
    except Exception:
        bt = set()
    try:
        with _Com():
            enum = _enumerator()
    except Exception as exc:
        log('ses aygıtı özellikleri okunamadı:', exc)
        return report
    try:
        report['default_mic'], report['default_speaker'] = _default_id(enum, _CAPTURE), _default_id(enum, _RENDER)
        for key, flow in ('mic', _CAPTURE), ('speaker', _RENDER):
            coll = ctypes.c_void_p()
            if _method(enum, 3, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(flow, _ACTIVE, ctypes.byref(coll)) or not coll.value:
                continue
            continue
            try:
                count = wintypes.UINT()
                _method(coll, 3, ctypes.POINTER(wintypes.UINT))(ctypes.byref(count))
                for i in range(count.value):
                    device = ctypes.c_void_p()
                    if _method(coll, 4, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(device)):
                        pass
            finally:
                _release(device)
                try:
                    name, bus, form, box = _props(device, (_FMTID_DEVICE_NAME, _PID_FRIENDLY_NAME), (_FMTID_DEVICE_NAME, _PID_ENUMERATOR), (_FMTID_FORM_FACTOR, 0), (_FMTID_CONTAINER, 2))
                    report[key].append({'id': _device_id(device), 'name': name or f'Aygıt {i + 1}', 'bus': bus or '?', 'form': _FORMS.get(form, str(form) if form is not None else '?'), 'bt': str(bus or '').upper().startswith('BTH') or (box or '').lower() in bt})
                finally:
                    _release(coll)
            continue
            _release(coll)
            continue
    finally:
        _release(enum)
    try:
        pass
    except Exception as exc:
        log('ses aygıtı özellikleri okunamadı:', exc)
    return report

def name_of(device_id: 'str') -> 'str':
    '''Kimliği verilen giriş aygıtının adı (seçili mikrofon); bulunamazsa boş.'''

    return next((d['name'] for d in endpoints(_CAPTURE) if d['id'] == device_id), '')

def _index(enum: 'ctypes.c_void_p', flow: 'int', wanted: 'str') -> 'int':
    """Aygıtın etkin aygıtlar listesindeki sırası (DSP'nin DEVICE_INDEXES'i bu sırayı ister); yoksa -1."""

    if not wanted:
        return -1
    coll = ctypes.c_void_p()
    if _method(enum, 3, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(flow, _ACTIVE, ctypes.byref(coll)) or not coll.value:
        return -1
    try:
        count = wintypes.UINT()
        _method(coll, 3, ctypes.POINTER(wintypes.UINT))(ctypes.byref(count))
        for i in range(count.value):
            try:
                try:
                    if _device_id(device) == wanted:
                        _release(device)
                        i
                        _release(coll)
                        return
                finally:
                    device = ctypes.c_void_p()
                    if _method(coll, 4, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(device)) != 0:
                        continue
            finally:
                _release(device)
                _release(coll)
            _release(device)
    finally:
        _release(coll)
    return -1

def _endpoint_volume(enum: 'ctypes.c_void_p') -> 'ctypes.c_void_p':
    """Varsayılan hoparlörün IAudioEndpointVolume'ü (alınamazsa boş)."""

    device, volume = ctypes.c_void_p(), ctypes.c_void_p()
    if _method(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(_RENDER, _CONSOLE, ctypes.byref(device)) or not device.value:
        return volume
    try:
        if _method(device, 3, ctypes.POINTER(_GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(_guid(_IID_ENDPOINT_VOLUME)), 23, None, ctypes.byref(volume)):
            volume.value = None
    finally:
        _release(device)
    return volume

def default_ids() -> 'tuple[str | int, str | int] | None':
    '''Sistemin o anki varsayılan (giriş, çıkış) aygıtının kimliği; yoksa -1 (devices.default_devices).'''

    try:
        with _Com():
            enum = _enumerator()
    except Exception:
        return
    try:
        pass
    finally:
        _release(enum)
    try:
        return _default_id(enum, _CAPTURE) or -1, _default_id(enum, _RENDER) or -1
    except Exception:
        return

_QI = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
_REF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_SETLEN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.DWORD)
_GETMAX = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
_GETBUF = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
_BUFFERS: 'dict[int, _Buffer]' = {}
_BUFFER_IIDS = {bytes(_guid(_IID_UNKNOWN)), bytes(_guid(_IID_MEDIA_BUFFER))}

@_QI
def _buf_qi(this, riid, ppv):
    if bytes(riid.contents) in _BUFFER_IIDS:
        ppv[0] = this
        return 0
    ppv[0] = None
    return -2147467262

@_REF
def _buf_ref(_this):
    return 1

@_SETLEN
def _buf_setlen(this, length):
    buf = _BUFFERS.get(this)
    if buf is None or length > buf.size:
        return -2147024809
    buf.length = length
    return 0

@_GETMAX
def _buf_getmax(this, out):
    buf = _BUFFERS.get(this)
    if buf is None or not out:
        return -2147467261
    out[0] = buf.size
    return 0

@_GETBUF
def _buf_get(this, data, length):
    buf = _BUFFERS.get(this)
    if buf is None:
        return -2147467261
    if data:
        data[0] = ctypes.addressof(buf.data)
    if length:
        length[0] = buf.length
    return 0

_BUF_VTABLE = (ctypes.c_void_p * 6)(*[ctypes.cast(f, ctypes.c_void_p).value for f in (_buf_qi, _buf_ref, _buf_ref, _buf_setlen, _buf_getmax, _buf_get)])

class _Buffer:
    def __init__(self, size: 'int') -> 'None':
        self.size, self.length = size, 0
        self.data = ctypes.create_string_buffer(size)
        self.obj = (ctypes.c_void_p * 1)(ctypes.addressof(_BUF_VTABLE))
        self.ptr = ctypes.addressof(self.obj)
        _BUFFERS[self.ptr] = self

    def take(self) -> 'bytes':
        out = self.data.raw[:self.length]
        self.length = 0
        return out

    def free(self) -> 'None':
        _BUFFERS.pop(self.ptr, None)


class _WaveFormat(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('wFormatTag', wintypes.WORD), ('nChannels', wintypes.WORD), ('nSamplesPerSec', wintypes.DWORD), ('nAvgBytesPerSec', wintypes.DWORD), ('nBlockAlign', wintypes.WORD), ('wBitsPerSample', wintypes.WORD), ('cbSize', wintypes.WORD)]

class _MediaType(ctypes.Structure):
    _fields_ = [('majortype', _GUID), ('subtype', _GUID), ('bFixedSizeSamples', wintypes.BOOL), ('bTemporalCompression', wintypes.BOOL), ('lSampleSize', wintypes.ULONG), ('formattype', _GUID), ('pUnk', ctypes.c_void_p), ('cbFormat', wintypes.ULONG), ('pbFormat', ctypes.c_void_p)]

class _OutputBuffer(ctypes.Structure):
    _fields_ = [('pBuffer', ctypes.c_void_p), ('dwStatus', wintypes.DWORD), ('rtTimestamp', ctypes.c_longlong), ('rtTimelength', ctypes.c_longlong)]

class _PropKey(ctypes.Structure):
    _fields_ = [('fmtid', _GUID), ('pid', wintypes.DWORD)]

class _PropVariant(ctypes.Structure):
    _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort), ('r2', ctypes.c_ushort), ('r3', ctypes.c_ushort), ('value', ctypes.c_longlong), ('extra', ctypes.c_void_p)]

class _Dsp:
    '''Voice Capture DSP, kaynak kipi, 16 kHz mono 16 bit çıktı. Oluşturulduğu iş parçacığında kullanılır.'''

    def __init__(self, mic_id: 'str'='') -> 'None':
        self.dmo, self.store, self.volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        self.buffer = _Buffer(MIC_RATE * 2)
        self.mic_id, self.mic_name = mic_id, ''
        try:
            self._open()
            return
        except BaseException:
            self.close()
            raise

    def _open(self) -> 'None':
        code = _ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_AEC)), None, 1, ctypes.byref(_guid(_IID_MEDIA_OBJECT)), ctypes.byref(self.dmo))
        if code or not self.dmo.value:
            raise OSError(f'Voice Capture DSP yok ({_hr(code)})')
        code = _method(self.dmo, 0, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(_guid(_IID_PROPERTY_STORE)), ctypes.byref(self.store))
        if code or not self.store.value:
            raise OSError(f'DSP ayarları açılamadı ({_hr(code)})')
        self._set(_PID_SYSTEM_MODE, _VT_I4, 0)
        self._set(_PID_MIC_GAIN_BOUNDER, _VT_BOOL, 0)
        self._set(_PID_FEATURE_MODE, _VT_BOOL, 1)
        self._set(_PID_AES, _VT_I4, AES)
        enum = _enumerator()
        try:
            mic = _index(enum, _CAPTURE, self.mic_id) if self.mic_id else -1
            if mic < 0:
                self.mic_id = _default_id(enum, _CAPTURE)
                mic = _index(enum, _CAPTURE, self.mic_id)
            spk = _index(enum, _RENDER, _default_id(enum, _RENDER))
            self.volume = _endpoint_volume(enum)
        finally:
            _release(enum)
        self.mic_name = name_of(self.mic_id) if self.mic_id else ''
        self._set(_PID_DEVICE_INDEXES, _VT_I4, (spk & 65535) << 16 | mic & 65535)
        fmt = _WaveFormat(1, 1, MIC_RATE, MIC_RATE * 2, 2, 16, 0)
        kind = _MediaType()
        kind.majortype = _guid('73647561-0000-0010-8000-00AA00389B71')
        kind.subtype = _guid('00000001-0000-0010-8000-00AA00389B71')
        kind.bFixedSizeSamples, kind.lSampleSize = 1, 2
        kind.formattype = _guid('05589F81-C356-11CE-BF01-00AA0055595A')
        kind.cbFormat = ctypes.sizeof(fmt)
        kind.pbFormat = ctypes.cast(ctypes.pointer(fmt), ctypes.c_void_p)
        code = _method(self.dmo, 9, wintypes.DWORD, ctypes.POINTER(_MediaType), wintypes.DWORD)(0, ctypes.byref(kind), 0)
        if code:
            raise OSError(f'DSP çıktı biçimi kabul edilmedi ({_hr(code)})')
        code = _method(self.dmo, 18)()
        if code < 0:
            raise OSError(f'DSP mikrofonu açamadı ({_hr(code)})')
        self.devices = mic, spk

    def _set(self, pid: 'int', vt: 'int', value: 'int') -> 'None':
        var = _PropVariant()
        var.vt = vt
        var.value = (-1 if value else 0) if vt == _VT_BOOL else value & 4294967295
        key = _PropKey(_guid(_FMTID_AEC), pid)
        code = _method(self.store, 6, ctypes.POINTER(_PropKey), ctypes.POINTER(_PropVariant))(ctypes.byref(key), ctypes.byref(var))
        if code:
            raise OSError(f'DSP ayarı {pid} kabul edilmedi ({_hr(code)})')

    def read(self) -> 'bytes':
        '''Birikmiş çıktının hepsi (yoksa b""). Hata OSError.'''

        out = bytearray()
        process = _method(self.dmo, 22, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OutputBuffer), ctypes.POINTER(wintypes.DWORD))
        while True:
            entry = _OutputBuffer()
            entry.pBuffer = self.buffer.ptr
            status = wintypes.DWORD()
            code = process(0, 1, ctypes.byref(entry), ctypes.byref(status))
            if code < 0:
                raise OSError(f'DSP okunamadı ({_hr(code)})')
            out += self.buffer.take()
            if not entry.dwStatus & _INCOMPLETE:
                return bytes(out)

    def loudness(self) -> 'float':
        '''Hoparlörün ses düzeyine göre yankının ölçekleme katsayısı (ölçümdeki düzeyde 1, sessizde 0; okunamazsa 1).'''

        if not self.volume.value:
            return 1.0
        muted, level = wintypes.BOOL(), ctypes.c_float()
        if _method(self.volume, 15, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(muted)) == 0 and muted.value:
            return 0.0
        if _method(self.volume, 8, ctypes.POINTER(ctypes.c_float))(ctypes.byref(level)):
            return 1.0
        return 10 ** ((level.value - CAL_DB) / 20)

    def close(self) -> 'None':
        if self.dmo.value:
            try:
                _method(self.dmo, 19)()
            except OSError:
                pass
        _release(self.volume)
        _release(self.store)
        _release(self.dmo)
        self.buffer.free()


_lock = threading.Lock()
_mic: 'DmoMic | None' = None
_SLOTS = 128
_played_at = [-1000000000.0] * _SLOTS
_played_peak = [0.0] * _SLOTS
_played_i = 0
_loudness = 1.0
_ducked = False

def _note_played(now: 'float', peak: 'float') -> 'None':
    global _played_i
    i = _played_i % _SLOTS
    _played_at[i], _played_peak[i] = now, peak
    _played_i += 1

def recent_peak(now: 'float | None'=None) -> 'float':
    '''Yankısı şu an mikrofona varan çalınmış sesin en yüksek tepesi (0..1, kısma dahil).'''

    now = time.monotonic() if now is None else now
    return max((p for t, p in zip(_played_at, _played_peak) if not now - t <= RECENT[0] if RECENT[0] <= RECENT[1]), default=0.0)

def _silent(now: 'float') -> 'bool':
    '''Asistanın sesi (ve yankısı) bitti mi.'''

    return now - max(_played_at) > RECENT[1]

def echo_floor() -> 'float':
    """Asistan çalarken kapının ek tabanı: DSP'nin bırakabileceği izin tahmini (Speaker.echo_floor)."""

    return min(FLOOR_CAP, FLOOR_RATIO * recent_peak() * _loudness)

def active() -> 'bool':
    '''Yankı engellemeli mikrofon açık ve işe yarıyor mu (söz kesme bu durumda açık).'''

    mic = _mic
    return mic is not None and not mic.ineffective

class DmoMic:
    '''Yankısı silinmiş mikrofon: 1024 örneklik parçalar asyncio kuyruğuna (devices._PortMic ile aynı arayüz).'''

    echo_cancelled = True
    path = 'yankı engellemeli'
    def __init__(self, loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue', mic_id: 'str'='') -> 'None':
        global _mic
        self.last_callback = time.monotonic()
        self.ineffective = False
        self.device_id, self.device_name = mic_id, ''
        self._probe = []
        self._quiet = deque(maxlen=PROBE)
        self._halt = threading.Event()
        self._ready = threading.Event()
        self._error = ''
        self._thread = threading.Thread(target=self._run, args=(loop, queue), daemon=True, name='yanki-engelleme')
        self._thread.start()
        if not self._ready.wait(OPEN_WAIT) or self._error:
            self.close()
            raise OSError(self._error or 'yankı engelleme yanıt vermedi')
        self.last_callback = time.monotonic()
        with _lock:
            old, _mic = _mic, self
        if old is not None:
            old.close()

    def _run(self, loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue') -> 'None':
        global _loudness
        with _Com():
            try:
                dsp = _Dsp(self.device_id)
            except OSError as exc:
                self._error = str(exc)
                self._ready.set()
                return
            except Exception as exc:
                self._error = f'{type(exc).__name__}: {exc}'
                self._ready.set()
                return
            _loudness = dsp.loudness()
            self.device_id, self.device_name = dsp.mic_id, dsp.mic_name
            log(f'yankı engelleme açık (Windows Voice Capture DSP, aygıt sırası mikrofon/hoparlör {dsp.devices[0]}/{dsp.devices[1]}, mikrofon “{dsp.mic_name or '?'}”, ses katsayısı {_loudness:.2f})')
            self._ready.set()
            pending = bytearray()
            volume_at = time.monotonic()
            try:
                while not self._halt.is_set():
                    data = dsp.read()
                    now = time.monotonic()
                    if data:
                        self.last_callback = now
                        pending += data
                    if now - volume_at >= VOLUME_EVERY:
                        volume_at, _loudness = now, dsp.loudness()
                    while len(pending) >= CHUNK * 2:
                        part = bytes(pending[:CHUNK * 2])
                        del pending[:CHUNK * 2]
                        self._watch(part)
                try:
                    loop.call_soon_threadsafe(_offer, queue, part)
                except RuntimeError:
                    dsp.close()
                    return
                else:
                    if len(pending) >= CHUNK * 2:
                        pass
                    time.sleep(0.01)
                    if not self._halt.is_set():
                        pass
            except OSError as exc:
                log('yankı engelleme durdu:', exc)
            dsp.close()

    def _watch(self, part: 'bytes') -> 'None':
        '''Öz denetim: asistan yüksek sesle konuşurken kalan iz çoğu parçada belirgin ve asistan susarkenki ortam
        sesinin (TV, odadaki konuşma) iki katından güçlüyse yankı silinmiyor; söz kesme kapanır, düzelince açılır.'''

        now = time.monotonic()
        samples = np.frombuffer(part, dtype=np.int16)
        level = float(np.abs(samples).max()) / 32768.0 if samples.size else 0.0
        if _silent(now):
            self._quiet.append(level)
            return
        if _ducked or recent_peak(now) * _loudness <= LOUD:
            return
        self._probe.append(level)
        if len(self._probe) < PROBE:
            return
        quarter = sorted(self._probe)[PROBE // 4]
        self._probe.clear()
        ambient = sorted(self._quiet)[len(self._quiet) // 4] if len(self._quiet) >= 16 else 0.0
        bad = quarter > max(RESIDUE, 2 * ambient)
        if bad != self.ineffective:
            self.ineffective = bad
            log(f'yankı engelleme etkisiz görünüyor (iz {quarter:.3f}, ortam {ambient:.3f}): asistan konuşurken mikrofon susar' if bad else f'yankı engelleme yeniden işe yarıyor (iz {quarter:.3f}): söz kesme açık')

    def close(self) -> 'None':
        global _mic
        with _lock:
            if _mic is self:
                _mic = None
        self._halt.set()
        if self._thread.is_alive():
            if self._thread is not threading.current_thread():
                self._thread.join(1.0)


class Speaker(_PortSpeaker):
    '''PortAudio hoparlörü + söz kesme: yankı engellemeli mikrofon açıkken kullanıcı araya girince ses kısılır.'''

    def __init__(self) -> 'None':
        self._gain = 1.0
        self.played = 0
        super().__init__()

    @property
    def echo_cancelled(self) -> 'bool':
        return active()

    @staticmethod
    def echo_floor() -> 'float':
        return echo_floor()

    def _on_play(self, take: 'bytes', now: 'float') -> 'bytes':
        self.played += len(take) // 2
        samples = np.frombuffer(take, dtype=np.int16)
        if samples.size:
            _note_played(now, float(np.abs(samples).max()) * self._gain / 32768.0)
        if self._gain != 1.0:
            take = (samples.astype(np.float32) * self._gain).astype(np.int16).tobytes()
        return take

    def duck(self, on: 'bool') -> 'None':
        global _ducked
        self._gain = DUCK if on else 1.0
        _ducked = on

    def clear(self) -> 'None':
        super().clear()
        self.duck(False)

    def close(self) -> 'None':
        self.duck(False)
        super().close()

    def warm(self) -> 'bool':
        return self.played >= WARM_SAMPLES


DISABLE_AFTER = 2
last_error = ''
_failures = 0

def disabled() -> 'bool':
    return _failures >= DISABLE_AFTER

def reset_failures() -> 'None':
    """Ayarlar'da mikrofon ya da yankı engelleme değişti: DSP yeniden denensin."""

    global _failures, last_error
    _failures, last_error = 0, ''

def note_failure(reason: 'str') -> 'bool':
    '''DSP çalışmadı: bir hata say. İkinciden sonra bu çalışmada kapalı kalır (True döner).'''

    global _failures
    _failures += 1
    log(f'yankı engelleme çalışmadı ({reason}); {_failures}. kez' + (', bu çalışmada bir daha denenmeyecek' if disabled() else ''))
    return disabled()

def open_mic(loop: 'asyncio.AbstractEventLoop', queue: 'asyncio.Queue', mic_id: 'str'='') -> 'DmoMic | None':
    '''Yankı engellemeli mikrofon ya da None (düz yol: asistan konuşurken mikrofon susar).'''

    global last_error
    if disabled():
        return
    try:
        mic = DmoMic(loop, queue, mic_id)
    except OSError as exc:
        if str(exc) != last_error:
            log('yankı engelleme açılamadı, düz mikrofon deneniyor:', exc)
        last_error = str(exc)
    last_error = ''
    return mic

# WARNING: Decompyle incomplete

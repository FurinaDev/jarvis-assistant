"""Windows izinleri: mikrofon ve kamera (Ayarlar › Gizlilik ve güvenlik).

Windows masaüstü uygulamalarına izin sorusu göstermez; izin Ayarlar'daki
anahtarlarla verilir. Durumu kayıt defterinden okuruz (yalnızca okuma),
kapalıysa tam o Ayarlar sayfasını açarız. Dosyalar, ekran ve tuş göndermek
için Windows izin istemez; bu yüzden yalnızca iki satır var.

Yalnızca Windows'ta içe aktarılır (permissions.py).
"""

from __future__ import annotations
import os
import re
import threading
import time
import winreg
from .log import log
CONSENT = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore'
CAPTURE = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Capture'
ROWS = ('microphone', 'camera')
PAGES = {'microphone': 'ms-settings:privacy-microphone', 'camera': 'ms-settings:privacy-webcam', 'sound': 'ms-settings:sound'}
REOPEN_AFTER = 45.0
_CAP = {'microphone': 'microphone', 'camera': 'webcam'}
_LABEL = {'microphone': ('Mikrofon', 'mikrofonunuza'), 'camera': ('Kamera', 'kameranıza')}
FALLBACK = {'microphone': 'Mikrofondan hiç ses gelmiyor. Mikrofon sessize alınmış ya da seçili giriş aygıtı yanlış olabilir (Ayarlar › Sistem › Ses › Giriş).', 'camera': 'Kamera açılamadı. Başka bir uygulama (Teams, Zoom, Kamera) kamerayı kullanıyor olabilir ya da bu bilgisayarda kamera yok.', 'no_mic': 'Mikrofon bulunamadı; yazarak konuşabilirsin. Mikrofon takılınca kendiliğinden açılır.'}
MIC_PROBLEMS = {'blocked': ('MİKROFON ERİŞİLEMİYOR', "Mikrofon var ama Windows ya da bir güvenlik programı JARVIS'in onu kullanmasını engelliyor. Windows'ta Ayarlar › Gizlilik ve güvenlik › Mikrofon'da üç anahtar da açık olmalı: “Mikrofon erişimi”, “Uygulamaların mikrofonunuza erişmesine izin verin” ve sayfanın altındaki “Masaüstü uygulamalarının mikrofonunuza erişmesine izin verin” (üst çubuktaki kırmızı rozete basınca o sayfa açılır). Antivirüs (Kaspersky, ESET, Bitdefender, Norton…) kullanıyorsan “mikrofon koruması”nda JARVIS'e izin ver. Engel kalkınca mikrofon kendiliğinden açılır."), 'busy': ('MİKROFON MEŞGUL', 'Mikrofonu şu an başka bir uygulama (Discord, Zoom, Teams, OBS…) tek başına kullanıyor. O uygulamayı kapatınca JARVIS mikrofonu kendiliğinden açar.'), 'none': ('MİKROFON YOK', 'Bu bilgisayarda etkin bir mikrofon bulunamadı; yazarak konuşabilirsin. Mikrofon takılınca kendiliğinden açılır.'), 'unreachable': ('MİKROFON AÇILAMADI', "Mikrofon var ama açılamadı. Windows gizlilik ayarı, bir güvenlik programı ya da ses sürücüsü engelliyor olabilir: Windows'ta Ayarlar › Gizlilik ve güvenlik › Mikrofon'daki anahtarlara ve antivirüsün mikrofon korumasına bak. JARVIS'in AYARLAR › SES ekranındaki MİKROFONU DENE hangi aygıtın denendiğini gösterir. Düzelince mikrofon kendiliğinden açılır.")}
_DENIED = re.compile('0x80070005|access (?:is )?denied|erişim engellendi', re.I)
_BUSY = re.compile('0x8889000A|PaErrorCode -9985|device unavailable', re.I)

def mic_problem(errors: 'list[str]') -> 'str':
    """Mikrofonun açılamama nedeni: blocked | busy | none | unreachable. errors: DSP'nin ve PortAudio'nun hata metinleri."""

    text = ' '.join((e for e in errors if e))
    try:
        if blocker('microphone') or _DENIED.search(text):
            return 'blocked'
        if not has_microphone():
            return 'none'
    except Exception as exc:
        log('mikrofon durumu okunamadı', exc)
    if _BUSY.search(text):
        return 'busy'
    return 'unreachable'

_last_opened: 'dict[str, float]' = {}
_lock = threading.Lock()

def _value(hive: 'int', sub: 'str') -> 'str | None':
    '''Anahtarın "Value" değeri (Allow | Deny); anahtar ya da değer yoksa None.'''

    try:
        with winreg.OpenKey(hive, sub) as key:
            return str(winreg.QueryValueEx(key, 'Value')[0])
    except OSError:
        return

def blocker(kind: 'str') -> 'str | None':
    '''Hangi anahtar kapalı: device (bütün cihaz) | apps (uygulamalar) | desktop (masaüstü uygulamaları).'''

    cap = _CAP.get(kind)
    if cap is None:
        return
    base = f'{CONSENT}\\{cap}'
    if _value(winreg.HKEY_LOCAL_MACHINE, base) == 'Deny':
        return 'device'
    if _value(winreg.HKEY_CURRENT_USER, base) == 'Deny':
        return 'apps'
    if 'Deny' in (_value(winreg.HKEY_CURRENT_USER, base + '\\NonPackaged'), _value(winreg.HKEY_LOCAL_MACHINE, base + '\\NonPackaged')):
        return 'desktop'

def has_microphone() -> 'bool':
    '''Etkin bir giriş aygıtı var mı. Kayıt anlıktır: sonradan takılan mikrofonu da görür.'''

    seen = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURE) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as dev:
                            state = int(winreg.QueryValueEx(dev, 'DeviceState')[0])
                    except OSError:
                        continue
                finally:
                    pass
                seen += 1
                if state & 15 != 1:
                    continue
                return True
    except OSError:
        pass
    if seen:
        return False
    try:
        from .audio import devices
    except Exception:
        return True
    return devices.input_available()

def status(kind: 'str') -> 'str':
    '''granted | denied | none (mikrofon hiç takılı değil).'''

    try:
        if blocker(kind):
            return 'denied'
        if kind == 'microphone' and not has_microphone():
            return 'none'
    except Exception as exc:
        log('izin durumu okunamadı', kind, exc)
    return 'granted'

def statuses() -> 'dict[str, str]':
    return {kind: status(kind) for kind in ROWS}

def media_status(media: 'str') -> 'str':
    '''permissions.media_status karşılığı: "audio" → mikrofon, "video" → kamera.'''

    kind = 'microphone' if media == 'audio' else 'camera'
    try:
        return 'denied' if blocker(kind) else 'granted'
    except Exception:
        return 'unknown'

def open_settings(kind: 'str', force: 'bool'=False) -> 'bool':
    """Ayarlar'da ilgili sayfayı açar (kendiliğinden açılışta kısa sürede tekrar açmaz)."""

    page = PAGES.get(kind)
    if page is None:
        return False
    if kind == 'microphone' and not blocker(kind) and not has_microphone():
        page = PAGES['sound']
    with _lock:
        now = time.monotonic()
        if not force:
            if now - _last_opened.get(kind, -REOPEN_AFTER) < REOPEN_AFTER:
                return False
        _last_opened[kind] = now
    try:
        os.startfile(page)
    except OSError as exc:
        log('ayarlar sayfası açılamadı', kind, exc)
        return False
    log('izin sayfası açıldı', _LABEL.get(kind, (kind,))[0])
    return True

def request(kind: 'str') -> 'str':
    '''Windows soru sormaz: izin kapalıysa (ya da mikrofon yoksa) doğrudan Ayarlar sayfası açılır.'''

    now = status(kind)
    if now != 'granted':
        open_settings(kind, force=True)
    return now

def explain(kind: 'str') -> 'str':
    label, whose = _LABEL.get(kind, (kind, ''))
    step = {'device': f'en üstteki “{label} erişimi” anahtarını aç', 'apps': f'“Uygulamaların {whose} erişmesine…” anahtarını aç'}.get(blocker(kind) or '', f'sayfanın altındaki “Masaüstü uygulamalarının {whose} erişmesine…” anahtarını aç')
    tail = 'Anahtarı açınca JARVIS mikrofonu kendiliğinden açar.' if kind == 'microphone' else 'Sonra kamerayı yeniden aç.'
    return f"Ayarlar'da {label} gizlilik sayfasını açtım: {step}. {tail}"


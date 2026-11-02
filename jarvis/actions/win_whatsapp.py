'''WhatsApp (Windows): Mağaza'daki WhatsApp masaüstü uygulaması (WinUI kabuğunda WebView2 ile WhatsApp Web).

Kişiler Mac'le ortak yerde (whatsapp.py: JARVIS'in kayıtlı WhatsApp kişileri). Windows'ta JARVIS ne WhatsApp'ın ne
telefonun rehberini görebilir: bulunamayan kişide model kullanıcıya nedenini söyler (testçiler bunu hata sanıyordu,
11 Ekim), numarayı bir kez ister ve ad + numarayla yeniden gönderir; numara o adla kaydedilir. Ad eşleşmesi burada
sıkı: tam ad, takma ad ya da tam sözcük ("Ali" → "Ali Yılmaz"); "Can" kayıtlı "Ercan"a gitmez, "Ercan'ı mı?" diye
sorulur. "Ahmet'e" gibi ekli ad ekiyle kaydedilmez (bare_name).

Sohbet whatsapp://send?phone=…&text=… ile mesaj yazılmış olarak açılır. "Gönder"de WhatsApp'ın Gönder düğmesine
UI Automation ile basılır (klavye, odak ve pencereyi öne getirme gerekmez; Enter denemesinde öne getirme ve odak
tutmadı, tuş kullanıcının o an geçtiği başka bir uygulamaya da gidebilirdi). Basmadan önce şunlar doğrulanır:
  - Sohbeti açmadan önce WhatsApp'ın penceresi gerçekten okundu ve hiçbir yazma kutusunda bu metin yok. Pencere
    kapalıysa (tepside) önce gösterilir; okunamazsa gönderilmez. Aynı metin zaten bir kutudaysa (başka bir
    sohbetin ya da önceki "hazırla"nın taslağı; yeni sohbet yüklenmeden o kutu bulunur) otomatik basılmaz.
  - Açılan sohbetin yazma kutusunun metni mesaja TAM eşit. WhatsApp bağlantıdaki metni kutudaki taslağın YANINA
    ekliyor (denendi): sohbette kullanıcının yarım bir taslağı varsa ikisi birleşir, o zaman gönderilmez.
  - Ekranda adı tam "Gönder"/"Send" olan tek bir düğme var (sohbet başlığındaki "…gönderin" sayılmaz).
Sonra kutunun boşaldığı, en az bir kutu okunarak doğrulanır. Doğrulanamayan hiçbir durumda "gönderildi" denmez;
basılmamışsa "GÖNDERİLMEDİ" denir.

Sonuç metinlerinde ve günlükte telefon numarası yoktur (Alp videolarında ekranı paylaşıyor).
'''

from __future__ import annotations
import ctypes
import os
import re
import time
import urllib.parse
import winreg
from ctypes import wintypes
import psutil
from ..log import log
from .whatsapp import (bare_name, find_contact, _normalize_phone, save_whatsapp_contact)
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_PACKAGES = 'Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\CurrentVersion\\AppModel\\Repository\\Packages'
SHOW_WAIT = 12.0
OPEN_WAIT = 15.0
SENT_WAIT = 4.0
SEND_NAMES = {'Gönder', 'Send'}
_INVISIBLE = re.compile('[​-‏‪-‮⁠-⁤﻿]')

def installed() -> 'bool':
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES) as key:
            return any((winreg.EnumKey(key, i).startswith('5319275A.WhatsAppDesktop_') for i in range(winreg.QueryInfoKey(key)[0])))
    except OSError:
        return False

def _norm(text: 'str') -> 'str':
    '''Karşılaştırma için: görünmez işaretler atılmış, boşlukları sadeleşmiş metin (WhatsApp satır sonlarını
    ve boşlukları değiştirebilir).'''

    return ' '.join(_INVISIBLE.sub('', text or '').split())

def _class(hwnd: 'int') -> 'str':
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _pid(hwnd: 'int') -> 'int':
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

def _windows() -> 'tuple[int, int] | None':
    """(WhatsApp'ın görünür ana penceresi, içindeki WebView2 penceresi) ya da None."""

    pids = {p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'whatsapp.root.exe'}
    if not pids:
        return
    tops = []
    _user32.EnumWindows(_EnumProc((lambda h, _: tops.append(h) or True)), 0)
    for main in tops:
        if _pid(main) not in pids:
            continue
        if _class(main) != 'WinUIDesktopWin32WindowClass':
            continue
        if _user32.IsWindowVisible(main):
            kids = []
            _user32.EnumChildWindows(main, _EnumProc((lambda h, _: kids.append(h) or True)), 0)
            host = next((h for h in kids if _class(h).startswith('Chrome_WidgetWin')), None)
            if host:
                return main, host

class _Scan:
    """WhatsApp'ın yazı kutularının bir okuması: kaç kutu okundu, mesaja tam eşit kutu, fazlasıyla içeren var mı."""

    def __init__(self, uia, target: 'str') -> 'None':
        self.main = self.host = None
        self.read, self.exact, self.partial = 0, None, False
        found = _windows()
        if not found:
            return
        self.main, self.host = found
        for el in uia.edits(self.host):
            value = el.value()
            if value is None:
                el.release()
                continue
            self.read += 1
            text = _norm(value)
            if text == target and self.exact is None:
                self.exact = el
                continue
            if target and target in text:
                self.partial = True
            el.release()

    def release(self) -> 'None':
        if self.exact:
            self.exact.release()
            self.exact = None


def _show(uia, target: 'str') -> '_Scan':
    """Pencere kapalıysa (tepside) ya da henüz okunmuyorsa WhatsApp'ı gönderme bağlantısı OLMADAN gösterir
    ve okunana kadar bekler: açmadan önceki denetim gerçek bir okumaya dayansın."""

    scan = _Scan(uia, target)
    if scan.read:
        return scan
    os.startfile('whatsapp:')
    end = time.monotonic() + SHOW_WAIT
    last = -1
    while time.monotonic() < end:
        time.sleep(0.5)
        scan.release()
        scan = _Scan(uia, target)
        if scan.read and scan.read == last:
            return scan
        last = scan.read
    return scan

def _press_send(uia, scan: '_Scan', target: 'str') -> 'bool':
    """WhatsApp'ın Gönder düğmesine basar; yalnızca yazma kutusu hâlâ mesaja tam eşitken ve tam olarak bir Gönder
    düğmesi varken. Basılamadıysa False (hiçbir şey gönderilmedi)."""

    if _norm(scan.exact.value() or '') != target:
        return False
    buttons = uia.buttons(scan.host, SEND_NAMES)
    try:
        if len(buttons) == 1 and buttons[0].enabled():
            for button in buttons:
                button.release()
            return
    finally:
        for button in buttons:
            button.release()
    try:
        log(f'whatsapp: Gönder düğmesi kullanılamadı ({len(buttons)} adet)')
    finally:
        for button in buttons:
            button.release()
    return False

def _open_and_send(phone: 'str', message: 'str', send_now: 'bool') -> 'str':
    '''Sonuç: "taslak" | "gönderildi" | "okunamadı" | "taslak-var" | "taslak-yok" | "birleşti" | "basılamadı" |
    "duruyor" | "belirsiz".'''

    from ..win_uia import Uia
    target = _norm(message)
    with Uia() as uia:
        before = _show(uia, target)
        try:
            if not before.read:
                before.release()
                return 'okunamadı'
        finally:
            before.release()
        try:
            if before.exact:
                before.release()
                return 'taslak-var'
        finally:
            before.release()
        try:
            main = before.main
        finally:
            before.release()
        url = f'whatsapp://send?phone={phone}&text={urllib.parse.quote(message.strip())}'
        os.startfile(url)
        end = time.monotonic() + OPEN_WAIT
        scan, merged_at = None, 0.0
        while time.monotonic() < end:
            time.sleep(0.4)
            scan = _Scan(uia, target)
            if scan.exact:
                break
            if scan.partial:
                merged_at = merged_at or time.monotonic()
                if time.monotonic() - merged_at > 2.0:
                    return 'birleşti'
            scan.release()
            scan = None
        if scan is None:
            return 'taslak-yok'
        try:
            if not send_now:
                scan.release()
                return 'taslak'
        finally:
            scan.release()
        try:
            if scan.main != main or not _press_send(uia, scan, target):
                scan.release()
                return 'basılamadı'
        finally:
            scan.release()
        try:
            end = time.monotonic() + SENT_WAIT
            while time.monotonic() < end:
                time.sleep(0.3)
                value = scan.exact.value()
                if value is not None and value.strip():
                    if _norm(value) == target:
                        continue
                after = _Scan(uia, target)
                try:
                    if after.read and not after.exact and not after.partial:
                        after.release()
                        scan.release()
                        return 'gönderildi'
                finally:
                    after.release()
                after.release()
        finally:
            scan.release()
        scan.release()
    return 'duruyor'

def send_whatsapp_message(message: 'str', phone_number: 'str'='', recipient_name: 'str'='', send_now: 'bool'=False, app_target: 'str'='auto') -> 'str':
    if not message or not message.strip():
        return 'Hata: mesaj boş olamaz.'
    if not installed():
        return "Hata: WhatsApp masaüstü uygulaması kurulu değil. Kullanıcı Microsoft Store'dan WhatsApp'ı kurup oturum açmalı."
    phone = ''
    if phone_number and phone_number.strip():
        try:
            phone = _normalize_phone(phone_number)
        except ValueError as exc:
            return f'Hata: {exc}'
    asked = (recipient_name or '').strip()
    name = bare_name(asked)
    if name and phone:
        contact, _similar = find_contact(asked)
        if contact and contact.get('_stripped'):
            contact = None
        aliases = ', '.join((str(a) for a in (contact or {}).get('aliases', []) or []))
        save_whatsapp_contact(name, phone, aliases=aliases)
    elif name:
        contact, similar = find_contact(asked)
        if contact:
            try:
                phone = _normalize_phone(str(contact.get('value', '')))
                name = str(contact.get('display_name', name)).strip() or name
            except ValueError:
                phone = ''
        elif similar:
            shown = ', '.join(similar[:5])
            return f"'{name}' adında tam eşleşen kayıtlı kişi yok; benzer kayıtlı adlar: {shown}. Kullanıcıya hangisini kastettiğini sor; söyleyince recipient_name'i tam o adla yeniden çağır. Hiçbir şey açılmadı."
        if not phone:
            return f"'{name}' JARVIS'in kayıtlı kişileri arasında yok; mesaj henüz gönderilmedi. Bu bir arıza değil: Windows'ta JARVIS, WhatsApp'ın ve telefonun rehberini göremiyor, bu yüzden her kişinin numarasını bir kez öğrenmesi gerekiyor. Kullanıcıya bunu tek cümleyle söyle ve bu kişinin numarasını iste (yazarak da verebilir). Numarayı verince mesajı phone_number VE recipient_name ile yeniden gönder: numara bu adla kaydedilir, bir dahaki sefere sorulmaz. Numarayı sesli tekrar etme."
    if not phone:
        return 'Hata: WhatsApp mesajı için kişi adı ya da telefon numarası gerekli.'
    label = name or 'verilen numara'
    try:
        outcome = _open_and_send(phone, message, bool(send_now))
    except OSError as exc:
        code = getattr(exc, 'winerror', None) or type(exc).__name__
        log(f'whatsapp: {label} · açılamadı ({code})')
        return f'Hata: WhatsApp açılamadı (Windows hata {code}). Mesaj GÖNDERİLMEDİ.'
    log(f'whatsapp: {label} · {outcome}')
    if outcome == 'taslak':
        return f"WhatsApp'ta {label} sohbeti mesaj yazılmış olarak açıldı. Göndermek için kullanıcı WhatsApp'ta Gönder'e basar (taslak açıkken sesle 'gönder' güvenle doğrulanamaz)."
    if outcome == 'gönderildi':
        return f'WhatsApp üzerinden {label} kişisine mesaj gönderildi (doğrulandı).'
    if outcome == 'okunamadı':
        return "Hata: WhatsApp'ın penceresi okunamadı (oturum kapalı ya da uygulama yanıt vermiyor olabilir); doğrulayamadığım için göndermedim. Mesaj GÖNDERİLMEDİ."
    if outcome == 'taslak-var':
        return "Hata: bu mesaj WhatsApp'ta zaten bir yazma kutusunda (taslak olarak) duruyor; hangi sohbette olduğunu doğrulayamadığım için otomatik göndermedim. Kullanıcı o taslağı WhatsApp'ta kendisi göndersin ya da silsin. Mesaj GÖNDERİLMEDİ."
    if outcome == 'taslak-yok':
        return f"Hata: WhatsApp'ta {label} sohbeti açılmadı ya da mesaj yazma kutusunda görünmedi (numara WhatsApp'ta olmayabilir, WhatsApp'ta oturum kapalı olabilir ya da uygulama yanıt vermedi). Mesaj GÖNDERİLMEDİ."
    if outcome == 'birleşti':
        return f"Hata: WhatsApp'ta {label} sohbetinde önceden yazılmış başka bir metin vardı; WhatsApp mesajı onun yanına ekledi. İkisi birlikte gitmesin diye göndermedim. Kullanıcı yazma kutusunu temizlesin, sonra yeniden dene. Mesaj GÖNDERİLMEDİ."
    if outcome == 'basılamadı':
        return f"Hata: WhatsApp'ta {label} sohbeti mesajla açıldı ama Gönder düğmesine basamadım. Mesaj taslak olarak duruyor, GÖNDERİLMEDİ. Kullanıcı WhatsApp'ta Gönder'e basabilir."
    if outcome == 'duruyor':
        return f"Hata: WhatsApp'ta {label} sohbetinde Gönder'e bastım ama mesaj yazma kutusunda duruyor; gönderildiğini doğrulayamadım. Kullanıcıya WhatsApp'a bakmasını söyle."
    return f"Hata: WhatsApp'ta {label} için sonuç belirsiz. Kullanıcıya WhatsApp'a bakmasını söyle."

# WARNING: Decompyle incomplete

'''Telefon bağlantısı (Windows): phone.py'nin Mac'e özgü parçalarının karşılıkları.

Windows'ta telefon bağlantısı yalnızca aynı Wi-Fi'da ve yalnızca iPhone uygulamasıyla (Alp, 13 Ekim 2026; Android
uygulaması yakında). Cloudflare tüneli (evin dışından bağlanma) Windows'ta henüz yok: cloudflared pakette değil.
- Bonjour: Mac'te /usr/bin/dns-sd; burada python-zeroconf. iPhone uygulaması bilgisayarı aynı Wi-Fi'da böyle bulur
  (_jarvis._tcp; TXT'de anahtar kimliği, adres ve bağlantı noktası, Mac'teki gibi).
- Bilgisayarın adı: Mac'te scutil; burada Windows'taki ad.
- Ağ profili: Wi-Fi Windows'ta "Genel" sayılıyorsa güvenlik duvarı gelen bağlantıyı çoğunlukla engeller; ekranda
  söylenir (salt okunur, hiçbir ayar değiştirilmez).
'''

from __future__ import annotations
import socket
import subprocess
from .log import log
_CREATE_NO_WINDOW = 134217728

def computer_name() -> 'str':
    """Windows'taki bilgisayar adı (Ayarlar › Sistem › Hakkında), iPhone'da böyle görünür."""

    return (socket.gethostname() or 'JARVIS')[:60]

def network_category(ip: 'str') -> 'str':
    '''Bu adresin bağlı olduğu ağın Windows'taki profili: Public | Private | DomainAuthenticated | "" (bilinmiyor).'''

    if not ip or ip.startswith('127.'):
        return ''
    script = f"$i = (Get-NetIPAddress -IPAddress '{ip}' -ErrorAction SilentlyContinue).InterfaceIndex; if ($i) {{ (Get-NetConnectionProfile -InterfaceIndex $i -ErrorAction SilentlyContinue).NetworkCategory }}"
    try:
        done = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, timeout=8, creationflags=_CREATE_NO_WINDOW)
        if done.stdout.strip():
            return done.stdout.decode('utf-8', 'replace').strip().splitlines()[0].strip()
        return ''
    except (OSError, subprocess.SubprocessError, IndexError):
        return ''

class Advert:
    '''Bonjour duyurusu (python-zeroconf). start ve stop aynı nesneyle; hata uygulamayı durdurmaz.'''

    def __init__(self) -> 'None':
        self._zc = None
        self._info = None

    def start(self, service: 'str', name: 'str', ip: 'str', port: 'int', txt: 'dict[str, str]') -> 'None':
        try:
            from zeroconf import (IPVersion, ServiceInfo, Zeroconf)
            kind = f'{service}.local.'
            host = ''.join((ch if ch.isalnum() or ch == '-' else '-' for ch in name)).strip('-') or 'jarvis'
            info = ServiceInfo(kind, f'{name}.{kind}', addresses=[socket.inet_aton(ip)], port=port, properties=txt, server=f'{host}.local.')
            zc = Zeroconf(interfaces=[ip], ip_version=IPVersion.V4Only)
            zc.register_service(info, allow_name_change=True)
            self._zc, self._info = zc, info
            return
        except Exception as exc:
            log('telefon: Bonjour duyurusu açılamadı:', exc)
            self.stop()

    def stop(self) -> 'None':
        zc, info, self._zc, self._info = self._zc, self._info, None, None
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception:
            pass
        try:
            zc.close()
        except Exception:
            return



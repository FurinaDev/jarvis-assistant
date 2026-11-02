"""Sistem bilgisi (Windows): sys_info aracı ve Sistem ayrıntısındaki bilgisayar bilgileri.

Mac'teki sys_info.py ile aynı sorgular ve aynı satır biçimleri; pmset, airport, df gibi Mac komutlarının yerine
psutil, kayıt defteri ve `netsh wlan`. Tarih Türkçe yazılır.
"""

from __future__ import annotations
import ctypes
import datetime as dt
import os
import platform
import re
import socket
import subprocess
import winreg
import psutil
from ..details import TR_DAYS, TR_MONTHS
_NO_WINDOW = 134217728

def sys_info(query: 'str') -> 'str':
    query = query.lower().strip()
    results = []
    if query in ('battery', 'pil', 'all'):
        results.append(_battery())
    if query in ('cpu', 'işlemci', 'all'):
        results.append(_cpu())
    if query in ('ram', 'bellek', 'memory', 'all'):
        results.append(_ram())
    if query in ('disk', 'depolama', 'all'):
        results.append(_disk())
    now = dt.datetime.now()
    if query in ('time', 'saat', 'zaman', 'all'):
        results.append(f'Saat: {now:%H:%M:%S}')
    if query in ('date', 'tarih', 'all'):
        results.append(f'Tarih: {now.day} {TR_MONTHS[now.month]} {now.year}, {TR_DAYS[now.weekday()]}')
    if query in ('network', 'ağ', 'wifi', 'all'):
        results.append(_network())
    if not results:
        results.append(f'Bilinmeyen sorgu: {query}. battery/cpu/ram/disk/time/date/network/all kullanın.')
    return '\n'.join((r for r in results if r))

def _battery() -> 'str':
    bat = psutil.sensors_battery()
    if bat is None:
        return 'Bu bilgisayarda pil yok; prize bağlı çalışıyor.'
    if bat.power_plugged:
        return f'Pil: %{bat.percent:.0f} — Şarj oluyor'
    left = bat.secsleft
    if isinstance(left, (int, float)):
        if 0 < left < 1000000:
            h, m = divmod(int(left) // 60, 60)
            return f'Pil: %{bat.percent:.0f} — Pilde, kalan yaklaşık {f'{h} sa ' if h else ''}{m} dk'
    return f'Pil: %{bat.percent:.0f} — Pilde'

def _cpu() -> 'str':
    usage = psutil.cpu_percent(interval=0.5)
    model = _cpu_name()
    if model:
        return f'CPU: %{usage:.1f} kullanım — {psutil.cpu_count(logical=True)} çekirdek' + f' ({model})'
    return None + ''

def _ram() -> 'str':
    vm = psutil.virtual_memory()
    return f'RAM: {vm.used / 1073741824:.1f}GB / {vm.total / 1073741824:.1f}GB kullanımda (%{vm.percent:.0f})'

def system_drive() -> 'str':
    '''Windows'un kurulu olduğu sürücü ("C:\\").'''

    return os.environ.get('SystemDrive', 'C:') + '\\'

def _disk() -> 'str':
    root = system_drive()
    du = psutil.disk_usage(root)
    gb = 1073741824
    line = f'Disk ({root[:2]}): {du.used / gb:.1f}GB kullanıldı, {du.free / gb:.1f}GB boş (toplam {du.total / gb:.1f}GB)'
    others = []
    for part in psutil.disk_partitions(all=False):
        if 'fixed' not in part.opts or part.mountpoint.upper() == root.upper():
            continue
        try:
            others.append(f'{part.mountpoint[:2]} {psutil.disk_usage(part.mountpoint).free / gb:.0f}GB boş')
        except OSError:
            continue
    if others:
        return line + f'; ayrıca {', '.join(others)}'
    return None + ''

def _network() -> 'str':
    '''Wi-Fi adı ve sinyal (netsh), yoksa kablolu bağlantı ve yerel IP.'''

    text = _run(['netsh', 'wlan', 'show', 'interfaces'])
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields.setdefault(key.strip().lower(), value.strip())
    state = fields.get('state') or fields.get('durum') or ''
    ssid = fields.get('ssid', '')
    signal = fields.get('signal') or fields.get('sinyal') or ''
    connected = bool(re.search('connected|bağlı|bağlandı', state, re.I)) and not re.search('dis|kesil', state, re.I)
    if connected and ssid:
        strength = re.sub('\\D', '', signal)
        if strength:
            return f'WiFi: {ssid} bağlı' + f' (sinyal %{strength})'
        return None + ''
    if connected and re.search('location|konum', text, re.I):
        return 'WiFi bağlı; ağ adını okumak için Windows Konum izni gerekiyor.'
    ip = _local_ip()
    wired = any((stats.isup and re.search('ethernet', name, re.I) for name, stats in psutil.net_if_stats().items()))
    if ip:
        return f'Ağ: {'kablolu bağlantı, ' if wired else ''}IP {ip}'
    return 'Ağ bağlantısı bulunamadı.'

def _local_ip() -> 'str':
    '''Varsayılan yolun yerel adresi (paket gönderilmez; UDP soketi yalnızca yönü seçer).'''

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            ip = s.getsockname()[0]
        if ip.startswith(('127.', '169.254.')):
            return ''
    except OSError:
        return ''
    return ip

def _run(cmd: 'list[str]') -> 'str':
    """Konsol programının çıktısı: önce UTF-8, olmazsa sistemin OEM kod sayfası (Türkçe'de 857)."""

    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=5, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ''
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode(f'cp{ctypes.windll.kernel32.GetOEMCP()}', 'replace')

def _reg(path: 'str', name: 'str') -> 'str':
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return ''

def _cpu_name() -> 'str':
    name = _reg('HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0', 'ProcessorNameString')
    return re.sub('\\s+', ' ', name.replace('(R)', '').replace('(TM)', '')).strip()

_EDITIONS = {'Professional': 'Pro', 'Core': 'Home', 'CoreSingleLanguage': 'Home', 'CoreCountrySpecific': 'Home', 'Enterprise': 'Enterprise', 'Education': 'Education', 'ProfessionalWorkstation': 'Pro for Workstations'}

def host_info() -> 'dict[str, str]':
    '''{"os", "cpu", "model", "name"}. ProductName kullanılmaz: Windows 11'de de "Windows 10 Pro" diyor.'''

    edition = _EDITIONS.get(platform.win32_edition() or '', platform.win32_edition() or '')
    display = _reg('SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion', 'DisplayVersion')
    maker = _reg('HARDWARE\\DESCRIPTION\\System\\BIOS', 'SystemManufacturer')
    product = _reg('HARDWARE\\DESCRIPTION\\System\\BIOS', 'SystemProductName')
    model = ' '.join((p for p in (maker, product) if p if 'o.e.m' not in p.lower() if 'default' not in p.lower()))
    return {'os': ' '.join((p for p in ('Windows', platform.release(), edition, display) if p)), 'cpu': _cpu_name() or platform.processor(), 'model': model, 'name': socket.gethostname()}

# WARNING: Decompyle incomplete

"""PowerShell (Windows): shell_run aracı ve araçların ortak çalıştırıcısı.

Windows PowerShell 5.1 tam yolundan (PATH'e güvenilmez), profilsiz ve etkileşimsiz açılır; komut
-EncodedCommand ile gider (tırnaklama sorunu yok), çıktı UTF-8 okunur (yoksa Türkçe harfler 857 kod
sayfasında bozuluyor). Pencere açılmaz (JARVIS konsolsuz). Zaman aşımında süreç ağacının tamamı kapatılır:
subprocess.run'ın zaman aşımı, boruyu tutan torun süreç yüzünden Windows'ta işlemiyor.
"""

from __future__ import annotations
import base64
import os
import re
import subprocess
from pathlib import Path
import psutil
POWERSHELL = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
_PREAMBLE = "$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "

def run_powershell(script: 'str', timeout: 'float'=20, cwd: 'str | None'=None) -> 'tuple[int | None, str]':
    '''(çıkış kodu, stdout+stderr metni). Zaman aşımında (None, o ana kadarki çıktı).'''

    encoded = base64.b64encode((_PREAMBLE + script).encode('utf-16-le')).decode('ascii')
    try:
        proc = subprocess.Popen([POWERSHELL, '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc:
        return -1, f'PowerShell açılamadı: {exc}'
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            out = b''
        return None, (out or b'').decode('utf-8', 'replace')
    return proc.returncode, out.decode('utf-8', 'replace')

TIMEOUT = 25
MAX_OUTPUT = 800
_WRITE_CMDS = {'set-acl', 'copy-item', 'move-item', 'remove-item', 'rename-item', 'cp', 'mi', 'mv', 'rd', 'ri', 'rm', 'cpi', 'del', 'ren', 'rni', 'copy', 'move', 'sudo', 'cacls', 'erase', 'rmdir', 'runas', 'xcopy', 'attrib', 'icacls', 'takeown', 'robocopy'}
_BLOCKED = [('\\bshutdown\\b|\\b(stop|restart)-computer\\b', 'bilgisayarı kapatma/yeniden başlatma'), ('\\b(format-volume|clear-disk|initialize-disk|remove-partition|diskpart)\\b|(^|[;&|]\\s*)format\\s+[a-z]:', 'disk biçimlendirme'), ('\\bbcdedit\\b|\\b(vssadmin|wbadmin)\\s+delete\\b|\\bcipher\\s+/w\\b', 'önyükleme ve yedek ayarı'), ('\\breg(\\.exe)?\\s+(delete|add|import)\\b|\\b(set|new|remove)-itemproperty\\b', 'kayıt defterine yazma'), ('\\bset-executionpolicy\\b|-verb\\s+runas\\b', 'güvenlik ilkesi / yönetici yetkisi'), ('\\b(set|add)-mppreference\\b|\\bnetsh\\s+advfirewall\\b', 'Defender / güvenlik duvarı ayarı'), ('\\bclear-recyclebin\\b|\\bremove-appxpackage\\b', 'geri dönüşümsüz silme'), ('\\b(stop-process|taskkill)\\b.*\\b(explorer|csrss|winlogon|lsass|wininit|svchost|dwm)\\b', 'sistem süreci'), ('\\|\\s*iex\\b|\\binvoke-expression\\b', 'invoke-expression')]
_WRAP = "$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')); try {{ & ([ScriptBlock]::Create($c)) 2>&1 | Out-String -Width 160 }} catch {{ 'HATA: ' + $_.Exception.Message }}"

def shell_run(command: 'str', timeout: 'int'=TIMEOUT) -> 'str':
    command = (command or '').strip()
    if not command:
        return 'Komut belirtilmedi.'
    for statement in re.split('[;|&\\n]+', command):
        words = statement.split()
        if not words:
            continue
        if words[0].lower() in _WRITE_CMDS:
            return 'Güvenlik: Dosya veya yetki değiştiren komutlar doğrudan çalıştırılmıyor. Daha güvenli ve dar kapsamlı bir komut dene.'
    low = command.lower()
    for pattern, label in _BLOCKED:
        if re.search(pattern, low):
            return f'Güvenlik: Bu komut engellendi → {label}'
    b64 = base64.b64encode(command.encode('utf-8')).decode('ascii')
    code, out = run_powershell(_WRAP.format(b64=b64), timeout=timeout, cwd=str(Path.home()))
    if code is None:
        return f'Komut zaman aşımına uğradı ({timeout}s).'
    if code == -1:
        return f'Hata: {out}'
    output = _clean(out)
    if not output:
        return 'Komut başarıyla çalıştı (çıktı yok).'
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + '\n... (çıktı kısaltıldı)'
    return output

def _clean(text: 'str') -> 'str':
    '''PowerShell hata kaydının gürültüsü ("At line:1 char:1", "+ ~~~", "+ CategoryInfo") atılır.'''

    kept, skipping = [], False
    for line in text.splitlines():
        if re.match('^At line:\\d+ char:\\d+', line) or re.match('^\\s*\\+ (CategoryInfo|FullyQualifiedErrorId)', line):
            skipping = True
            continue
        if skipping:
            if line.lstrip().startswith('+'):
                continue
        skipping = False
        kept.append(line.rstrip())
    return '\n'.join(kept).strip()

def _kill_tree(pid: 'int') -> 'None':
    try:
        root = psutil.Process(pid)
        for p in [*root.children(recursive=True), root]:
            try:
                p.kill()
            except psutil.Error:
                continue
    except psutil.Error:
        return


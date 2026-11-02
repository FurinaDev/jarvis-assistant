'''Güncelleme: yeni sürüm var mı, indir, doğrula, kur (yalnızca paketlenmiş uygulamada: JARVIS.app, Windows kurulumu).

Kanal FEED: GitHub'daki jarvis deposunun sürüm listesi. Depoda eski (V2/V3) sürümler de var: yalnızca bu işletim
sisteminin dosyası olan (Mac: JARVIS-<sürüm>.dmg, Windows: JARVIS-<sürüm>-Windows-Setup.exe), taslak ve ön sürüm
olmayan en yeni sürüm alınır. Tek bir sürümün JSON'u ("/releases/latest") ya da aynı bilgileri veren küçük bir JSON
({"version", "title", "notes", "url", "size", "sha256"}) da okunur. FEED boşken özellik kapalıdır, Hakkında "yakında"
der. (Deneme için JARVIS_UPDATE_FEED ortam değişkeni.) İndirilen dosyanın SHA-256'sı GitHub'ın verdiği özetle
(asset "digest") karşılaştırılır.

Windows'ta kurulum win_update.py'de (sessiz kurulum, JARVIS kapanınca). Mac'te kurulum:
  1. DMG önbelleğe indirilir (ilerleme ekrana gider).
  2. İçindeki JARVIS.app denetlenir: imza sağlam, ekip kimliği bizim Apple geliştirici kimliğimiz
     (TEAM_ID), paket kimliği aynı, Apple onaylı (spctl), sürümü duyurulanla aynı. Tutmayan hiçbir şey kurulmaz.
  3. Uygulama önbelleğe kopyalanır; küçük bir betik JARVIS kapanınca eskisini yenisiyle değiştirir ve açar.
     Değiştirme yarıda kalırsa eskisi geri konur.
İmza aynı olduğu için macOS izinleri, Anahtar Zinciri erişimi, ayarlar ve veriler korunur.
'''

from __future__ import annotations
import hashlib
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
import requests
from . import VERSION, paths
from .log import log
FEED = 'https://api.github.com/repos/alpunlu12-commits/jarvis/releases?per_page=30'
TEAM_ID = '7346LFSJVY'
BUNDLE_ID = 'com.alpunlu.jarvis.mac'
CHECK_EVERY = 21600.0
NAMES = ('JARVIS', 'ALPAI')
_NAME = '(?:' + '|'.join(map(re.escape, NAMES)) + ')'
if paths.IS_WIN:
    CACHE = paths.DATA_DIR / '_update' if os.environ.get('JARVIS_DATA_DIR') else Path(os.environ.get('LOCALAPPDATA') or Path.home()) / paths.APP_NAME / 'update'
else:
    CACHE = Path.home() / 'Library' / 'Caches' / paths.APP_NAME / 'update'

def feed() -> 'str':
    return os.environ.get('JARVIS_UPDATE_FEED', '').strip() or FEED

def enabled() -> 'bool':
    """Kanal var ve uygulama paketten çalışıyor (JARVIS.app ya da Windows kurulumu); kaynaktan çalışan kopya git ile
    güncellenir. Windows'ta kurulum klasöründen çalışmayan paket (dist\\JARVIS) de güncellenmez."""

    if not feed() or not paths.FROZEN:
        return False
    if paths.IS_WIN:
        from . import win_update
        return win_update.install_dir() is not None
    return paths.IS_MAC

def _parts(version: 'str') -> 'tuple[int, ...]':
    return tuple((int(x) for x in re.findall('\\d+', version or '')[:4])) or (0,)

def newer(candidate: 'str', current: 'str'=VERSION) -> 'bool':
    return _parts(candidate) > _parts(current)

def check() -> 'dict[str, Any] | None':
    '''Kanaldaki son sürüm bundan yeniyse bilgisi (yoksa None). Ağ hatası RuntimeError.'''

    try:
        r = requests.get(feed(), timeout=12, headers={'Accept': 'application/vnd.github+json', 'User-Agent': f'JARVIS/{VERSION}'})
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError('Güncelleme sunucusuna ulaşılamadı.') from exc
    if isinstance(data, list) or 'tag_name' in data:
        found = [r for r in (data if isinstance(data, list) else [data]) if _asset(r)]
        if not found:
            return
        rel = max(found, key=(lambda r: _parts(_release_version(r))))
        asset = _asset(rel)
        digest = str(asset.get('digest') or '')
        info = {'version': _release_version(rel), 'title': rel.get('name') or '', 'notes': rel.get('body') or '', 'url': asset['browser_download_url'], 'size': int(asset.get('size') or 0), 'sha256': digest[7:].lower() if digest.startswith('sha256:') else ''}
    else:
        info = {'version': str(data.get('version', '')), 'title': data.get('title') or '', 'notes': data.get('notes') or '', 'url': data.get('url') or '', 'size': int(data.get('size') or 0), 'sha256': str(data.get('sha256') or '').lower()}
    if not (info['url'].startswith('https://') or os.environ.get('JARVIS_UPDATE_FEED')):
        return
    force = os.environ.get('JARVIS_UPDATE_FORCE') == '1'
    if newer(info['version']) or force and info['version'] == VERSION:
        return info

def _release_version(rel: 'dict[str, Any]') -> 'str':
    '''Etiketteki sürüm: "v4.5.1" → "4.5.1" (sonundaki "-mac" gibi ekler atılır).'''

    hit = re.search('\\d+(?:\\.\\d+)+', str(rel.get('tag_name') or ''))
    if hit:
        return hit.group(0)
    return ''

def _asset(rel: 'dict[str, Any]') -> 'dict[str, Any] | None':
    '''Yayımlanmış bir V4 sürümünde bu işletim sisteminin dosyası (Mac: DMG, Windows: kurulum; dosya adındaki sürüm
    etiketteki sürüm olmalı). Eski sürümler, taslaklar, ön sürümler, dosyası olmayanlar: None.'''

    if not isinstance(rel, dict) or rel.get('draft') or rel.get('prerelease'):
        return
    version = _release_version(rel)
    if _parts(version)[:1] < (4,):
        return
    name = f'{_NAME}-{re.escape(version)}-Windows-Setup\\.exe' if paths.IS_WIN else f'{_NAME}-[\\d.]+\\.dmg'
    return next((a for a in rel.get('assets') or []
         if isinstance(a, dict) and re.fullmatch(name, str(a.get('name', '')), re.I) and a.get('state', 'uploaded') == 'uploaded'), None)

def current_bundle() -> 'Path | None':
    """Çalışan JARVIS.app'in yeri (…/JARVIS.app/Contents/MacOS/JARVIS)."""

    exe = Path(sys.executable).resolve()
    app = exe.parents[2] if len(exe.parents) > 2 else None
    if app and app.suffix == '.app':
        return app

def _run(cmd: 'list[str]', timeout: 'float'=120) -> 'subprocess.CompletedProcess':
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def download(info: 'dict[str, Any]', progress: 'Callable[[float], None]') -> 'Path':
    '''Dosyayı önbelleğe indirir; eksik inerse ya da SHA-256 özeti tutmazsa RuntimeError (dosya silinir).'''

    CACHE.mkdir(parents=True, exist_ok=True)
    name = f'JARVIS-{info['version']}-Windows-Setup.exe' if paths.IS_WIN else f'JARVIS-{info['version']}.dmg'
    target = CACHE / name
    part = CACHE / (name + '.part')
    digest = hashlib.sha256()
    try:
        with requests.get(info['url'], stream=True, timeout=30, headers={'User-Agent': f'JARVIS/{VERSION}'}) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length') or info.get('size') or 0)
            done, last = 0, 0.0
            with open(part, 'wb') as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if not total:
                        continue
                    if time.monotonic() - last > 0.25:
                        last = time.monotonic()
                        progress(min(1.0, done / total))
    except (requests.RequestException, OSError) as exc:
        part.unlink(missing_ok=True)
        log('güncelleme: indirme koptu', exc)
        raise RuntimeError('İndirme yarıda kaldı. İnternet bağlantını kontrol edip yeniden dene.') from exc
    if total and done != total:
        part.unlink(missing_ok=True)
        raise RuntimeError('İndirme yarıda kaldı. İnternet bağlantını kontrol edip yeniden dene.')
    if info.get('sha256') and digest.hexdigest() != info['sha256']:
        part.unlink(missing_ok=True)
        raise RuntimeError('İndirilen dosya bozuk (SHA-256 özeti tutmuyor); kurulmadı. Yeniden dene.')
    part.replace(target)
    progress(1.0)
    return target

def verify_app(app: 'Path', version: 'str') -> 'str | None':
    '''Kurulacak uygulama bizim mi, sağlam mı, Apple onaylı mı? Sorun varsa açıklaması.'''

    if not app.exists():
        return 'İndirilen dosyada JARVIS bulunamadı.'
    if _run(['codesign', '--verify', '--deep', '--strict', str(app)]).returncode != 0:
        return 'İndirilen uygulamanın imzası bozuk.'
    info = _run(['codesign', '-dv', '--verbose=2', str(app)]).stderr
    if f'TeamIdentifier={TEAM_ID}' not in info or f'Identifier={BUNDLE_ID}' not in info:
        return "İndirilen uygulama JARVIS'in geliştiricisi tarafından imzalanmamış."
    if _run(['spctl', '-a', '-t', 'exec', str(app)]).returncode != 0:
        return 'İndirilen uygulama Apple onayından geçmemiş.'
    try:
        plist = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
    except (OSError, plistlib.InvalidFileException):
        return 'İndirilen uygulamanın bilgileri okunamadı.'
    if plist.get('CFBundleShortVersionString') != version:
        return 'İndirilen sürüm duyurulanla aynı değil.'

def stage(dmg: 'Path', version: 'str') -> 'Path':
    """DMG'yi bağla, içindeki uygulamayı denetle ve önbelleğe kopyala. Hata RuntimeError."""

    mount = Path(tempfile.mkdtemp(prefix='jarvis-update-'))
    attach = _run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', str(mount), str(dmg)])
    if attach.returncode != 0:
        raise RuntimeError('İndirilen dosya açılamadı (DMG bozuk olabilir).')
    try:
        app = next((mount / f'{n}.app' for n in NAMES if (mount / f'{n}.app').exists()), mount / 'JARVIS.app')
        problem = verify_app(app, version)
        if problem:
            raise RuntimeError(problem)
        staged = CACHE / 'JARVIS.app'
        shutil.rmtree(staged, ignore_errors=True)
        if _run(['ditto', str(app), str(staged)], timeout=300).returncode != 0:
            raise RuntimeError('Yeni sürüm kopyalanamadı.')
    finally:
        _run(['hdiutil', 'detach', '-quiet', str(mount)])
        shutil.rmtree(mount, ignore_errors=True)
    return staged

def schedule_swap(staged: 'Path', target: 'Path', relaunch: 'bool'=True) -> 'None':
    """JARVIS kapanınca eskisini yenisiyle değiştiren betik (arka planda, JARVIS'ten bağımsız)."""

    old = target.with_name(target.name + '.eski')
    q = shlex.quote
    script = f'#!/bin/sh\nwhile kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done\nrm -rf {q(str(old))}\nif mv {q(str(target))} {q(str(old))} && ditto {q(str(staged))} {q(str(target))}; then\n  rm -rf {q(str(old))} {q(str(staged))}\nelse\n  rm -rf {q(str(target))}; mv {q(str(old))} {q(str(target))}\nfi\n{f'open {q(str(target))}' if relaunch else ''}\n'
    path = CACHE / 'kur.sh'
    path.write_text(script, encoding='utf-8')
    path.chmod(493)
    subprocess.Popen(['/bin/sh', str(path)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log('güncelleme: kapanınca kurulacak', target)

def cleanup() -> 'None':
    '''Kurulmuş (bu sürüm ya da eskisi) güncellemenin indirme artıklarını sil (DMG ~90 MB, Windows kurulumu ~70 MB);
    Windows kurulum günlüklerinden son üçü kalır.'''

    if not CACHE.exists():
        return
    logs = []
    for f in CACHE.iterdir():
        if re.fullmatch('kurulum-.+\\.log', f.name):
            logs.append(f)
            continue
        m = re.match('JARVIS-([\\d.]+?)(?:-Windows-Setup\\.exe|\\.dmg)(\\.part)?$', f.name)
        if not m or newer(m.group(1)):
            if f.name != 'kur.sh':
                continue
        try:
            f.unlink()
        except OSError:
            continue
    for f in sorted(logs, key=(lambda p: p.stat().st_mtime))[:-3]:
        try:
            f.unlink()
        except OSError:
            continue

def writable(target: 'Path') -> 'bool':
    return os.access(target.parent, os.W_OK) and os.access(target, os.W_OK)


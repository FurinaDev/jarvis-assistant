"""Asistanın kullanıcıya dosya göndermesi: Mac'te dosya bulmak, okumak, hazırlamak.

Üç araç buraya dayanır:
  find_files   Masaüstü, Belgeler, İndirilenler ve Resimler'de (bir de ekran
               görüntülerinin kaydedildiği klasörde) ada, türe ve tarihe göre
               arar; bulunanlar sohbette kart olarak görünür.
  read_file    Bulunan (ya da hazırlanan) bir dosyanın içeriğini asistana verir:
               metin olarak ya da görsel olarak (fotoğraf, taranmış PDF). Dosya
               dönüşümü jarvis.attachments'tadır, kullanıcının sürükleyip
               bıraktığı dosyalarla aynı yoldan geçer.
  create_file  Asistanın yazdığı metni, listeyi, tabloyu dosyaya çevirir
               (txt, md, csv, docx). Belgeler/JARVIS Dosyaları'na kaydedilir.

Sınırlar:
- Yalnızca yukarıdaki kullanıcı klasörlerine bakılır; Kütüphane, sistem
  klasörleri, gizli dosyalar ve adı anahtar/şifre gibi görünen dosyalar
  aranmaz ve okunmaz.
- Hiçbir dosya silinmez, taşınmaz, üzerine yazılmaz. Hazırlanan dosyanın adı
  varsa sonuna numara eklenir.
- Dosyalar hiçbir yere gönderilmez; yalnızca sohbette gösterilir. Kartın
  düğmeleri: aç, Finder'da göster, panoya kopyala.

Windows'a özgü parçalar (klasörlerin gerçek yeri, gizli dosyalar, Gezgin, pano,
küçük resim) jarvis.win_files'ta.
"""

from __future__ import annotations
import base64
import csv
import datetime as dt
import html
import io
import itertools
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from . import attachments, paths
from .attachments import (AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, human_size)
from .log import log
if paths.IS_WIN:
    from . import win_docs, win_files
HOME = Path.home()
FOLDERS = {'desktop': ('MASAÜSTÜ', HOME / 'Desktop'), 'documents': ('BELGELER', HOME / 'Documents'), 'downloads': ('İNDİRİLENLER', HOME / 'Downloads'), 'pictures': ('RESİMLER', HOME / 'Pictures')}
if paths.IS_WIN:
    FOLDERS = {k: (label, win_files.known_folder(k) or p) for k, (label, p) in FOLDERS.items()}
OUT_DIR = Path(os.environ.get('JARVIS_FILES_DIR') or FOLDERS['documents'][1] / 'JARVIS Dosyaları')
MAX_DEPTH = 6
MAX_SEEN = 120000
SEARCH_BUDGET = 6.0
MAX_SHOWN = 6
MAX_CONTENT = 200000
THUMB = 360
SKIP_DIRS = {'.git', '.venv', '.Trash', 'site-packages', 'Pods', 'dist', 'venv', 'build', 'Library', 'DerivedData', '__pycache__', 'node_modules'}
PACKAGE_EXT = {'numbers-tef', 'app', 'key', 'band', 'kext', 'rtfd', 'pages', 'bundle', 'logicx', 'lrdata', 'plugin', 'numbers', 'fcpbundle', 'framework', 'lrlibrary', 'tvlibrary', 'xcodeproj', 'playground', 'xcworkspace', 'musiclibrary', 'sparsebundle', 'imovielibrary', 'photoslibrary'}
NOT_A_RESULT_EXT = {'kext', 'bundle', 'lrdata', 'plugin', 'fcpbundle', 'framework', 'lrlibrary', 'tvlibrary', 'musiclibrary', 'sparsebundle', 'imovielibrary', 'photoslibrary'}
PARTIAL_EXT = {'tmp', 'part', 'partial', 'download', 'crdownload'}
APP_EXT = {'app', 'lnk', 'url'}
PRIVATE_NAME = re.compile('api[_ -]?keys?|apikey|secret|token|passw|sifre|parola|credential|id_rsa|id_ed25519|\\.env$|keychain|wallet|seed[_ -]?phrase|recovery[_ -]?(key|codes?)|backup[_ -]?codes?|yedek[_ -]?kod|(^|[^a-z0-9])2fa([^a-z0-9]|$)|two[_ -]?factor')
PRIVATE_EXT = {'keychain-db', 'env', 'gpg', 'p12', 'pem', 'pfx', 'kdbx', 'ovpn', 'keychain'}
KINDS: 'dict[str, set[str]]' = {'image': IMAGE_EXT, 'pdf': {'pdf'}, 'doc': {'md', 'doc', 'odt', 'rtf', 'txt', 'docx', 'rtfd', 'pages', 'markdown'}, 'sheet': {'csv', 'ods', 'tsv', 'xls', 'xlsx', 'numbers'}, 'slides': {'key', 'odp', 'ppt', 'pptx'}, 'video': VIDEO_EXT, 'audio': AUDIO_EXT, 'archive': {'7z', 'gz', 'xz', 'bz2', 'dmg', 'rar', 'tar', 'tgz', 'zip'}}
SCREENSHOT = re.compile('^(ekran resmi|ekran goruntusu|ekran kaydi|screenshot|screen shot|screen recording)')
ROOT_NAMES = {'MASAÜSTÜ': 'Masaüstü', 'BELGELER': 'Belgeler', 'İNDİRİLENLER': 'İndirilenler', 'RESİMLER': 'Resimler', 'EKRAN GÖRÜNTÜLERİ': 'Ekran görüntüleri', 'JARVIS DOSYALARI': 'JARVIS Dosyaları'}
KIND_LABEL = {'image': 'GÖRSEL', 'pdf': 'PDF', 'doc': 'BELGE', 'sheet': 'TABLO', 'slides': 'SUNUM', 'video': 'VİDEO', 'audio': 'SES', 'archive': 'ARŞİV', 'folder': 'KLASÖR', 'other': 'DOSYA'}
TR_MONTHS = ['', 'Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara']

def fold(text: 'str') -> 'str':
    '''Karşılaştırma için: küçük harf, Türkçe harfler sadeleşmiş ("Sözleşme" → "sozlesme").'''

    text = unicodedata.normalize('NFKD', text.replace('ı', 'i').replace('İ', 'i'))
    return ''.join((c for c in text if not unicodedata.combining(c))).casefold()

def _ext(name: 'str') -> 'str':
    if '.' in name.strip('.'):
        return name.rsplit('.', 1)[-1].lower()
    return ''

def kind_of(name: 'str', is_dir: 'bool'=False) -> 'str':
    ext = _ext(name)
    if is_dir and ext not in PACKAGE_EXT:
        return 'folder'
    for kind, exts in KINDS.items():
        if ext not in exts:
            continue
        return kind
    return 'other'

def private(path: 'str | Path') -> 'bool':
    '''Anahtar, şifre, gizli dosya ya da kilit dosyası mı (aranmaz, okunmaz).'''

    parts = Path(path).parts
    name = parts[-1] if parts else ''
    return any((p.startswith('.') for p in parts[1:])) or name.startswith('~$') or _ext(name) in PRIVATE_EXT or bool(PRIVATE_NAME.search(fold(name)))

def screenshot_dir() -> 'Path | None':
    """Ekran görüntülerinin kaydedildiği klasör (macOS'ta değiştirildiyse; Windows'ta Resimler/Ekran Görüntüleri)."""

    if paths.IS_WIN:
        return win_files.known_folder('screenshots')
    if not paths.IS_MAC:
        return
    try:
        out = subprocess.run(['defaults', 'read', 'com.apple.screencapture', 'location'], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    else:
        if out:
            return Path(os.path.expanduser(out))

def roots(folder: 'str'='any') -> 'list[tuple[str, Path]]':
    '''Aranacak klasörler: (ekrandaki ad, yol).'''

    if folder == 'jarvis':
        return [('JARVIS DOSYALARI', OUT_DIR)]
    chosen = [FOLDERS[folder]] if folder in FOLDERS else list(FOLDERS.values())
    shots = screenshot_dir()
    if folder in ('any', 'screenshots') and shots and shots.is_dir() and shots.is_relative_to(HOME):
        if not any((shots == p or shots.is_relative_to(p) for _, p in chosen)):
            chosen.append(('EKRAN GÖRÜNTÜLERİ', shots))
    if folder == 'screenshots':
        chosen = [c for c in chosen if c[0] == 'EKRAN GÖRÜNTÜLERİ'] or list(FOLDERS.values())
    return [(label, p) for label, p in chosen if p.is_dir()]

def allowed(path: 'str | Path') -> 'bool':
    '''Asistanın okuyabileceği yerde mi: kullanıcı klasörleri, hazırlananlar, kullanıcının gönderdikleri.'''

    try:
        p = Path(path).expanduser().resolve()
    except OSError:
        return False
    if private(p):
        return False
    places = [r for _, r in roots('any')] + [OUT_DIR, attachments.INBOX]
    return str(p) in _known or any((p == r.resolve() or p.is_relative_to(r.resolve()) for r in places if r.exists()))

def _stamp(st: 'os.stat_result') -> 'float':
    '''Dosyanın "ne zaman" zamanı: oluşturulma (indirme) ya da son değişiklik, hangisi yeniyse.'''

    return max(st.st_mtime, getattr(st, 'st_birthtime', 0) or 0)

def when_label(ts: 'float') -> 'str':
    moment = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    if moment.date() == today:
        return f'BUGÜN {moment:%H:%M}'
    if moment.date() == today - dt.timedelta(days=1):
        return f'DÜN {moment:%H:%M}'
    if moment.year != today.year:
        return f'{moment.day} {TR_MONTHS[moment.month].upper()}' + f' {moment.year}'
    return None + ''

def _since(when: 'str') -> 'float':
    today = dt.datetime.combine(dt.date.today(), dt.time())
    starts = {'today': today, 'yesterday': today - dt.timedelta(days=1), 'week': today - dt.timedelta(days=7), 'month': today - dt.timedelta(days=31), 'year': today - dt.timedelta(days=366)}
    if when in starts:
        return starts[when].timestamp()
    return 0.0

@dataclass
class Found:
    path: 'Path'
    root: 'str'
    kind: 'str'
    stamp: 'float'
    size: 'int'
    score: 'float' = 0.0

def _words(query: 'str') -> 'list[str]':
    return [w for w in re.split('[\\s_\\-.,;:/\\\\()\\[\\]\'\\"’]+', fold(query)) if w]

def _match(words: 'list[str]', name: 'str', rel: 'str', ext: 'str'='') -> 'float':
    '''Adın sorguya uyma puanı (0: uymuyor). Sözcük adda yoksa klasör yolunda aranır.

    Türkçe ekler yüzünden ("sözleşmeyi") uzun sözcüğün sonundan 1-3 harf atılarak da denenir.
    Uzantı da bir sözcük sayılır ("rapor pdf"). Sözcüğün tamamı ya da başı tutan ad, ortasında
    geçen addan önce gelir ("MEF" → "MEF", sonra "mefumetto").
    '''

    if not words:
        return 1.0
    score = 0.0
    parts = _words(name)
    for w in words:
        stems = [w] + [w[:-k] for k in (1, 2, 3) if len(w) - k >= 4]
        if w == ext or w in parts:
            score += 1.0
        elif any((p.startswith(s) for p in parts for s in stems)):
            score += 0.85
        elif any((s in name for s in stems)):
            score += 0.6
        elif any((s in rel for s in stems)):
            score += 0.5
        else:
            return 0.0
    return score / len(words)

def find(query: 'str'='', folder: 'str'='any', kind: 'str'='any', when: 'str'='any', limit: 'int'=5, cap: 'int'=MAX_SHOWN) -> 'list[Found]':
    '''Kullanıcı klasörlerinde arar; en uygun ve en yeni olanlar önce.'''

    words = _words(query)
    since, until = _since(when), _since('today') if when == 'yesterday' else float('inf')
    want_shot = kind == 'screenshot'
    started, seen = time.monotonic(), 0
    hits = []
    visited = set()
    def consider(entry: 'os.DirEntry', root_label: 'str', rel: 'str', is_dir: 'bool') -> 'None':
        name = entry.name
        k = kind_of(name, is_dir)
        if want_shot:
            if not SCREENSHOT.match(fold(name)) or k not in ('image', 'video'):
                return
        if kind == 'folder':
            if k != 'folder':
                return
                if kind != 'any' and k != kind:
                    return
        if _ext(name) in NOT_A_RESULT_EXT | (APP_EXT if kind != 'any' or not words else set()) or not is_dir and _ext(name) in PARTIAL_EXT:
            return
        stem = fold(name.rsplit('.', 1)[0] if not is_dir else name)
        score = _match(words, stem, fold(rel), '' if is_dir else _ext(name))
        if score <= 0 or k == 'folder' and kind != 'folder' and not words:
            return
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            pass
        else:
            stamp = _stamp(st)
            if stamp < since or stamp >= until:
                return
            hits.append(Found(Path(entry.path), root_label, k, stamp, 0 if is_dir else st.st_size, score))

    def walk(folder_path: 'Path', root_label: 'str', rel: 'str', depth: 'int') -> 'None':
        nonlocal seen
        if folder_path in visited:
            return
        visited.add(folder_path)
        try:
            with os.scandir(folder_path) as it:
                entries = list(it)
        except OSError:
            return
        subdirs = []
        for e in entries:
            seen += 1
            if not (e.name.startswith('.') or e.name.startswith('~$')):
                if not private(e.name):
                    if paths.IS_WIN:
                        if win_files.hidden(e):
                            continue
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    consider(e, root_label, rel, is_dir)
                    if not is_dir:
                        continue
                    if _ext(e.name) in PACKAGE_EXT:
                        continue
                    if e.name in SKIP_DIRS:
                        continue
                    subdirs.append(e)
        if depth >= MAX_DEPTH:
            return
        for e in subdirs:
            if seen > MAX_SEEN or time.monotonic() - started > SEARCH_BUDGET:
                return
            walk(Path(e.path), root_label, f'{rel}/{e.name}', depth + 1)

    for label, root in roots('screenshots' if want_shot and folder == 'any' else folder):
        walk(root, label, '', 0)
    unique = {h.path: h for h in hits}.values()
    ranked = sorted(unique, key=(lambda h: (-round(h.score, 1), -h.stamp)))
    log(f'dosya arama: {query!r} {folder}/{kind}/{when} → {len(hits)} eşleşme, {seen} öğe, {time.monotonic() - started:.2f} sn')
    return ranked[:max(1, min(limit, cap))]

_ids = itertools.count(1)
_by_id: 'dict[str, str]' = {}
_known: 'set[str]' = set()

def register(path: 'str | Path') -> 'str':
    card = f'f{next(_ids)}'
    _by_id[card] = str(path)
    _known.add(str(Path(path).resolve()))
    return card

def path_of(card: 'str') -> 'str | None':
    return _by_id.get(card)

def _where(path: 'Path') -> 'str':
    for label, root in [*FOLDERS.values(), ('JARVIS DOSYALARI', OUT_DIR)]:
        if path.parent != root:
            continue
        return label
    for label, root in [('JARVIS DOSYALARI', OUT_DIR), *FOLDERS.values()]:
        try:
            rel = path.parent.relative_to(root)
        except ValueError:
            continue
        return f'{label}/{rel.parts[-1].upper() if len(rel.parts) == 1 else '…/' + rel.parts[-1].upper()}'
    return path.parent.name.upper()

def where_name(path: 'Path') -> 'str':
    '''Konuşmada: "Belgeler/JARVIS Dosyaları".'''

    for label, root in ('Belgeler/JARVIS Dosyaları', OUT_DIR), ('Masaüstü', FOLDERS['desktop'][1]), ('İndirilenler', FOLDERS['downloads'][1]):
        if path.parent == root:
            return label
    return str(path.parent).replace(str(HOME), '~')

def card(path: 'str | Path', made: 'bool'=False) -> 'dict[str, Any]':
    '''Ekrana giden kart (küçük resim sonra gelir: `thumb`).'''

    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {'id': register(p), 'name': p.name, 'kind': 'other', 'ext': _ext(p.name), 'label': 'BULUNAMADI', 'where': '', 'missing': True}
    is_dir = p.is_dir() and _ext(p.name) not in PACKAGE_EXT
    kind = kind_of(p.name, is_dir)
    if is_dir:
        try:
            count = sum((1 for e in os.scandir(p) if not e.name.startswith('.') if not paths.IS_WIN or not win_files.hidden(e)))
        except OSError:
            count = 0
        label = f'KLASÖR · {count} ÖĞE'
    else:
        label = f'{_ext(p.name).upper() or KIND_LABEL[kind]} · {human_size(st.st_size)}'
    if kind in ('doc', 'sheet') and _ext(p.name) in ('txt', 'md', 'csv', 'tsv') and not _in_cloud(p):
        return {'id': register(p), 'name': p.name, 'kind': kind, 'ext': _ext(p.name), 'label': label, 'where': ('HAZIRLANDI · ' if made else '') + f'{_where(p)} · {when_label(_stamp(st))}', 'snippet': _snippet(p), 'made': made}
    return {'id': None, 'name': None, 'kind': None, 'ext': None, 'label': None, 'where': None, 'snippet': '', 'made': made}

def _in_cloud(p: 'Path') -> 'bool':
    """Windows: OneDrive'da yalnızca bulutta duran dosya; kart için açılmaz (açılırsa indirilir)."""

    return paths.IS_WIN and win_files.cloud_only(p)

def _snippet(p: 'Path') -> 'str':
    try:
        with open(p, encoding='utf-8-sig', errors='replace') as f:
            text = f.read(400)
    except OSError:
        return ''
    return '\n'.join((line[:60] for line in text.splitlines()[:5]))

def thumb(path: 'str | Path') -> 'str':
    '''Kartın küçük resmi (data: adresi); üretilemezse boş.'''

    p = Path(path)
    ext = _ext(p.name)
    try:
        img = None
        if ext in IMAGE_EXT and not _in_cloud(p):
            from PIL import Image
        try:
            img = Image.open(p)
            img.draft('RGB', (THUMB, THUMB))
            img.load()
        except Exception:
            img = _quicklook(p)
        else:
            if ext == 'pdf' and paths.IS_MAC:
                import Foundation
                import Quartz
                doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(p)))
                if doc is not None and not doc.isLocked() and doc.pageCount():
                    img = attachments._pdf_page(doc, 0, THUMB)
            elif ext == 'pdf' and paths.IS_WIN and not _in_cloud(p):
                img = win_docs.pdf_thumb(p, THUMB)
            elif ext not in VIDEO_EXT:
                if ext in {'ai', 'doc', 'key', 'odt', 'psd', 'rtf', 'svg', 'docx', 'heic', 'pptx', 'xlsx', 'pages', 'numbers'} or paths.IS_WIN and not p.is_dir():
                    img = _quicklook(p)
            if img is None:
                return ''
            jpeg = attachments._jpeg(img, THUMB, 75)
    except Exception as exc:
        log('küçük resim yok:', p.name, exc)
        return ''
    return 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()

def _quicklook(p: 'Path'):
    if paths.IS_WIN:
        return win_files.thumbnail(p, THUMB)
    if not paths.IS_MAC:
        return
    from PIL import Image
    out = Path(tempfile.mkdtemp(prefix='jarvis-ql-'))
    try:
        subprocess.run(['qlmanage', '-t', '-s', str(THUMB * 2), '-o', str(out), str(p)], capture_output=True, timeout=6)
        made = next(out.glob('*.png'), None)
        if made is None:
            shutil.rmtree(out, ignore_errors=True)
            return
        img = Image.open(made)
        img.load()
    except (subprocess.TimeoutExpired, OSError):
        shutil.rmtree(out, ignore_errors=True)
        return
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return img

def read(path: 'str') -> 'tuple[str, list[bytes]]':
    '''Asistan için: (metin, görseller). Kullanıcının sürükleyip bıraktığı dosyayla aynı dönüşüm.'''

    p = Path(os.path.expanduser(path.strip()))
    if not p.exists():
        return f'Dosya bulunamadı: {p.name}. Önce find_files ile ara.', []
    if not allowed(p):
        return 'Bu dosya okunamaz: yalnızca kullanıcı klasörlerindeki (anahtar/şifre olmayan) dosyalar okunur.', []
    att = attachments.from_path(str(p))
    _known.add(str(p.resolve()))
    head = f'[Dosya: {att.name} — {att.info}]'
    if att.error and not att.text and not att.images:
        return f'Hata: {att.name} okunamadı ({att.error}).', []
    images = att.images[:attachments.PDF_PAGE_IMAGES]
    note = f'\n({len(images)} görsel bu yanıtın ekinde; onlara bakarak anlat.)' if images else ''
    return head + ('\n' + att.text if att.text else '') + note, images

FORMATS = ('txt', 'md', 'csv', 'docx')

def _safe_name(name: 'str') -> 'str':
    name = re.sub('[\\\\/:*?\\"<>|\\x00-\\x1f]+', ' ', name).strip(' .')
    return re.sub('\\s+', ' ', name)[:80] or 'JARVIS dosyası'

def _unique(folder: 'Path', stem: 'str', ext: 'str') -> 'Path':
    target = folder / f'{stem}.{ext}'
    n = 2
    while target.exists():
        target = folder / f'{stem} ({n}).{ext}'
        n += 1
    return target

def _list_separator() -> 'str':
    """Excel, ondalık ayırıcı virgül olan dillerde (Türkçe) CSV'yi noktalı virgülle bekler."""

    if paths.IS_WIN:
        return win_docs.list_separator()
    if paths.IS_MAC:
        try:
            import Foundation
            if Foundation.NSLocale.currentLocale().decimalSeparator() == ',':
                return ';'
        except Exception:
            pass
        return ','
    return ','

def _csv(content: 'str') -> 'str':
    """Asistanın yazdığı tabloyu (noktalı virgül, sekme, Markdown tablosu ya da virgülle) Excel'in açacağı hâle
    getirir. Ayırıcı ilk satırdan seçilir: tahmin, tek bir eksik hücrede ya da ondalık virgülde şaşıyordu."""

    lines = [line for line in content.strip('\n').splitlines()
         if not re.fullmatch('\\s*\\|?\\s*:?-{3,}:?\\s*(\\|\\s*:?-{3,}:?\\s*)*\\|?\\s*', line)]
    delimiter = next((d for d in (';', '\t', '|') if lines if d in lines[0]), None)
    if delimiter == '|':
        lines = [line.strip().strip('|') for line in lines]
    elif delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff('\n'.join(lines[:10]), delimiters=',;\t').delimiter
        except csv.Error:
            delimiter = ','
    rows = list(csv.reader(io.StringIO('\n'.join(lines)), delimiter=delimiter))
    rows = [[cell.strip() for cell in row] for row in rows if any((c.strip() for c in row))]
    out = io.StringIO()
    csv.writer(out, delimiter=_list_separator(), lineterminator='\r\n').writerows(rows)
    return out.getvalue()

def _md_html(content: 'str', title: 'str') -> 'str':
    """Basit Markdown (başlık, kalın, italik, madde) → HTML; Word'e bununla çevrilir."""

    def inline(text: 'str') -> 'str':
        text = html.escape(text)
        text = re.sub('\\*\\*(.+?)\\*\\*', '<b>\\1</b>', text)
        return re.sub('(?<![\\w*])\\*(?!\\s)(.+?)(?<!\\s)\\*(?![\\w*])', '<i>\\1</i>', text)

    out, in_list = [], ''
    for raw in content.splitlines():
        line = raw.rstrip()
        bullet = re.match('^\\s*[-*•]\\s+(.*)', line)
        number = re.match('^\\s*\\d+[.)]\\s+(.*)', line)
        tag = 'ul' if bullet else 'ol' if number else ''
        if in_list and tag != in_list:
            out.append(f'</{in_list}>')
            in_list = ''
        if tag:
            if not in_list:
                out.append(f'<{tag}>')
                in_list = tag
            out.append(f'<li>{inline((bullet or number).group(1))}</li>')
            continue
        heading = re.match('^(#{1,4})\\s+(.*)', line)
        if heading:
            level = len(heading.group(1))
            out.append(f'<h{level}>{inline(heading.group(2))}</h{level}>')
            continue
        if not line.strip():
            continue
        out.append(f'<p>{inline(line)}</p>')
        continue
    if in_list:
        out.append(f'</{in_list}>')
    return f"<html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head><body style='font-family:Helvetica;font-size:12pt'>" + '\n'.join(out) + '</body></html>'

def create(name: 'str', content: 'str', fmt: 'str'='txt', folder: 'str'='jarvis') -> 'Path':
    '''Yeni dosya yazar ve yolunu döndürür. Var olan hiçbir dosyanın üzerine yazmaz.'''

    fmt = (fmt or 'txt').lower().lstrip('.')
    if fmt in ('markdown',):
        fmt = 'md'
    if fmt in ('word', 'doc'):
        fmt = 'docx'
    if fmt not in FORMATS:
        raise ValueError(f'desteklenmeyen biçim: {fmt} (txt, md, csv ya da docx)')
    content = (content or '').strip()
    if not content:
        raise ValueError('dosyanın içeriği boş')
    if len(content) > MAX_CONTENT:
        raise ValueError('içerik çok uzun')
    target_dir = {'desktop': FOLDERS['desktop'][1], 'downloads': FOLDERS['downloads'][1]}.get(folder, OUT_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(re.sub('\\.(txt|md|csv|docx?|markdown)$', '', name.strip(), flags=re.I))
    target = _unique(target_dir, stem, fmt)
    if fmt == 'csv':
        target.write_text(_csv(content), encoding='utf-8-sig', newline='')
    elif fmt == 'docx' and paths.IS_WIN:
        win_docs.write_docx(target, content, stem)
    elif fmt == 'docx':
        if not paths.IS_MAC:
            raise ValueError("Word dosyası şimdilik yalnızca macOS'ta")
        with tempfile.NamedTemporaryFile('w', suffix='.html', encoding='utf-8', delete=False) as tmp:
            tmp.write(_md_html(content, stem))
        try:
            done = subprocess.run(['textutil', '-convert', 'docx', '-output', str(target), tmp.name], capture_output=True, timeout=20)
        finally:
            os.unlink(tmp.name)
        if done.returncode or not target.exists():
            raise ValueError('Word dosyasına çevrilemedi')
        elif fmt == 'txt':
            target.write_text(re.sub('\\*\\*(.+?)\\*\\*', '\\1', content) + '\n', encoding='utf-8')
        else:
            target.write_text(content + '\n', encoding='utf-8')
    log(f'dosya hazırlandı: {target} ({human_size(target.stat().st_size)})')
    return target

def reveal(path: 'str') -> 'None':
    """Finder'da (Windows'ta Dosya Gezgini'nde), dosya seçili olarak göster."""

    if paths.IS_MAC:
        subprocess.run(['open', '-R', path], check=False, timeout=5)
        return
    if paths.IS_WIN:
        win_files.reveal(path)

def copy_to_pasteboard(path: 'str') -> 'bool':
    """Dosyanın kendisini panoya koyar: Finder'a, WhatsApp'a, Mail'e ⌘V ile yapıştırılır."""

    if paths.IS_WIN:
        return win_files.copy_file(path)
    if not paths.IS_MAC:
        return False
    done = threading.Event()
    ok = [False]
    def put() -> 'None':
        try:
            import AppKit
            board = AppKit.NSPasteboard.generalPasteboard()
            board.clearContents()
            ok[0] = bool(board.writeObjects_([AppKit.NSURL.fileURLWithPath_(path)]))
        finally:
            done.set()

    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(put)
    except Exception:
        pass
    if not done.wait(2):
        put()
    return ok[0]

# WARNING: Decompyle incomplete

'''Dosya ve fotoğraf gönderme: yazma satırındaki ataç, sürükle-bırak ya da ⌘V.

Gemini Live yalnızca görsel ve metin kabul ediyor; PDF'yi doğrudan gönderince
oturumu "geçersiz bağımsız değişken" (1007) hatasıyla kapatıyor. Bu yüzden her
dosya modele gitmeden önce görsele ya da metne çevrilir:

  fotoğraf (jpg, png, heic, gif, webp…)  → uzun kenarı en fazla 1600 px JPEG
  PDF                                    → metni; metni yoksa (taranmış) ilk sayfaların görüntüsü
  metin ve kod (txt, md, py, json, csv…) → metnin kendisi
  Word, RTF, ODT, HTML                   → macOS textutil ile metin
  video                                  → eşit aralıklı birkaç kare
  klasör                                 → içindekilerin listesi
  diğerleri (Pages, Keynote, Excel…)     → Quick Look önizlemesi; o da yoksa yalnızca adı ve boyutu

Beyne sağlayıcıdan bağımsız parçalar gider: ("text", str) ya da ("image", jpeg).

Windows'ta macOS'un araçları yok: PDF, belgeler ve önizlemeler jarvis.win_docs'ta (PDFium, Office olmadan).
'''

from __future__ import annotations
import base64
import io
import itertools
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from . import paths
from .log import log
if paths.IS_WIN:
    from . import win_docs, win_files
MAX_FILES = 10
MAX_SIDE = 1600
THUMB_SIDE = 240
MAX_TEXT = 30000
MAX_TOTAL_TEXT = 60000
MAX_READ = 4194304
MAX_DATA = 41943040
PDF_PAGE_IMAGES = 4
VIDEO_FRAMES = 4
IMAGE_EXT = {'bmp', 'gif', 'ico', 'jpg', 'png', 'tif', 'avif', 'heic', 'heif', 'jpeg', 'tiff', 'webp'}
TEXT_EXT = {'c', 'h', 'm', 'r', 'cc', 'go', 'js', 'kt', 'md', 'mm', 'py', 'rb', 'rs', 'sh', 'ts', 'bib', 'cfg', 'cpp', 'css', 'csv', 'hpp', 'ini', 'jsx', 'log', 'lua', 'mjs', 'php', 'rst', 'sql', 'srt', 'tex', 'tsv', 'tsx', 'txt', 'vtt', 'vue', 'xml', 'yml', 'zsh', 'bash', 'conf', 'dart', 'java', 'json', 'scss', 'toml', 'yaml', 'ipynb', 'jsonl', 'swift', 'svelte', 'markdown'}
DOC_EXT = {'doc', 'htm', 'odt', 'rtf', 'docx', 'html', 'rtfd', 'wordml', 'webarchive'}
VIDEO_EXT = {'3gp', 'avi', 'm4v', 'mkv', 'mov', 'mp4', 'webm'}
AUDIO_EXT = {'aac', 'aif', 'm4a', 'mp3', 'ogg', 'wav', 'aiff', 'flac', 'opus'}
NO_PREVIEW_EXT = {'7z', 'db', 'gz', 'xz', 'app', 'bin', 'bz2', 'dat', 'dmg', 'exe', 'iso', 'msi', 'pkg', 'rar', 'tar', 'tgz', 'zip', 'sqlite'}
_ids = itertools.count(1)
INBOX = Path(tempfile.gettempdir()) / 'jarvis-ekler'

@dataclass
class Attachment:
    name: 'str'
    path: 'str' = ''
    kind: 'str' = 'other'
    label: 'str' = ''
    size: 'int' = 0
    images: 'list[bytes]' = field(default_factory=list)
    text: 'str' = ''
    info: 'str' = ''
    error: 'str' = ''
    thumb: 'str' = ''
    id: 'str' = field(default_factory=(lambda: f'a{next(_ids)}'))
    def view(self) -> 'dict[str, Any]':
        '''Ekrana giden özet (bayt yok).'''

        return {'id': self.id, 'name': self.name, 'kind': self.kind, 'label': self.label, 'ext': _ext(self.name), 'thumb': self.thumb, 'error': self.error, 'openable': bool(self.path)}


def human_size(n: 'int') -> 'str':
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            if unit == 'B' or n >= 10:
                return f'{n:.0f} {unit}'
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.0f} GB'

def _ext(name: 'str') -> 'str':
    if '.' in name:
        return name.rsplit('.', 1)[-1].lower()
    return ''

def _jpeg(img, side: 'int'=MAX_SIDE, quality: 'int'=85) -> 'bytes':
    '''PIL görseli → uzun kenarı en fazla `side` olan JPEG. Saydam yerler beyaz olur.'''

    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality, optimize=True)
    return buf.getvalue()

def _thumb(jpeg: 'bytes') -> 'str':
    from PIL import Image
    small = _jpeg(Image.open(io.BytesIO(jpeg)), THUMB_SIDE, 72)
    return 'data:image/jpeg;base64,' + base64.b64encode(small).decode()

def _clip(text: 'str', limit: 'int'=MAX_TEXT) -> 'tuple[str, bool]':
    text = text.replace('\r\n', '\n').replace('\x00', '')
    text = re.sub('\\n{4,}', '\n\n\n', text).strip()
    if len(text) > limit:
        return text[:limit], True
    return text, False

def _image(att: 'Attachment', path: 'str') -> 'None':
    from PIL import Image
    try:
        img = Image.open(path)
        img.seek(0)
        img.load()
    except Exception:
        img = _via_sips(path)
    img.load()
    att.kind = 'image'
    w, h = img.size
    att.images = [_jpeg(img)]
    att.label = f'FOTOĞRAF · {w}×{h}'
    att.info = f'fotoğraf/görsel, {w}×{h} piksel (görsel ekte)'

def _via_sips(path: 'str'):
    if paths.IS_WIN:
        return win_docs.image_fallback(path)
    from PIL import Image
    out = Path(tempfile.mkdtemp(prefix='jarvis-')) / 'x.jpg'
    try:
        done = subprocess.run(['sips', '-s', 'format', 'jpeg', path, '--out', str(out)], capture_output=True, timeout=30)
        if done.returncode or not out.exists():
            raise ValueError('görsel biçimi tanınmadı')
        img = Image.open(out)
        img.load()
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    return img

def _pdf(att: 'Attachment', path: 'str') -> 'None':
    if paths.IS_WIN:
        return win_docs.read_pdf(att, path)
    import Foundation
    import Quartz
    att.kind = 'pdf'
    doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(path))
    if doc is None:
        raise ValueError('PDF açılamadı')
    pages = doc.pageCount()
    att.label = f'PDF · {pages} SAYFA'
    if doc.isLocked():
        att.info = f'PDF, {pages} sayfa, şifreli; içeriği okunamadı'
        att.error = 'Şifreli PDF'
        return
    text, cut = _clip(doc.string() or '')
    if len(text) >= 200 or len(text) >= 40 * pages:
        att.text = text
        att.info = f'PDF, {pages} sayfa. Metni aşağıda' + (f' (ilk {len(text):,} karakter; gerisi kesildi)' if cut else '') + ':'
        first = _pdf_page(doc, 0, THUMB_SIDE * 2)
        if first is not None:
            att.thumb = _thumb(_jpeg(first, THUMB_SIDE * 2))
        return
    count = min(pages, PDF_PAGE_IMAGES)
    for i in range(count):
        img = _pdf_page(doc, i, MAX_SIDE)
        if img is not None:
            att.images.append(_jpeg(img))
    shown = f'ilk {count} sayfanın görüntüsü' if count < pages else 'sayfaların görüntüsü'
    if text:
        att.text = text
        att.info = f'PDF, {pages} sayfa, çok az metin var; {shown} ve metni aşağıda:'
        return
    att.info = f'PDF, {pages} sayfa, metin katmanı yok (taranmış olabilir); {shown} ekte'

def _pdf_page(doc, index: 'int', side: 'int'):
    import Foundation
    import Quartz
    from PIL import Image
    page = doc.pageAtIndex_(index)
    if page is None:
        return
    image = page.thumbnailOfSize_forBox_(Foundation.NSMakeSize(side, side), Quartz.kPDFDisplayBoxMediaBox)
    tiff = image.TIFFRepresentation() if image else None
    if tiff:
        return Image.open(io.BytesIO(bytes(tiff)))

def _text(att: 'Attachment', path: 'str') -> 'None':
    with open(path, 'rb') as f:
        raw = f.read(MAX_READ)
    for enc in ('utf-8-sig', 'cp1254', 'latin-1'):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        break
    text, cut = _clip(text)
    lines = text.count('\n') + 1
    att.kind = 'text'
    att.text = text
    att.label = f'METİN · {human_size(att.size)}'
    att.info = f'metin dosyası, {lines} satır. İçeriği aşağıda' + (' (baştan bir kısmı; gerisi kesildi)' if cut or att.size > MAX_READ else '') + ':'

def _doc(att: 'Attachment', path: 'str') -> 'None':
    if paths.IS_WIN:
        return win_docs.read_doc(att, path)
    cmd = ['textutil', '-convert', 'txt', '-stdout']
    if _ext(att.name) in ('html', 'htm'):
        cmd += ['-inputencoding', 'UTF-8']
    out = subprocess.run([*cmd, '--', path], capture_output=True, timeout=30)
    text, cut = _clip(out.stdout.decode('utf-8', 'replace'))
    if not text:
        raise ValueError('belge metni okunamadı')
    att.kind = 'doc'
    att.text = text
    att.label = f'BELGE · {human_size(att.size)}'
    att.info = 'belge. Metni aşağıda' + (' (baştan bir kısmı; gerisi kesildi)' if cut else '') + ':'

def _video(att: 'Attachment', path: 'str') -> 'None':
    import cv2
    from PIL import Image
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ValueError('video açılamadı')
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        seconds = frames / fps if fps > 0 and frames > 0 else 0
        spots = [int(frames * (i + 0.5) / VIDEO_FRAMES) for i in range(VIDEO_FRAMES)] if frames > 1 else [0]
        for spot in spots:
            cap.set(cv2.CAP_PROP_POS_FRAMES, spot)
            ok, frame = cap.read()
            if ok:
                att.images.append(_jpeg(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), 1024, 80))
    finally:
        cap.release()
    if not att.images:
        raise ValueError('videodan kare alınamadı')
    length = f'{int(seconds) // 60}:{int(seconds) % 60:02d}' if seconds else '?'
    att.kind = 'video'
    att.label = f'VİDEO · {length}'
    att.info = f'video, {length} uzunluğunda. Baştan sona eşit aralıklı {len(att.images)} kare ekte (ses yok; yalnızca bu kareleri görüyorsun)'

def _folder(att: 'Attachment', path: 'str') -> 'None':
    entries = sorted(os.scandir(path), key=(lambda e: (not e.is_dir(), e.name.casefold())))
    entries = [e for e in entries if not e.name.startswith('.') if not paths.IS_WIN if not win_files.hidden(e)]
    rows = []
    for e in entries[:120]:
        try:
            rows.append(f'{e.name}/' if e.is_dir() else f'{e.name} ({human_size(e.stat().st_size)})')
        except OSError:
            rows.append(e.name)
            continue
    att.kind = 'folder'
    att.label = f'KLASÖR · {len(entries)} ÖĞE'
    att.text = '\n'.join(rows) + (f'\n… ve {len(entries) - 120} öğe daha' if len(entries) > 120 else '')
    att.info = f'klasör, {len(entries)} öğe. İçindekiler:'

def _quicklook(att: 'Attachment', path: 'str') -> 'bool':
    '''Bilinmeyen biçim: macOS Quick Look önizlemesi (Pages, Keynote, Excel, SVG…).'''

    if paths.IS_WIN:
        return win_docs.preview(att, path)
    from PIL import Image
    out = Path(tempfile.mkdtemp(prefix='jarvis-ql-'))
    try:
        subprocess.run(['qlmanage', '-t', '-s', str(MAX_SIDE), '-o', str(out), path], capture_output=True, timeout=8)
        made = next(out.glob('*.png'), None)
        if made is None:
            shutil.rmtree(out, ignore_errors=True)
            return False
        img = Image.open(made)
        img.load()
        att.images = [_jpeg(img)]
    except (subprocess.TimeoutExpired, OSError):
        shutil.rmtree(out, ignore_errors=True)
        return False
    shutil.rmtree(out, ignore_errors=True)
    ext = _ext(att.name).upper() or 'DOSYA'
    att.label = f'{ext} · {human_size(att.size)}'
    att.info = f'{ext} dosyası, {human_size(att.size)}. Metni okunamadı; ilk sayfanın önizlemesi ekte'
    return True

def _zip(att: 'Attachment', path: 'str') -> 'None':
    import zipfile
    with zipfile.ZipFile(path) as z:
        pass
    infos = [i for i in z.infolist() if not i.filename.startswith(('__MACOSX/', '.'))]
    rows = [f'{i.filename} ({human_size(i.file_size)})' if not i.is_dir() else i.filename for i in infos[:150]]
    files = sum((not i.is_dir() for i in infos))
    att.kind = 'folder'
    att.label = f'ZIP · {files} DOSYA'
    att.text = '\n'.join(rows) + (f'\n… ve {len(infos) - 150} öğe daha' if len(infos) > 150 else '')
    att.info = f'zip arşivi, {human_size(att.size)}, içinde {files} dosya (açılmadı). İçindekiler:'

def _looks_text(path: 'str') -> 'bool':
    try:
        with open(path, 'rb') as f:
            head = f.read(8192)
        if b'\x00' in head:
            return False
        head.decode('utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    return True

def from_path(path: 'str') -> 'Attachment':
    '''Dosyayı modele gidecek hâle getirir. Hata olursa `error` dolu döner, istisna atmaz.'''

    path = os.path.abspath(os.path.expanduser(path))
    name = os.path.basename(path.rstrip('/')) or path
    att = Attachment(name=name, path=path)
    started = time.monotonic()
    try:
        if os.path.isdir(path):
            _folder(att, path)
            return att
        att.size = os.path.getsize(path)
        ext = _ext(name)
        if ext in IMAGE_EXT:
            _image(att, path)
        elif ext == 'pdf':
            _pdf(att, path)
        elif ext in TEXT_EXT:
            _text(att, path)
        elif ext in DOC_EXT:
            _doc(att, path)
        elif ext in VIDEO_EXT:
            _video(att, path)
        elif ext in AUDIO_EXT:
            att.kind = 'audio'
            att.label = f'SES · {human_size(att.size)}'
            att.info = f'ses dosyası, {human_size(att.size)}. İçeriğini dinleyemiyorsun'
        elif ext == 'zip':
            _zip(att, path)
        elif _looks_text(path):
            _text(att, path)
        elif ext in NO_PREVIEW_EXT or not _quicklook(att, path):
            att.label = f'DOSYA · {human_size(att.size)}'
            kind = f'{ext.upper()} dosyası' if ext else 'bilinmeyen türde bir dosya'
            att.info = f'{kind}, {human_size(att.size)}; içeriği okunamadı'
    except PermissionError:
        att.error = 'Erişim izni yok'
        att.info = 'dosya; erişim izni olmadığı için okunamadı' if paths.IS_WIN else 'dosya; macOS erişim izni vermediği için okunamadı'
    except FileNotFoundError:
        att.error = 'Dosya bulunamadı'
        att.info = 'dosya; bulunamadı'
    except Exception as exc:
        log('ek okunamadı:', name, exc)
        att.error = 'Okunamadı'
        att.info = f'dosya; okunamadı ({str(exc)[:80]})'
    while True:
        if not att.label:
            att.label = (_ext(name).upper() or 'DOSYA') + (f' · {human_size(att.size)}' if att.size else '')
        if att.images and not att.thumb:
            att.thumb = _thumb(att.images[0])
        log(f'ek hazır: {name} ({att.kind}, {len(att.images)} görsel, {len(att.text)} karakter, {time.monotonic() - started:.2f} sn)')
        return att

def from_data(name: 'str', data: 'bytes') -> 'Attachment':
    '''Yapıştırılan (⌘V) ya da tarayıcıdan sürüklenen, yolu olmayan dosya.'''

    if len(data) > MAX_DATA:
        return Attachment(name=name, error='Çok büyük', info='dosya; çok büyük olduğu için alınmadı', label=human_size(len(data)))
    INBOX.mkdir(parents=True, exist_ok=True)
    for old in INBOX.iterdir():
        try:
            if time.time() - old.stat().st_mtime > 86400:
                old.unlink()
        except OSError:
            continue
    safe = re.sub('[^\\w.\\- ]+', '_', name).strip() or 'dosya'
    target = INBOX / f'{int(time.time() * 1000)}-{safe}'
    target.write_bytes(data)
    att = from_path(str(target))
    att.name = name
    return att

def to_parts(items: 'list[Attachment]') -> 'list[tuple[str, Any]]':
    '''Modele gidecek parçalar: her ek için başlık, görseller ve metni.'''

    parts = []
    budget = MAX_TOTAL_TEXT
    for i, att in enumerate(items, 1):
        where = f' (konum: {att.path})' if att.path and not att.path.startswith(str(INBOX)) else ''
        parts.append(('text', f'[Ek {i}: {att.name} — {att.info}]{where}'))
        for jpeg in att.images:
            parts.append(('image', jpeg))
        if not att.text:
            continue
        if not budget > 0:
            continue
        text = att.text[:budget]
        budget -= len(text)
        parts.append(('text', text + ('\n[… kesildi]' if len(text) < len(att.text) else '')))
        continue
    return parts

def describe(items: 'list[Attachment]') -> 'str':
    '''Sistem notlarında: "bu fotoğrafı", "bu 3 dosyayı".'''

    if len(items) == 1:
        return {'image': 'bu fotoğrafı', 'pdf': "bu PDF'yi", 'video': 'bu videoyu', 'folder': 'bu klasörü'}.get(items[0].kind, 'bu dosyayı')
    if all((a.kind == 'image' for a in items)):
        return f'bu {len(items)} fotoğrafı'
    return f'bu {len(items)} dosyayı'


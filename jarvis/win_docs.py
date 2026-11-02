"""Belgeler (Windows): PDF, Office/ODF/RTF/HTML okuma, Word belgesi yazma, Excel'in liste ayırıcısı.

Mac'te bunları macOS yapıyor (Quartz PDF, textutil, Quick Look). Windows'ta Office kurulu olmayabilir, bu yüzden
dosyalar doğrudan okunur: docx/xlsx/pptx ve ODT/ODS/ODP zip içinde XML, RTF ve HTML düz metne çevrilir. Eski
ikili biçimler (.doc, .xls, .ppt) okunamaz. PDF için PDFium (pypdfium2); PDFium aynı anda tek iş parçacığından
kullanılmalı (kilit). attachments.py ve files.py buradaki işlevleri yalnızca Windows'ta çağırır.

Dosyalar güvenilmez: zip içindeki parçalar beyan edilen boyuta değil gerçekten okunan bayta göre sınırlanır
(zip bombası), tablolar akışla okunur ve yeterince metin toplanınca bırakılır (büyük Excel), sayı içeren
öğeler (ODF boşluk tekrarı, tekrarlanan hücre/satır) üstten sınırlanır.
"""

from __future__ import annotations
import codecs
import ctypes
import datetime as dt
import html
import re
import threading
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET
from . import win_files
MAX_PART = 41943040
MAX_STREAM = 419430400
MAX_FILE = 16777216
TEXT_STOP = 40000
OFFICE_PREVIEW = {'odp', 'ods', 'docm', 'pptx', 'xlsm', 'xlsx'}
_SHORTCUTS = {'lnk', 'pif', 'scf', 'url'}
_pdf_lock = threading.Lock()

def _pdf_render(doc, index: 'int', side: 'int'):
    page = doc[index]
    try:
        w, h = page.get_size()
        scale = side / max(w, h, 1)
    finally:
        page.close()
    return page.render(scale=scale).to_pil().copy()

def read_pdf(att, path: 'str') -> 'None':
    """attachments._pdf'nin Windows hâli: metni; metni yoksa (taranmış) ilk sayfaların görüntüsü."""

    import pypdfium2 as pdfium
    from . import attachments as A
    att.kind = 'pdf'
    with _pdf_lock:
        try:
            doc = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as exc:
            if 'password' in str(exc).lower():
                att.label = 'PDF · ŞİFRELİ'
                att.info = 'PDF, şifreli; içeriği okunamadı'
                att.error = 'Şifreli PDF'
                return
            raise ValueError('PDF açılamadı') from exc
        try:
            pages = len(doc)
            att.label = f'PDF · {pages} SAYFA'
            chunks, size = [], 0
            for i in range(pages):
                page = doc[i]
                try:
                    textpage = page.get_textpage()
                    chunks.append(textpage.get_text_range().replace('￾', ''))
                    textpage.close()
                finally:
                    page.close()
                size += len(chunks[-1])
                if size > TEXT_STOP:
                    break
            text, cut = A._clip('\n\n'.join(chunks))
            cut = cut or len(chunks) < pages
            if len(text) >= 200 or len(text) >= 40 * pages:
                att.text = text
                att.info = f'PDF, {pages} sayfa. Metni aşağıda' + (f' (ilk {len(text):,} karakter; gerisi kesildi)' if cut else '') + ':'
                if pages:
                    att.thumb = A._thumb(A._jpeg(_pdf_render(doc, 0, A.THUMB_SIDE * 2), A.THUMB_SIDE * 2))
                doc.close()
                return
        finally:
            doc.close()
        try:
            count = min(pages, A.PDF_PAGE_IMAGES)
            for i in range(count):
                att.images.append(A._jpeg(_pdf_render(doc, i, A.MAX_SIDE)))
        finally:
            doc.close()
    shown = f'ilk {count} sayfanın görüntüsü' if count < pages else 'sayfaların görüntüsü'
    if text:
        att.text = text
        att.info = f'PDF, {pages} sayfa, çok az metin var; {shown} ve metni aşağıda:'
        return
    att.info = f'PDF, {pages} sayfa, metin katmanı yok (taranmış olabilir); {shown} ekte'

def pdf_thumb(path: 'str | Path', side: 'int'):
    '''Dosya kartı için ilk sayfa (PIL) ya da None (şifreli/bozuk).'''

    import pypdfium2 as pdfium
    with _pdf_lock:
        try:
            doc = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError:
            return
        try:
            pass
        finally:
            doc.close()
        return _pdf_render(doc, 0, side) if len(doc) else None

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PR = '{http://schemas.openxmlformats.org/package/2006/relationships}'
OFFICE = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
TEXT = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
TABLE = '{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
DRAW = '{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}'
PRESENTATION = '{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}'

class _Capped:
    '''Zip parçasını okurken gerçekten açılan baytı sayar: beyan edilen boyut sahte olabilir (zip bombası).'''

    def __init__(self, raw, limit: 'int') -> 'None':
        self.raw, self.left = raw, limit

    def read(self, n: 'int'=-1) -> 'bytes':
        data = self.raw.read(65536 if n is None or n < 0 else min(n, 1048576))
        self.left -= len(data)
        if self.left < 0:
            raise ValueError('belge çok büyük')
        return data


def _xml(z: 'zipfile.ZipFile', name: 'str') -> 'ET.Element':
    with z.open(name) as f:
        data = f.read(MAX_PART + 1)
    if len(data) > MAX_PART:
        raise ValueError('belge çok büyük')
    return ET.fromstring(data)

def _stream(z: 'zipfile.ZipFile', name: 'str'):
    '''(olay, öğe) akışı; işlenen öğe bitince ebeveyninden çıkarılır, bellek büyümez.'''

    stack = []
    with z.open(name) as f:
        for event, el in ET.iterparse(_Capped(f, MAX_STREAM), events=('start', 'end')):
            if event == 'start':
                stack.append(el)
                yield (event, el)
                continue
            stack.pop()
            yield (event, el)
            if not el.get('_done'):
                continue
            if stack:
                stack[-1].remove(el)

def _rels(z: 'zipfile.ZipFile', name: 'str', base: 'str') -> 'dict[str, str]':
    '''İlişki kimliği → zip içindeki yol.'''

    try:
        root = _xml(z, name)
    except KeyError:
        return {}
    out = {}
    for rel in root.iter(PR + 'Relationship'):
        target = rel.get('Target') or ''
        out[rel.get('Id')] = target.lstrip('/') if target.startswith('/') else base + target
    return out

_W_SKIP = {W + 'pPr', W + 'rPr', W + 'del', W + 'moveFrom', MC + 'Fallback', W + 'sectPr'}
_W_WRAP = {W + 'sdt', W + 'sdtContent', W + 'customXml', W + 'smartTag'}

def _w_children(el: 'ET.Element', tag: 'str'):
    '''Doğrudan çocuklar (içerik denetimi gibi sarmalayıcıların içi dahil); iç içe tablolara inmez.'''

    for child in el:
        if child.tag == tag:
            yield child
        else:
            if child.tag not in _W_WRAP:
                continue
            yield from _w_children(child, tag)

def _w_inline(el: 'ET.Element', out: 'list[str]', extra: 'list[str]') -> 'None':
    for child in el:
        tag = child.tag
        if tag == W + 't':
            out.append(child.text or '')
        elif tag == W + 'tab':
            out.append('\t')
        elif tag in (W + 'br', W + 'cr'):
            out.append('\n')
        elif tag == W + 'txbxContent':
            _w_body(child, extra)
        else:
            if tag in _W_SKIP:
                continue
            _w_inline(child, out, extra)

def _w_para(p: 'ET.Element', lines: 'list[str]') -> 'None':
    out = []
    extra = []
    _w_inline(p, out, extra)
    text = ''.join(out)
    listed = p.find(f'{W}pPr/{W}numPr') is not None
    lines.append(f'• {text}' if listed and text.strip() else text)
    lines.extend(extra)

def _w_body(el: 'ET.Element', lines: 'list[str]') -> 'None':
    for child in el:
        if child.tag == W + 'p':
            _w_para(child, lines)
            continue
        if child.tag == W + 'tbl':
            for tr in _w_children(child, W + 'tr'):
                cells = []
                for tc in _w_children(tr, W + 'tc'):
                    sub = []
                    _w_body(tc, sub)
                    cells.append(' '.join((s.strip() for s in sub if s.strip())))
                if any(cells):
                    lines.append(' | '.join(cells))
            continue
        if child.tag not in _W_WRAP and child.tag != W + 'body':
            continue
        _w_body(child, lines)
        continue

def _docx(z: 'zipfile.ZipFile') -> 'str':
    lines = []
    _w_body(_xml(z, 'word/document.xml'), lines)
    return '\n'.join(lines)

def _column(ref: 'str | None') -> 'int | None':
    '''"C12" → 2 (sütun dizini); yoksa None.'''

    m = re.match('([A-Z]{1,3})\\d', ref or '')
    if not m:
        return
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1

def _xlsx(z: 'zipfile.ZipFile') -> 'str':
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for event, el in _stream(z, 'xl/sharedStrings.xml'):
            if event != 'end':
                continue
            if el.tag == S + 'si':
                shared.append(''.join((t.text or '' for t in el.iter(S + 't') if t not in el.findall(f'.//{S}rPh/{S}t'))))
                el.clear()
                el.set('_done', '1')
    rels = _rels(z, 'xl/_rels/workbook.xml.rels', 'xl/')
    out = []
    size = 0
    for sheet in _xml(z, 'xl/workbook.xml').iter(S + 'sheet'):
        target = rels.get(sheet.get(R + 'id'))
        if not target or target not in z.namelist():
            continue
        out.append(f'## Sayfa: {sheet.get('name')}')
        for event, row in _stream(z, target):
            if event != 'end' or row.tag != S + 'row':
                pass
        continue
        cells = []
        for c in row.iter(S + 'c'):
            kind, v = c.get('t'), c.find(S + 'v')
            if kind == 's' and v is not None:
                if (v.text or '').isdigit() and int(v.text) < len(shared):
                    value = shared[int(v.text)]
                elif kind == 'inlineStr':
                    value = ''.join((t.text or '' for t in c.iter(S + 't')))
                elif kind == 'b' and v is not None:
                    value = 'DOĞRU' if v.text == '1' else 'YANLIŞ'
                else:
                    value = v.text if v is not None and v.text else ''
            col = _column(c.get('r'))
            if col is not None and col > len(cells) and col - len(cells) <= 1000:
                cells += [''] * (col - len(cells))
            cells.append(value)
            continue
        row.clear()
        row.set('_done', '1')
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            out.append(' | '.join(cells))
            size += len(out[-1])
        if not size > TEXT_STOP:
            continue
        return '\n'.join(out)
        continue
    return '\n'.join(out)

def _pptx(z: 'zipfile.ZipFile') -> 'str':
    rels = _rels(z, 'ppt/_rels/presentation.xml.rels', 'ppt/')
    order = [rels.get(s.get(R + 'id')) for s in _xml(z, 'ppt/presentation.xml').iter(P + 'sldId')]
    out = []
    for n, target in enumerate([t for t in order if t if t in z.namelist()], 1):
        paras = []
        root = _xml(z, target)
        fallbacks = {id(el) for fb in root.iter(MC + 'Fallback') for el in fb.iter()}
        for p in root.iter(A_NS + 'p'):
            if id(p) in fallbacks:
                continue
            text = ''.join(('\n' for el in p.iter()
                 if el.tag in (A_NS + 't', A_NS + 'br')
                 if el.tag != A_NS + 't'
                 if el.text))
            if text.strip():
                paras.append(text)
        out.append(f'## Slayt {n}\n' + '\n'.join(paras))
        if sum(map(len, out)) > TEXT_STOP:
            break
    return '\n\n'.join(out)

_ODF_INLINE_SKIP = {TEXT + 'note', DRAW + 'frame', OFFICE + 'annotation', OFFICE + 'annotation-end', TEXT + 'tracked-changes'}
_ODF_SKIP = {TEXT + 'tracked-changes', OFFICE + 'annotation', PRESENTATION + 'notes', TEXT + 'note-citation'}

def _count(value: 'str | None') -> 'int':
    """ODF'deki tekrar sayısı (dosyadan gelir: bozuk ya da devasa olabilir)."""

    if value and value.isdigit() and len(value) < 10:
        return max(1, int(value))
    return 1

def _odf_text(el: 'ET.Element') -> 'str':
    out = [el.text or '']
    for child in el:
        if child.tag == TEXT + 's':
            out.append(' ' * min(_count(child.get(TEXT + 'c')), 100))
        elif child.tag == TEXT + 'tab':
            out.append('\t')
        elif child.tag == TEXT + 'line-break':
            out.append('\n')
        elif child.tag not in _ODF_INLINE_SKIP:
            out.append(_odf_text(child))
        out.append(child.tail or '')
    return ''.join(out)

def _odf_extras(el: 'ET.Element', out: 'list[str]') -> 'None':
    '''Paragrafın içindeki dipnot ve metin kutusu: ayrı satırlar.'''

    for child in el:
        if child.tag in (TEXT + 'note-body', DRAW + 'text-box'):
            _odf_walk(child, out)
        else:
            if child.tag in _ODF_SKIP:
                continue
            _odf_extras(child, out)

def _odf_walk(el: 'ET.Element', out: 'list[str]') -> 'None':
    for child in el:
        if child.tag in _ODF_SKIP:
            continue
        if child.tag in (TEXT + 'p', TEXT + 'h'):
            out.append(_odf_text(child))
            _odf_extras(child, out)
        else:
            _odf_walk(child, out)
        if sum(map(len, out)) > TEXT_STOP * 2:
            return

def _ods(z: 'zipfile.ZipFile') -> 'str':
    out = []
    size = 0
    for event, el in _stream(z, 'content.xml'):
        if event == 'start' and el.tag == TABLE + 'table':
            out.append(f'## Sayfa: {el.get(TABLE + 'name')}')
        if event != 'end' or el.tag != TABLE + 'table-row':
            continue
        cells = []
        for cell in el:
            if cell.tag not in (TABLE + 'table-cell', TABLE + 'covered-table-cell'):
                continue
            text = '\n'.join((_odf_text(p) for p in cell if p.tag in (TEXT + 'p', TEXT + 'h')))
            repeat = _count(cell.get(TABLE + 'number-columns-repeated'))
            cells += [text] * min(repeat, 50 if text else 1000)
            if len(cells) > 2000:
                break
        rows = min(_count(el.get(TABLE + 'number-rows-repeated')), 50)
        el.clear()
        el.set('_done', '1')
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            continue
        line = ' | '.join(cells)
        out += [line] * rows
        size += len(line) * rows
        if size > TEXT_STOP:
            break
    return '\n'.join(out)

def _odf(z: 'zipfile.ZipFile', ext: 'str') -> 'str':
    if ext == 'ods':
        return _ods(z)
    root = _xml(z, 'content.xml')
    out = []
    _odf_walk(root.find(OFFICE + 'body') if root.find(OFFICE + 'body') is not None else root, out)
    return '\n'.join(out)

_RTF_TOKEN = re.compile("\\\\([a-z]{1,32})(-?\\d{1,10})? ?|\\\\'([0-9a-f]{2})|\\\\([^a-z])|([{}])|[\\r\\n]+|([^\\\\{}\\r\\n]+)", re.I | re.S)
_RTF_SKIP = {'info', 'pict', 'title', 'author', 'buptim', 'footer', 'header', 'object', 'pntext', 'pntxta', 'pntxtb', 'revtbl', 'revtim', 'bkmkend', 'comment', 'company', 'creatim', 'doccomm', 'filetbl', 'fldinst', 'fonttbl', 'footerf', 'footerl', 'footerr', 'headerf', 'headerl', 'headerr', 'mmathPr', 'printim', 'rsidtbl', 'subject', 'xmlopen', 'colortbl', 'footnote', 'keywords', 'listtext', 'operator', 'pgdsctbl', 'xmlnstbl', 'bkmkstart', 'datastore', 'generator', 'listtable', 'themedata', 'nonshppict', 'stylesheet', 'latentstyles', 'listoverridetable', 'colorschememapping'}
_RTF_CHARS = {'par': '\n', 'line': '\n', 'sect': '\n\n', 'page': '\n\n', 'tab': '\t', 'cell': ' | ', 'row': '\n', 'emdash': '—', 'endash': '–', 'bullet': '•', 'lquote': '‘', 'rquote': '’', 'ldblquote': '“', 'rdblquote': '”', '~': ' ', '_': '-', '\n': '\n', '\r': '\n'}
_RTF_CHARSETS = {77: 'mac_roman', 128: 'cp932', 129: 'cp949', 134: 'gbk', 136: 'cp950', 161: 'cp1253', 162: 'cp1254', 163: 'cp1258', 177: 'cp1255', 178: 'cp1256', 186: 'cp1257', 204: 'cp1251', 222: 'cp874', 238: 'cp1250'}
_MAC_PAGES = {'10000': 'mac_roman', '10006': 'mac_greek', '10007': 'mac_cyrillic', '10029': 'mac_latin2', '10081': 'mac_turkish'}

def _codec(name: 'str', fallback: 'str'='cp1252') -> 'str':
    try:
        return codecs.lookup(name).name
    except LookupError:
        return fallback

def _rtf(data: 'bytes') -> 'str':
    raw = data.decode('latin-1')
    page = re.search('\\\\ansicpg(\\d+)', raw[:4096])
    default = _codec(_MAC_PAGES.get(page.group(1), f'cp{page.group(1)}')) if page else 'cp1252'
    fonts = {}
    for m in re.finditer('\\\\f(\\d+)(?:\\\\[a-z]+-?\\d* ?)*?\\\\fcharset(\\d+)', raw[:262144]):
        charset = int(m.group(2))
        if charset in _RTF_CHARSETS:
            fonts[m.group(1)] = _codec(_RTF_CHARSETS[charset], default)
    stack = []
    ignorable, ucskip, skip, codepage = False, 1, 0, default
    out = []
    pending = bytearray()
    for m in _RTF_TOKEN.finditer(raw):
        word, arg, hexcode, symbol, brace, char = m.groups()
        if hexcode is None and pending:
            out.append(pending.decode(codepage, 'replace'))
            pending.clear()
        if brace:
            skip = 0
            if brace == '{':
                stack.append((ucskip, ignorable, codepage))
                continue
            if not stack:
                continue
            ucskip, ignorable, codepage = stack.pop()
            continue
        if symbol:
            skip = 0
            if symbol == '*':
                ignorable = True
                continue
            if ignorable:
                continue
            out.append(_RTF_CHARS.get(symbol, symbol if symbol in '\\{}' else ''))
            continue
        if word:
            skip = 0
            if word in _RTF_SKIP:
                ignorable = True
                continue
            if ignorable:
                continue
            if word in _RTF_CHARS:
                out.append(_RTF_CHARS[word])
                continue
            if word == 'f' and arg:
                codepage = fonts.get(arg, default)
                continue
            if word == 'uc' and arg:
                ucskip = int(arg)
                continue
            if word != 'u':
                continue
            if not arg:
                continue
            code = int(arg)
            out.append(chr(code + 65536 if code < 0 else code))
            skip = ucskip
            continue
        if hexcode:
            if skip:
                skip -= 1
                continue
            if ignorable:
                continue
            pending.append(int(hexcode, 16))
            continue
        if not char:
            continue
        if skip:
            drop = min(skip, len(char))
            char, skip = char[drop:], skip - drop
        if not char:
            continue
        if ignorable:
            continue
        out.append(char)
        continue
    if pending:
        out.append(pending.decode(codepage, 'replace'))
    return ''.join(out).encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')

class _HtmlText(HTMLParser):
    BLOCK = {'p', 'br', 'dd', 'dt', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'tr', 'ul', 'div', 'pre', 'table', 'footer', 'header', 'article', 'section', 'blockquote'}
    HIDDEN = {'style', 'title', 'script', 'noscript', 'template'}
    def __init__(self) -> 'None':
        super().__init__(convert_charrefs=True)
        self.out = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
            return
        if tag in self.BLOCK:
            if tag == 'li':
                self.out.append('\n• ')
                return
            None('\n')
            return
        if tag in ('td', 'th'):
            self.out.append(' | ')

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
            return
        if tag in self.BLOCK:
            self.out.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(re.sub('\\s+', ' ', data))


def _decode(data: 'bytes', enc: 'str') -> 'str':
    '''Katı çözer; yalnızca sondaki (kesilmiş) yarım karakter atılır.'''

    try:
        return data.decode(enc)
    except UnicodeDecodeError as exc:
        if exc.start >= len(data) - 4:
            return data[:exc.start].decode(enc)
        raise

def _html(data: 'bytes') -> 'str':
    boms = (codecs.BOM_UTF8, 'utf-8-sig'), (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')
    candidates = [enc for bom, enc in boms if data.startswith(bom)]
    found = re.search('charset=[\\"\']?([\\w-]+)', data[:4096].decode('ascii', 'ignore'), re.I)
    if found:
        candidates.append(found.group(1))
    text = None
    for enc in candidates + ['utf-8', 'cp1254']:
        try:
            text = _decode(data, enc)
        except (UnicodeDecodeError, LookupError):
            continue
        break
    if text is None:
        text = data.decode('latin-1')
    parser = _HtmlText()
    parser.feed(text)
    parser.close()
    lines = [line.strip() for line in ''.join(parser.out).split('\n')]
    return re.sub('\\n{3,}', '\n\n', '\n'.join(lines)).strip()

_LABELS = {'xlsx': 'TABLO', 'xlsm': 'TABLO', 'ods': 'TABLO', 'pptx': 'SUNUM', 'odp': 'SUNUM'}

def doc_text(path: 'str', ext: 'str') -> 'tuple[str, bool]':
    '''(belgenin düz metni, dosya sonuna kadar okunmadı mı); okunamayan biçimde ValueError.'''

    if ext in ('rtf', 'html', 'htm'):
        with open(path, 'rb') as f:
            data = f.read(MAX_FILE + 1)
        cut = len(data) > MAX_FILE
        data = data[:MAX_FILE]
        if ext == 'rtf':
            return _rtf(data), cut
        return _html(data), cut
    if ext in ('docx', 'docm', 'xlsx', 'xlsm', 'pptx', 'odt', 'ods', 'odp'):
        try:
            with zipfile.ZipFile(path) as z:
                if ext in ('docx', 'docm'):
                    return _docx(z), False
                if ext in ('xlsx', 'xlsm'):
                    return _xlsx(z), False
                if ext == 'pptx':
                    return _pptx(z), False
                return _odf(z, ext), False
        except (zipfile.BadZipFile, KeyError, ET.ParseError, EOFError) as exc:
            raise ValueError('belge bozuk ya da şifreli') from exc
    old = {'doc': 'Word', 'xls': 'Excel', 'ppt': 'PowerPoint'}.get(ext)
    if old:
        raise ValueError(f'eski {old} biçimi (.{ext}) okunamıyor; .{ext}x olarak kaydedip gönder')
    raise ValueError(f".{ext} biçimi Windows'ta okunamıyor")

def read_doc(att, path: 'str') -> 'None':
    """attachments._doc'un Windows hâli (Office olmadan)."""

    from . import attachments as A
    ext = A._ext(att.name)
    raw, partial = doc_text(path, ext)
    text, cut = A._clip(raw)
    cut = cut or partial or len(raw) >= TEXT_STOP
    if not text:
        raise ValueError('belge metni okunamadı')
    att.kind = 'doc'
    att.text = text
    att.label = f'{_LABELS.get(ext, 'BELGE')} · {A.human_size(att.size)}'
    what = {'TABLO': 'tablo (hücreler | ile ayrık; tarih ve saatler Excel sayısı olarak görünebilir)', 'SUNUM': 'sunum (slayt slayt)'}.get(_LABELS.get(ext, ''), 'belge')
    att.info = f'{what}. Metni aşağıda' + (' (baştan bir kısmı; gerisi kesildi)' if cut else '') + ':'

def preview(att, path: 'str') -> 'bool':
    """attachments._quicklook'un Windows hâli: Excel/PowerPoint/ODF'nin metni, diğerlerinde Gezgin'in önizlemesi."""

    from . import attachments as A
    ext = A._ext(att.name)
    if ext in OFFICE_PREVIEW:
        read_doc(att, path)
        return True
    if ext in _SHORTCUTS:
        return False
    img = win_files.thumbnail(path, A.MAX_SIDE, download=True)
    if img is None:
        return False
    att.images = [A._jpeg(img)]
    label = ext.upper() or 'DOSYA'
    att.label = f'{label} · {A.human_size(att.size)}'
    att.info = f'{label} dosyası, {A.human_size(att.size)}. Metni okunamadı; önizlemesi ekte'
    return True

def image_fallback(path: 'str'):
    """PIL'in açamadığı görsel (HEIC gibi): Windows'un kendi çözücüsüyle (yüklüyse). Yoksa ValueError."""

    from . import attachments as A
    img = win_files.thumbnail(path, A.MAX_SIDE, download=True)
    if img is None:
        raise ValueError("görsel biçimi tanınmadı (HEIC için Microsoft Store'dan HEIF Görüntü Uzantıları gerekir)")
    return img

_CONTENT_TYPES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>'
_ROOT_RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>'
_DOC_RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
_WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_BAD_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿���-���]')

def _style(sid: 'str', name: 'str', size: 'int', bold: 'bool'=True, space: 'int'=120) -> 'str':
    return f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{space * 2}" w:after="{space}"/><w:outlineLvl w:val="{int(sid[-1]) - 1 if sid[-1].isdigit() else 0}"/></w:pPr><w:rPr>{'<w:b/>' if bold else ''}<w:sz w:val="{size}"/></w:rPr></w:style>'

_STYLES = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_WNS}><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" w:eastAsia="Calibri"/><w:sz w:val="24"/><w:lang w:val="tr-TR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' + _style('Heading1', 'heading 1', 32) + _style('Heading2', 'heading 2', 28) + _style('Heading3', 'heading 3', 26) + _style('Heading4', 'heading 4', 24) + '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/><w:ind w:left="720" w:hanging="360"/></w:pPr></w:style></w:styles>'

def _runs(text: 'str') -> 'str':
    '''**kalın** ve *italik* → Word parçaları.'''

    out = []
    for part in re.split('(\\*\\*.+?\\*\\*|(?<![\\w*])\\*(?!\\s).+?(?<!\\s)\\*(?![\\w*]))', text):
        if part:
            props = ''
            if part.startswith('**') and part.endswith('**') and len(part) > 4:
                part, props = part[2:-2], '<w:b/>'
            elif part.startswith('*') and part.endswith('*') and len(part) > 2:
                part, props = part[1:-1], '<w:i/>'
            rpr = f'<w:rPr>{props}</w:rPr>' if props else ''
            out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{html.escape(part, quote=False)}</w:t></w:r>')
    return ''.join(out)

def _paragraphs(content: 'str') -> 'str':
    out = []
    for raw in content.splitlines():
        line = raw.rstrip()
        heading = re.match('^(#{1,4})\\s+(.*)', line)
        bullet = re.match('^\\s*[-*•]\\s+(.*)', line)
        number = re.match('^\\s*(\\d+[.)])\\s+(.*)', line)
        if heading:
            out.append(f'<w:p><w:pPr><w:pStyle w:val="Heading{len(heading.group(1))}"/></w:pPr>{_runs(heading.group(2))}</w:p>')
            continue
        if bullet or number:
            mark, body = ('•', bullet.group(1)) if bullet else (number.group(1), number.group(2))
            out.append(f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr><w:r><w:t xml:space="preserve">{mark}</w:t></w:r><w:r><w:tab/></w:r>{_runs(body)}</w:p>')
            continue
        if line.strip():
            out.append(f'<w:p>{_runs(line)}</w:p>')
            continue
        out.append('<w:p/>')
        continue
    return ''.join(out)

def write_docx(target: 'Path', content: 'str', title: 'str') -> 'None':
    """Basit Markdown'dan (başlık, madde, numara, kalın, italik) Word belgesi; Office gerekmez."""

    content, title = _BAD_XML.sub('', content), _BAD_XML.sub('', title)
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    core = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{html.escape(title, quote=False)}</dc:title><dc:creator>JARVIS</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>'
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_WNS}><w:body>{_paragraphs(content)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>'
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CONTENT_TYPES)
        z.writestr('_rels/.rels', _ROOT_RELS)
        z.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', _STYLES)
        z.writestr('docProps/core.xml', core)

def list_separator() -> 'str':
    '''Windows bölge ayarındaki liste ayırıcısı (Türkçe: ";"); Excel CSV'yi bununla açar.'''

    buf = ctypes.create_unicode_buffer(8)
    if ctypes.windll.kernel32.GetLocaleInfoEx(None, 12, buf, len(buf)) and buf.value in (',', ';', '\t', '|'):
        return buf.value
    return ','

# WARNING: Decompyle incomplete

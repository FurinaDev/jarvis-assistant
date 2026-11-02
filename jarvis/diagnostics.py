'''TEŞHİSİ KOPYALA (Ayarlar › HAKKINDA): test eden kişi sorunu tek mesajla anlatsın (9 Ekim 2026, 20 kişilik deneme).

Panoya giden metin: sürüm, sistem, ses aygıtları, izin, model, açık mikrofon ve günlükten JARVIS'in kendi ses ve
bağlantı satırları. Anahtar, söz, dosya ya da kişi adı yok: günlük satırları bir izin listesiyle süzülür (yalnızca
KEEP'teki başlangıçlarla başlayanlar; "ek → … soru:" gibi kullanıcının yazdığını taşıyan satırlar alınmaz).
'''

from __future__ import annotations
import datetime as dt
import platform
import re
from . import (VERSION, paths, permissions, settings)
KEEP = re.compile('^(JARVIS \\d|mikrofon|hoparlör|yankı engelleme|ses aygıt|ses yeniden|ses: |ses yardımcısı|varsayılan ses|cevap bekçisi|cevap gecikmesi|bağlantı yok|oturum|sunucu oturumu|sessiz tur|kullanıcı sesi tepe|sahne mikrofonu|ilk açılış bitti|sürdürme anahtarı|arama: |models/[\\w.-]+ kullanılamıyor|gemini-[\\w.-]+ → |ana modele|spotify-hata|söz kesme|söz bitti|model sustu|model sesi atıldı|tur kesildi)')
LOG_LINES = 40
_STAMP = re.compile('^(\\d{4}-\\d\\d-\\d\\d \\d\\d:\\d\\d:\\d\\d) (.*)$')

def _log_tail() -> 'list[str]':
    """Günlüğün son ~300 KB'ından KEEP'e uyan son LOG_LINES satır."""

    try:
        with paths.LOG_FILE.open('rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 300000))
            text = fh.read().decode('utf-8', errors='replace')
    except OSError:
        return []
    keep = []
    for line in text.splitlines()[1:]:
        m = _STAMP.match(line)
        if not m:
            continue
        if KEEP.match(m.group(2)):
            keep.append(f'{m.group(1)[5:]} {m.group(2)[:300]}')
    return keep[-LOG_LINES:]

def report(brain) -> 'str':
    out = [f'JARVIS {VERSION} teşhis · {dt.datetime.now():%Y-%m-%d %H:%M}']
    if paths.IS_WIN:
        from . import win_diag
        out += win_diag.lines()
    else:
        out.append(f'macOS {platform.mac_ver()[0] or '?'} ({platform.machine()})')
        out.append(f'İzin: mikrofon {permissions.status('microphone')}, kamera {permissions.status('camera')}')
    model = str(getattr(brain, 'model', '') or '?').split('/')[-1]
    try:
        from .brain.gemini_live import LIVE_MODELS
        backup = model != LIVE_MODELS[0].split('/')[-1]
    except Exception:
        backup = False
    out.append(f'Model: {model}' + (' (yedek: ana model aksadı)' if backup else ''))
    info = dict(getattr(brain, 'mic_info', {}) or {})
    problem = getattr(brain, '_mic_problem', '')
    mic = 'KAPALI (MİKROFON/F4)' if settings.get('mic_enabled', True) is False else f'açık · “{info.get('device') or 'varsayılan'}” · {info.get('path') or '?'}' if info else 'açılamadı'
    out.append(f'JARVIS mikrofonu: {mic}' + (f' · sorun: {problem}' if problem else ''))
    tail = _log_tail()
    if tail:
        out += ['', 'Son ses ve bağlantı olayları:', *tail]
    return '\n'.join(out)


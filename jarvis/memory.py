'''
Kalıcı bellek — JSON dosyasına kaydedilir.
'''

import json
import re
import time
import unicodedata
from pathlib import Path
from . import paths
MEMORY_FILE = paths.MEMORY_FILE

def load_memory() -> dict:
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return {}
    return {}

def update_memory(data: dict):
    mem = load_memory()
    _deep_merge(mem, data)
    _write_memory(mem)

def _write_memory(mem: dict):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)

def _deep_merge(base: dict, update: dict):
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

def _normalize_text(text: str) -> str:
    text = (text or '').strip().casefold()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join((ch for ch in text if not unicodedata.combining(ch)))
    text = text.replace('ı', 'i')
    return ' '.join(text.split())

def _entry_value_text(value) -> str:
    if isinstance(value, dict):
        base = value.get('value')
        if base is not None:
            return str(base)
        return json.dumps(value, ensure_ascii=False)
    return str(value)

_PHONE_LIKE = re.compile('(?<!\\d)(?:\\+|0|5)[\\d\\s().-]{8,18}\\d(?!\\d)')

def hide_numbers(text: str, whole: bool=False) -> str:
    '''Ekranda gösterilecek metinde telefon numaraları: "•••• 67" (son iki rakam). whole: metnin tamamı numaradır
    (kayıtlı WhatsApp kişisi), biçimi ne olursa olsun gizlenir.'''

    def mask(found: str) -> str:
        digits = re.sub('\\D', '', found)
        if len(digits) >= 2:
            return f'•••• {digits[-2:]}'
        return '••••'

    if whole:
        if re.sub('\\D', '', text or ''):
            return mask(text)
    return _PHONE_LIKE.sub((lambda m: mask(m.group()) if 10 <= len(re.sub('\\D', '', m.group())) <= 13 else m.group()), text or '')

def _tokenize_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [token for token in re.split('[^a-z0-9]+', normalized) if token]

def _entry_matches(needle: str, category: str, item_key: str, item_value) -> bool:
    haystacks = [_normalize_text(category), _normalize_text(item_key), _normalize_text(_entry_value_text(item_value))]
    if any((needle in hay for hay in haystacks)):
        return True
    tokens = [tok for tok in _tokenize_text(needle) if len(tok) >= 3]
    if not tokens:
        return False
    entry_tokens = []
    for hay in haystacks:
        entry_tokens.extend(_tokenize_text(hay))
    matched = 0
    for token in tokens:
        if any((token in entry_token in token for entry_token in entry_tokens)):
            matched += 1
    if len(tokens) == 1:
        return matched == 1
    return matched >= min(2, len(tokens))

def forget_all() -> None:
    '''Ayarlar › Hafıza › HEPSİNİ UNUT: bütün kayıtlar silinir; önceki hâli aynı klasörde yedek olarak kalır.'''

    mem = load_memory()
    if mem:
        backup = MEMORY_FILE.with_name(f'{MEMORY_FILE.stem}-yedek-{time.strftime('%Y%m%d-%H%M%S')}.json')
        backup.write_text(json.dumps(mem, indent=2, ensure_ascii=False), encoding='utf-8')
    _write_memory({})

def delete_memory(category: str='', key: str='', match_text: str='') -> str:
    mem = load_memory()
    if not mem:
        return 'Hafizada silinecek bir kayit yok.'
    category = (category or '').strip()
    key = (key or '').strip()
    match_text = (match_text or '').strip()
    if category and key:
        bucket = mem.get(category)
        if isinstance(bucket, dict) and key in bucket:
            del bucket[key]
            if not bucket:
                mem.pop(category, None)
            _write_memory(mem)
            return f'{category}/{key} hafizadan kaldirildi.'
        return 'Bu hafiza kaydini bulamadim.'
    needle = _normalize_text(match_text or key)
    if not needle:
        return 'Silmek icin category/key veya match_text gerekli.'
    for cat, bucket in list(mem.items()):
        if not isinstance(bucket, dict):
            if _entry_matches(needle, cat, cat, bucket):
                del mem[cat]
                _write_memory(mem)
                return f'{cat} hafizadan kaldirildi.'
            continue
        for item_key, item_value in list(bucket.items()):
            if _entry_matches(needle, cat, item_key, item_value):
                del bucket[item_key]
                if not bucket:
                    mem.pop(cat, None)
                _write_memory(mem)
                return f'{cat}/{item_key} hafizadan kaldirildi.'
    return 'Eslestigim bir hafiza kaydi bulamadim.'

def format_memory_for_prompt(memory: dict) -> str:
    if not memory:
        return ''
    lines = ['[KULLANICI HAKKINDA BİLGİLER]']
    for category, items in memory.items():
        if isinstance(items, dict):
            for key, val in items.items():
                if category == 'whatsapp_contacts' and isinstance(val, dict):
                    display_name = val.get('display_name', key)
                    aliases = val.get('aliases', [])
                    alias_str = ''
                    if isinstance(aliases, list) and aliases:
                        alias_str = f' aliases={', '.join((str(a) for a in aliases))}'
                    lines.append(f'  {category}/{display_name}: numarası kayıtlı (adıyla gönder){alias_str}')
                else:
                    value = val.get('value', val) if isinstance(val, dict) else val
                    lines.append(f'  {category}/{key}: {value}')
            continue
        lines.append(f'  {category}: {items}')
        continue
    return '\n'.join(lines)


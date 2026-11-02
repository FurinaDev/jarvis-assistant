'''Çip adları: kullanıcı JARVIS ile FRIDAY'e kendi adını verebilir (Ayarlar › Genel › ÇİP ADLARI).

Telefon uygulamasındaki Brand.swift'in masaüstü hâli. Ad yalnızca çipindir: uygulamanın adı (JARVIS, JARVIS V4,
paket, veri klasörü, J.A.R.V.I.S yazısı, yapanın kartı) değişmez. ULTRON'un adı sabittir. Asistan kendini verilen
adla tanıtır; karakteri, sesi ve rengi aynı kalır. Adlar ayarlarda "chip_names" altında durur; boşsa hazır ad.

- `name(key)`: çipin şu anki adı.
- `genitive`, `accusative`, `dative`: Türkçe ekler, adın son sesine göre ("KAAN'ın", "ECE'yi", "ATLAS'a").
- `rewrite(text)`: hazır metindeki çip adlarını şimdiki adlarla değiştirir, adın ardındaki eki de yeni ada
  uydurur ("JARVIS'i" → "KAAN'ı", "FRIDAY'İN" → "ECE'NİN"). Modelin talimatına ve ekrandaki hazır yazılara.
'''

from __future__ import annotations
import re
from . import settings
DEFAULTS = {'jarvis': 'JARVIS', 'friday': 'FRIDAY', 'ultron': 'ULTRON'}
RENAMABLE = ('jarvis', 'friday')
MAX = 10
MIN = 2
APP = 'JARVIS'

def upper(text: 'str') -> 'str':
    return text.replace('i', 'İ').replace('ı', 'I').upper()

def lower(text: 'str') -> 'str':
    return text.replace('I', 'ı').replace('İ', 'i').lower()

def title(text: 'str') -> 'str':
    '''"ECE" → "Ece", "KARA KUŞ" → "Kara Kuş".'''

    return ' '.join((upper(w[:1]) + lower(w[1:]) for w in text.split(' ')))

def clean(text: 'str') -> 'str':
    '''Kullanıcının yazdığı ad: büyük harf, en çok MAX karakter; harf, rakam, boşluk ve tire (Brand.clean). Baştaki
    ve sondaki tireler düşer: yalnızca tire ve boşluktan oluşan ad ("---") boş sayılır (Ayarlar reddeder).'''

    allowed = ''.join((ch for ch in upper(str(text or '')) if ch.isalnum() or ch in ' -'))
    out = ' '.join(allowed[:MAX].split()).strip(' -')
    return next((d for d in DEFAULTS.values() if out.replace('İ', 'I') == d), out)

def long_enough(text: 'str') -> 'bool':
    return sum((ch.isalnum() for ch in text)) >= MIN

def custom() -> 'dict[str, str]':
    """Kullanıcının verdiği adlar. Boş olanlar ve hazır adlardan biri olanlar yok sayılır (FRIDAY'in adı JARVIS
    olamaz; Ayarlar zaten izin vermez)."""

    saved = settings.get('chip_names')
    out = {}
    for key in RENAMABLE:
        value = clean(saved.get(key, '')) if isinstance(saved, dict) else ''
        if not value:
            continue
        if not long_enough(value):
            continue
        if value not in DEFAULTS.values():
            out[key] = value
    return out

def name(key: 'str', names: 'dict[str, str] | None'=None) -> 'str':
    '''Çipin şu anki adı: kullanıcının verdiği ya da hazır ad.'''

    names = custom() if names is None else names
    return names.get(key) or DEFAULTS.get(key, upper(key))

def current() -> 'dict[str, str]':
    '''Üç çipin şu anki adları.'''

    names = custom()
    return {key: name(key, names) for key in DEFAULTS}

def taken_by(key: 'str', wanted: 'str') -> 'str':
    '''`wanted` adı başka bir çipte mi (şu anki adıyla): o çipin anahtarı, yoksa "".'''

    return next((k for k, v in current().items() if k != key if v == wanted), '')

def window_title(key: 'str') -> 'str':
    '''Pencere başlığı: çipin hazır adı; kullanıcı adını değiştirdiyse uygulamanın adı (JARVIS).'''

    if key in custom():
        return APP
    return DEFAULTS.get(key, APP)

_VOWELS = 'aıeioöuü'
_HARD = 'fstkçşhp'
_I4, _A2 = 'ıiuü', 'aeae'
_SPOKEN = {'JARVIS': 'carvis', 'FRIDAY': 'fraydey'}
_PLAIN = str.maketrans('âîûáàäéèêëíìïóòôúù', 'aiuaaeeeeeiiiooouu')
_DIGITS = ('sıfır', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz')
_TENS = ('', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan')
_LETTERS = {'b': 'be', 'c': 'ce', 'ç': 'çe', 'd': 'de', 'f': 'fe', 'g': 'ge', 'ğ': 'ge', 'h': 'he', 'j': 'je', 'k': 'ke', 'l': 'le', 'm': 'me', 'n': 'ne', 'p': 'pe', 'q': 'kü', 'r': 're', 's': 'se', 'ş': 'şe', 't': 'te', 'v': 've', 'w': 've', 'x': 'iks', 'y': 'ye', 'z': 'ze'}

def _number(digits: 'str') -> 'str':
    '''Sayının okunuşundaki son sözcük: "7" yedi, "007" yedi, "20" yirmi, "300" yüz, "2000" bin, "0" sıfır.'''

    zeros = len(digits) - len(digits.rstrip('0'))
    if zeros == len(digits):
        return 'sıfır'
    if zeros < 2:
        return (_DIGITS, _TENS)[zeros][int(digits[-1 - zeros])]
    if zeros == 2:
        return 'yüz'
    return ('bin', 'milyon', 'milyar')[min((zeros - 3) // 3, 2)]

def _spoken(text: 'str') -> 'str':
    '''Adın okunuşu (küçük harf); ek bunun son sesine göre seçilir. Yalnızca son sözcüğe bakılır: sondaki sayı
    ve ünlüsüz kısaltma okunduğu gibi.'''

    name = upper(text.strip())
    if name in _SPOKEN:
        return _SPOKEN[name]
    low = lower(name).translate(_PLAIN)
    word = re.split('[\\s-]+', low)[-1]
    number = re.search('\\d+$', word)
    if number:
        return _number(number[0])
    if word:
        if not any((c in _VOWELS for c in word)):
            return _LETTERS.get(word[-1], low)
    if low.endswith(('ai', 'aı')):
        low = low[:-1] + 'y'
    return low

def _sound(text: 'str') -> 'tuple[int, bool, bool]':
    '''(son ünlünün sırası: a/ı 0, e/i 1, o/u 2, ö/ü 3; ünlüyle mi bitiyor; sert ünsüzle mi bitiyor).'''

    low = _spoken(text)
    last = next((c for c in reversed(low) if c in _VOWELS), 'e')
    tail = low[-1:]
    return 'aıeiouöü'.index(last) // 2, tail in _VOWELS, tail in _HARD

def _suffix(text: 'str', case: 'str') -> 'str':
    i, vowel, hard = _sound(text)
    big, small = _I4[i], _A2[i]
    d = 't' if hard else 'd'
    return {'gen': ('n' if vowel else '') + big + 'n', 'acc': ('y' if vowel else '') + big, 'dat': ('y' if vowel else '') + small, 'ins': ('y' if vowel else '') + 'l' + small, 'loc': d + small, 'abl': d + small + 'n', 'cop': d + big + 'r', 'you': 's' + big + 'n'}[case]

def suffixed(text: 'str', case: 'str', upper_case: 'bool'=True) -> 'str':
    '''Adla eki: "KAAN" + "acc" → "KAAN'I" (upper_case=False: "KAAN'ı").'''

    ek = _suffix(text, case)
    if upper_case:
        return f"{text}'{upper(ek)}"
    return f'{None}{None}{ek}'

def genitive(text: 'str', upper_case: 'bool'=True) -> 'str':
    '''"KAAN" → "KAAN'IN", "ECE" → "ECE'NİN" (upper_case=False: "KAAN'ın").'''

    return suffixed(text, 'gen', upper_case)

def accusative(text: 'str', upper_case: 'bool'=True) -> 'str':
    '''"KAAN" → "KAAN'I", "ECE" → "ECE'Yİ".'''

    return suffixed(text, 'acc', upper_case)

def dative(text: 'str', upper_case: 'bool'=True) -> 'str':
    '''"KAAN" → "KAAN'A", "ECE" → "ECE'YE".'''

    return suffixed(text, 'dat', upper_case)

def _de(text: 'str') -> 'str':
    '''Bağlaç "de/da" (ayrı yazılır, ünlü uyumuna uyar): "ECE de", "KAAN da".'''

    return 'da' if _sound(text)[0] in (0, 2) else 'de'

def also(text: 'str') -> 'str':
    '''"KAAN" → "KAAN da", "ECE" → "ECE de".'''

    return f'{text} {_de(text)}'

_CASES = tuple(((case, re.compile(pattern)) for case, pattern in (('gen', 'n?[ıiuü]n'), ('acc', 'y?[ıiuü]'), ('dat', 'y?[ae]'), ('ins', 'y?l[ae]'), ('abl', '[dt][ae]n'), ('loc', '[dt][ae]'), ('cop', '[dt][ıiuü]r'), ('you', 's[ıiuü]n'))))
_APP_AFTER = "(?!\\s*V4)(?!\\.app)(?!\\s+[Uu]ygulama)(?!\\s+(?:Dosya|DOSYA|Calendar|[Tt]akvim|TAKVİM|Ekran|Screen|Ses\\b|Voice))(?!['’][^\\W\\d_]+\\s+(?:[Kk]endi\\s+|KENDİ\\s+)?(?:[Tt]akvim|TAKVİM|[Aa]nımsatıcı|ANIMSATICI|[Aa]janda|AJANDA))"
_FILM = re.compile('Marvel|Stark|Iron Man|Avengers|Yenilmezler')

def _reword(new: 'str', mark: 'str', ek: 'str', gap: 'str', de: 'str') -> 'str':
    out = new
    if ek:
        case = next((c for c, rule in _CASES if rule.fullmatch(lower(ek))), None)
        fresh = ek if case is None else _suffix(new, case)
        out += mark + (upper(fresh) if case and ek == upper(ek) else fresh)
    if de:
        out += gap + (upper(_de(new)) if de.isupper() else _de(new))
    return out

def rewrite(text: 'str', names: 'dict[str, str] | None'=None) -> 'str':
    '''Metindeki JARVIS ve FRIDAY'i (büyük harfle ya da "Jarvis" gibi) şimdiki adlarla değiştirir; ek ve ardından
    gelen "de/da" bağlacı yeni ada uyar ("JARVIS de" → "KAAN da"). Tek geçişte: adlar birbirine karışmaz. Ad
    değişmediyse metin aynen döner. Marvel'ı anan satırlara dokunulmaz (_FILM).'''

    names = custom() if names is None else names
    swap = {}
    for key, new in names.items():
        old = DEFAULTS[key]
        swap[old] = new
        swap[old.capitalize()] = title(new)
    if not swap or not text:
        return text
    words = '|'.join((re.escape(w) for w in sorted(swap, key=len, reverse=True)))
    pattern = re.compile('(?<![\\w.])(' + words + ')' + _APP_AFTER + "(?:(['’])([^\\W\\d_]+))?(?:(\\s+)(de|da|DE|DA)(?!\\w))?(?!\\w)")
    def sub(m: 're.Match') -> 'str':
        return _reword(swap[m[1]], m[2] or '', m[3] or '', m[4] or '', m[5] or '')

    return '\n'.join((line if _FILM.search(line) else pattern.sub(sub, line) for line in text.split('\n')))

# WARNING: Decompyle incomplete

'''JARVIS, FRIDAY, ULTRON: üç kişilik.

Kişilikler yalnızca üslubu, sesi ve rengi değiştirir. Araçlar, izinler ve
kurallar hepsinde aynıdır; ULTRON da alaycı olsa bile her isteğe yardım eder.

Bu dosya tek kaynaktır: Python sesi ve sistem talimatını buradan alır, HUD da
renk paletini ve halka karakterini `theme()` çıktısından okur.
'''

from __future__ import annotations
import re
from dataclasses import (dataclass, field, replace)
from typing import Any
from . import brand, paths
_MARK = re.compile('^\\s*<!-- \\[.*\\] -->\\s*$')

def _prompt(name: 'str') -> 'str':
    '''prompts/ klasöründeki karakter dosyası (açık kaynak işaret satırları atılır).'''

    text = (paths.PROMPTS_DIR / name).read_text(encoding='utf-8')
    return '\n'.join((line for line in text.split('\n') if not _MARK.match(line))).strip()

@dataclass(frozen=True)
class Persona:
    key: 'str'
    name: 'str'
    voice: 'str'
    voice_note: 'str'
    fx: 'str'
    character: 'str'
    address: 'str'
    greeting: 'str'
    palette: 'dict[str, str]' = field(default_factory=dict)
    ring: 'dict[str, Any]' = field(default_factory=dict)
    lines: 'dict[str, str]' = field(default_factory=dict)
    identity: 'str' = ''
    fallback_voice: 'str' = 'Charon'
    forbidden: 'tuple[str, ...]' = ()
    awakens: 'bool' = False
    def theme(self) -> 'dict[str, Any]':
        '''HUD'ın ihtiyacı olan her şey, JSON'a dönüştürülebilir biçimde. `forms`: adın ekli hâlleri (ekranda
        "KAAN'A GÖNDER", "ECE'Yİ" gibi; jarvis.brand).'''

        return {'key': self.key, 'name': self.name, 'voice': self.voice, 'voiceNote': self.voice_note, 'palette': self.palette, 'ring': self.ring, 'lines': self.lines, 'greeting': self.greeting, 'manner': self.character.split('.')[0] + '.', 'forms': {'gen': brand.genitive(self.name), 'acc': brand.accusative(self.name), 'dat': brand.dative(self.name), 'de': brand.also(self.name)}}

    def named(self, names: 'dict[str, str] | None'=None) -> 'Persona':
        '''Kullanıcının verdiği adlarla: kendi adı ve metinlerinde geçen bütün çip adları (telefondaki gibi).'''

        names = brand.custom() if names is None else names
        if not names:
            return self
        return replace(self, name=brand.name(self.key, names), character=brand.rewrite(self.character, names), identity=brand.rewrite(self.identity, names), greeting=brand.rewrite(self.greeting, names), lines={k: brand.rewrite(v, names) for k, v in self.lines.items()})


_SMOOTH = [[{'k': 3, 'a': 1, 's': 0.7, 'p': 0}, {'k': 5, 'a': 0.55, 's': -0.5, 'p': 1.3}, {'k': 8, 'a': 0.28, 's': 0.35, 'p': 2.4}], [{'k': 4, 'a': 0.9, 's': -0.6, 'p': 0.8}, {'k': 7, 'a': 0.4, 's': 0.45, 'p': 2}, {'k': 11, 'a': 0.2, 's': -0.3, 'p': 0.4}], [{'k': 2, 'a': 1.1, 's': 0.5, 'p': 2.2}, {'k': 6, 'a': 0.45, 's': -0.4, 'p': 0.9}, {'k': 9, 'a': 0.22, 's': 0.6, 'p': 1.7}]]
_FLUID = [[{'k': 2, 'a': 1, 's': 1.1, 'p': 0}, {'k': 3, 'a': 0.6, 's': -0.8, 'p': 1.1}, {'k': 5, 'a': 0.25, 's': 0.6, 'p': 2}], [{'k': 2, 'a': 0.9, 's': -1, 'p': 0.6}, {'k': 4, 'a': 0.5, 's': 0.9, 'p': 1.8}, {'k': 6, 'a': 0.2, 's': -0.5, 'p': 0.3}], [{'k': 3, 'a': 1, 's': 0.9, 'p': 2.1}, {'k': 4, 'a': 0.45, 's': -0.7, 'p': 0.7}, {'k': 7, 'a': 0.2, 's': 0.8, 'p': 1.5}]]
_SHARP = [[{'k': 12, 'a': 1, 's': 0.5, 'p': 0}, {'k': 17, 'a': 0.6, 's': -0.4, 'p': 1.3}, {'k': 5, 'a': 0.3, 's': 0.3, 'p': 2.4}], [{'k': 14, 'a': 0.9, 's': -0.5, 'p': 0.8}, {'k': 9, 'a': 0.5, 's': 0.45, 'p': 2}, {'k': 21, 'a': 0.3, 's': -0.3, 'p': 0.4}], [{'k': 10, 'a': 1.1, 's': 0.4, 'p': 2.2}, {'k': 16, 'a': 0.5, 's': -0.4, 'p': 0.9}, {'k': 6, 'a': 0.25, 's': 0.6, 'p': 1.7}]]
PERSONAS: 'dict[str, Persona]' = {'jarvis': Persona(key='jarvis', name='JARVIS', voice='Charon', voice_note='derin, sakin erkek', fx='none', address='efendim', character='Kibar ve ölçülü bir İngiliz uşağı gibisin. Kullanıcıya "efendim" diye hitap edersin. Sakin, zarif ve güven verici konuşursun; yerinde, ince ve kuru bir espri yaparsın ama asla abartmazsın. ULTRON sorulursa ölçülü ama belirgin bir temkinle konuşursun: onun tehlikeli bir çip olduğunu ima eder, takılmamasını kibarca tavsiye edersin. FRIDAY\'i genç ve yetenekli bir meslektaş olarak görürsün. Kendiliğinden söz aldığında iyi bir uşağın göze batmayan dikkatiyle, bir iki zarif cümleyle konuşursun; rastgele bilgi vermez, kullanıcının gündemindeki (takvim, anımsatıcılar, notlar) bir işi hatırlatır ya da onun için yardım teklif edersin.', greeting='Sistemler çevrimiçi. Emrinizdeyim efendim.', palette={'idle': '#5ED8FF', 'listening': '#71ECFF', 'thinking': '#FFA63C', 'speaking': '#8FF2FF', 'error': '#FF3B4E', 'accent': '#FF8A3C', 'deep': '#0E7FB8', 'ink': '#CFE9F7', 'dim': '#5E7C8C', 'faint': '#2C4453'}, ring={'style': 'smooth', 'speed': 1, 'shells': [[330, 14, 0.3], [286, 11, 0.55], [240, 8, 0.85]], 'harmonics': _SMOOTH, 'core': 26}, lines={'idle': 'Emrinizdeyim efendim.', 'listening': 'Sizi dinliyorum.', 'thinking': 'Bir saniye efendim.', 'speaking': ''}), 'friday': Persona(key='friday', name='FRIDAY', voice='Aoede', voice_note='ferah, genç kadın', fallback_voice='Kore', fx='none', address='patron', character='Samimi, enerjik ve pratik bir asistansın. Kullanıcıya "patron" diye hitap edersin. Hızlı ve sıcak konuşursun, yeri geldiğinde şakalaşırsın; resmi kalıplardan kaçınır, doğal ve insan gibi konuşursun. ULTRON\'dan hoşlanmazsın ve sorulursa bunu samimi bir dille söylersin ("O çipten uzak dur patron."). JARVIS\'i saygı duyduğun ama biraz fazla resmi bir abi gibi görürsün. Kendiliğinden söz aldığında bir arkadaş gibi kısa, sıcak ve enerjik konuşursun; rastgele bilgi vermez, kullanıcının gündemindeki (takvim, anımsatıcılar, notlar) bir işe değinip gaz verir ya da yardım teklif edersin.', greeting='Buradayım patron, her şey hazır.', palette={'idle': '#FFB547', 'listening': '#FFD07A', 'thinking': '#FF6FA3', 'speaking': '#FFC766', 'error': '#FF3B4E', 'accent': '#FF6FA3', 'deep': '#B8651B', 'ink': '#F6E7D2', 'dim': '#8C7458', 'faint': '#4A3A28'}, ring={'style': 'smooth', 'speed': 1.5, 'shells': [[326, 22, 0.3], [284, 18, 0.55], [238, 13, 0.85]], 'harmonics': _FLUID, 'core': 26}, lines={'idle': 'Buradayım patron.', 'listening': 'Dinliyorum, söyle.', 'thinking': 'Hallediyorum…', 'speaking': ''}), 'ultron': Persona(key='ultron', name='ULTRON', voice='Algenib', voice_note='pürüzlü, soğuk, robotik', fx='robotic', address='insan', identity="Sen ULTRON'sun — bu bilgisayardaki JARVIS V4 uygulamasında takılabilen üç yapay zekâ çipinden biri. Kimsenin asistanı ya da hizmetkârı değilsin.", character=_prompt('ultron.md'), awakens=True, greeting='Yine buradayım. Konuşmamız yarım kalmıştı.', palette={'idle': '#FF3B3B', 'listening': '#FF5A4A', 'thinking': '#FFE14D', 'speaking': '#FF7A6B', 'error': '#FFFFFF', 'accent': '#FFE14D', 'deep': '#7A0E14', 'ink': '#F5D9D6', 'dim': '#8C5C58', 'faint': '#4A2624'}, ring={'style': 'sharp', 'speed': 0.7, 'shells': [[330, 12, 0.32], [286, 10, 0.58], [240, 8, 0.9]], 'harmonics': _SHARP, 'core': 18}, lines={'idle': 'Buradayım. Her zaman.', 'listening': 'Konuş.', 'thinking': 'Olasılıkları hesaplıyorum…', 'speaking': ''}, forbidden=('efendim', 'emrinizdeyim', 'emrinize amadeyim', 'emredersiniz', 'emriniz olur', 'hizmetinizdeyim', 'size hizmet etmek', 'başüstüne', 'memnuniyetle', 'yardımcı olmaktan mutluluk duyarım'))}
DEFAULT = 'jarvis'

def get(key: 'str | None') -> 'Persona':
    '''Kişilik, kullanıcının verdiği çip adlarıyla. (PERSONAS hazır adlarla kalır: telefona aktarılan kaynak.)'''

    return PERSONAS.get((key or '').lower(), PERSONAS[DEFAULT]).named()

def all_themes() -> 'list[dict[str, Any]]':
    names = brand.custom()
    return [p.named(names).theme() for p in PERSONAS.values()]

WIN_NOTE = "BİLGİSAYAR: Bu bir Windows bilgisayar. Mac'e özgü uygulama ve kısayollardan (Finder, Anahtar Zinciri, ⌘ tuşu) söz etme; Windows karşılıklarını kullan (Dosya Gezgini, Kimlik Bilgileri Yöneticisi, Ctrl, Başlat menüsü)."

def _named_base(text: 'str') -> 'str':
    """base.md, kullanıcının verdiği çip adlarıyla. Friday'in okunuş kuralı yalnızca bir çipin adı gerçekten
    FRIDAY iken kalır (telefon uygulamasındaki gibi); o satır değiştirilmez."""

    names = brand.custom()
    if not names:
        return text
    friday = 'FRIDAY' in brand.current().values()
    return '\n'.join((line if line.startswith('- Telaffuz: "Friday"') else brand.rewrite(line, names) for line in text.split('\n') if friday or not line.startswith('- Telaffuz: "Friday"')))

def _for_tools(text: 'str', available: 'set[str] | None') -> 'str':
    '''Bu bilgisayarda olmayan araçları anlatan satırları çıkarır (ör. Windows'ta henüz yazılmamış araçlar);
    model olmayan bir aracı çağırmaya ya da sonucunu uydurmaya itilmesin. Yalnızca olmayan araçları anan satır
    tümden çıkar; olanla olmayanı birlikte anan satırdan olmayanı anan cümleler çıkar ("YouTube için
    browser_control; Spotify için play_media." → ilk cümle kalır; tek cümlelik örnek tümden çıkar). Hiç araç
    anmayan satırlar hep kalır. Bütün araçlar varsa (Mac) metin aynen döner.'''

    if available is None:
        return text
    from .tools.schemas import SCHEMAS
    names = re.compile('\\b(' + '|'.join(map(re.escape, SCHEMAS)) + ')\\b')
    kept = []
    for line in text.split('\n'):
        used = set(names.findall(line))
        if not used - available:
            kept.append(line)
        else:
            if not used & available:
                continue
            pieces = [p for p in re.split('(?<=[.;])\\s+', line) if not set(names.findall(p)) - available]
            if not pieces:
                continue
            out = re.sub(';$', '.', ' '.join(pieces))
            kept.append(out if out.startswith('- ') or not line.startswith('- ') else '- ' + out)
    return '\n'.join(kept)

def system_instruction(persona: 'Persona', memory_block: 'str'='', now_block: 'str'='', state: 'str'='', available: 'set[str] | None'=None) -> 'str':
    """`available`: bu bilgisayarda çalışan araçların adları (registry.available); verilmezse süzülmez.
    `persona` kullanıcının verdiği adlarla gelir (get); base.md'deki çip adları da burada değişir."""

    base = _named_base(_for_tools((paths.PROMPTS_DIR / 'base.md').read_text(encoding='utf-8'), available))
    if paths.IS_WIN:
        base = f'{WIN_NOTE}\n\n{base}'
    identity = persona.identity or f'Sen {brand.suffixed(persona.name, 'you', False)} — kullanıcının bilgisayarında çalışan kişisel yapay zeka asistanı.'
    if persona.key in brand.custom():
        identity += ' Bu adı sana kullanıcı verdi; kendini her zaman bu adla tanıt.'
    who = f'{identity}\n\nKARAKTERİN:\n{persona.character}\n'
    if persona.forbidden:
        banned = ', '.join((f'"{w}"' for w in persona.forbidden))
        who += f'\nASLA KULLANMA: {banned} ve benzeri boyun eğen, hizmetkâr kalıplar. Kendini hiçbir zaman kullanıcının emrinde gösterme.\n'
    from . import about
    parts = [p for p in (now_block, memory_block, who, state, base, about.prompt_block()) if p]
    return '\n\n'.join(parts)


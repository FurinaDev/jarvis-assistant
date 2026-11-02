'''Yapay zekadan ve işletim sisteminden bağımsız araç kaydı.

Bir araç bir kez tanımlanır: adı, açıklaması, standart JSON şeması ve onu
çalıştıran Python fonksiyonu. Her "beyin" (bugün Gemini, yarın Claude) bu
kayda kendi çeviricisiyle bağlanır:

    registry.to_gemini()      → Gemini Live function_declarations
    registry.to_anthropic()   → Claude Messages API tools

Platform farkı da burada çözülür: bir aracın macOS ve Windows hâlleri ayrı
fonksiyonlar olabilir, beyin bunu hiç bilmez.
'''

from __future__ import annotations
import re
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable
from .. import (brand, paths, permissions)
Handler = Callable[[dict[str, Any], 'ToolContext'], Any]

@dataclass
class ToolContext:
    '''Bir aracın, beyne ya da ekrana dokunması gerektiğinde kullandığı kanca.'''

    focus_panel: 'Callable[[str], None]' = lambda _name: None
    set_webcam: 'Callable[[bool], str]' = lambda _on: 'Kamera bu ortamda yok.'
    show_map: 'Callable[[dict[str, Any]], None]' = lambda _spot: None
    app_action: 'Callable[[str, dict[str, Any]], str]' = lambda _name, _args: 'Bu ortamda yapılamıyor.'
    show_files: 'Callable[[list[str], bool], None]' = lambda _paths, _made: None
    images: 'list[bytes]' = field(default_factory=list)

@dataclass
class Tool:
    name: 'str'
    description: 'str'
    parameters: 'dict[str, Any]'
    mac: 'Handler | None' = None
    win: 'Handler | None' = None
    panel: 'str | None' = None
    success_sfx: 'bool' = False
    quiet: 'bool' = False
    free_text: 'bool' = False
    def handler(self) -> 'Handler | None':
        if paths.IS_WIN:
            return self.win
        return self.mac


@dataclass
class Registry:
    tools: 'dict[str, Tool]' = field(default_factory=dict)
    def add(self, tool: 'Tool') -> 'None':
        self.tools[tool.name] = tool

    def available(self) -> 'list[Tool]':
        '''Bu işletim sisteminde gerçekten çalışabilen araçlar.'''

        return [t for t in self.tools.values() if t.handler() is not None]

    def to_gemini(self) -> 'list[dict[str, Any]]':
        names = brand.custom()
        return [{'name': t.name, 'description': brand.rewrite(t.description, names), 'parameters': _gemini_schema(t.parameters)} for t in self.available()]

    def to_anthropic(self) -> 'list[dict[str, Any]]':
        return [{'name': t.name, 'description': t.description, 'input_schema': t.parameters} for t in self.available()]

    def call(self, name: 'str', args: 'dict[str, Any]', ctx: 'ToolContext') -> 'tuple[str, bool]':
        '''Aracı çalıştırır → (sonuç metni, başarılı mı). Asla istisna fırlatmaz.'''

        tool = self.tools.get(name)
        if tool is None:
            return f'Bilinmeyen araç: {name}', False
        fn = tool.handler()
        if fn is None:
            return f'{name} bu işletim sisteminde henüz desteklenmiyor.', False
        try:
            if tool.panel:
                ctx.focus_panel(tool.panel)
            result = fn(dict(args or {}), ctx)
        except Exception as exc:
            traceback.print_exc()
            return f'Hata: {exc}', False
        text = str(result if result is not None else 'Tamam.')
        if tool.free_text:
            return text, not text.startswith('Hata:')
        text, needs_permission = permissions.handle_tool_result(text)
        return text, not needs_permission and not looks_like_error(text)


def _gemini_schema(node: 'Any') -> 'Any':
    '''JSON Schema → Gemini Schema: tür adları büyük harf (object → OBJECT).'''

    if isinstance(node, dict):
        return {k: v.upper() if k == 'type' and isinstance(v, str) else _gemini_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_gemini_schema(x) for x in node]
    return node

_ERROR_MARKERS = ('error', 'alinamadi', 'alınamadı', 'bulunamadi', 'bulunamadı', 'eklenemedi', 'silinemedi', 'acilamadi', 'açılamadı', 'kapatılamadı', 'tamamlanamadi', 'tamamlanamadı', 'gecersiz', 'geçersiz', 'izin gerekiyor', 'izin gerekli', 'desteklenmiyor')
_HATA = re.compile("hata(?!s[ıi]z)(?!y(?:['’]|\\b))")
_SUCCESS_HEAD = re.compile('^(animsatici eklendi|anımsatıcı eklendi|anımsatıcı silindi|anımsatıcı zaten var|anımsatıcı az önce hatırlatıldı|tamamlandı olarak işaretlendi|\\d+ anımsatıcı (silindi|tamamlandı)|bu ada uyan|takvime eklendi|takvimden silindi|\\d+ etkinlik takvimden silindi|tekrarlayan etkinlik o günden|siradaki (etkinlik|animsatici))')
_QUESTION = 'hiçbirine dokunmadım'

def looks_like_error(text: 'str') -> 'bool':
    low = (text or '').strip().lower()
    if _QUESTION in low:
        return False
    if _SUCCESS_HEAD.match(low):
        low = low.split(':', 1)[0]
    return bool(low) and (any((marker in low for marker in _ERROR_MARKERS)) or bool(_HATA.search(low)))


'''Konuşma dili: Ayarlar › Genel › Dil.

"Otomatik"te asistan Türkçe ağırlıklıdır, kullanıcı başka dilde konuşursa o
dile geçer. Bazen Türkçe konuşma başka bir dil sanılıyordu; bir dil seçilince:
- sesin yazıya dökümüne o dil ipucu olarak verilir (language_codes),
- asistanın sesi o dile ayarlanır (speech language_code),
- en önemlisi, talimatın başına "hep bu dilde anla, hep bu dilde cevap ver"
  kuralı eklenir. (Gemini 3.8 Live'da ilk ikisi yalnızca ipucu; Türkçe
  konuşurken "İngilizce" seçili olsa bile Türkçe anlayıp Türkçe cevap
  veriyordu. Dili gerçekten sabitleyen talimat.)
Arayüz Türkçe kalır; değişen yalnızca konuşmanın dili.
'''

from __future__ import annotations
from typing import Any
from . import settings
LANGUAGES: 'dict[str, tuple[str, str | None, str | None, str, str]]' = {'auto': ('OTOMATİK', None, None, '', ''), 'tr': ('TÜRKÇE', 'tr-TR', 'tr', 'Türkçe', 'Türkçeye'), 'en': ('İNGİLİZCE', 'en-US', 'en', 'İngilizce', 'İngilizceye'), 'fr': ('FRANSIZCA', 'fr-FR', 'fr', 'Fransızca', 'Fransızcaya'), 'ar': ('ARAPÇA', 'ar-SA', 'ar', 'Arapça', 'Arapçaya'), 'az': ('AZERİCE', 'az-AZ', 'az', 'Azerice', 'Azericeye')}

def current() -> 'str':
    key = str(settings.get('language') or 'auto')
    if key in LANGUAGES:
        return key
    return 'auto'

def fixed() -> 'bool':
    '''Türkçe dışında bir dil seçili mi (sahne sözleri çevrilerek söylenir).'''

    return current() not in ('auto', 'tr')

def word() -> 'str':
    return LANGUAGES[current()][3]

def transcription() -> 'dict[str, Any]':
    '''Sesin yazıya dökümüne dil ipucu. Otomatik'te de Türkçe (ve İngilizce) verilir: ipucu yokken döküm her cümlede
    dili tahmin ediyor, Türkçe sözler sohbette İngilizce ya da bozuk görünüyordu ("WhatsApp'ı aç" → "what's up").'''

    code = LANGUAGES[current()][1]
    return [code] if code else ['tr-TR', 'en-US']

def speech_code() -> 'str | None':
    return LANGUAGES[current()][2]

def instruction() -> 'str':
    """Sistem talimatının başına: seçilen dili sabitleyen kural (Otomatik'te boş)."""

    key = current()
    if key == 'auto':
        return ''
    name, dative = LANGUAGES[key][3], LANGUAGES[key][4]
    return f'[KONUŞMA DİLİ: {name.upper()}] Bu kural aşağıdaki bütün dil kurallarından önce gelir. Kullanıcı {name} konuşuyor: söylediklerini her zaman {name} olarak anla (başka bir dile benzeyen sesleri de {name} sözcükler olarak yorumla) ve her zaman yalnızca {name} yanıt ver. Aşağıdaki talimatlar Türkçe yazılmış olsa da konuşman {name} olsun; karakterini, hitaplarını ve esprilerini {dative} uyarla.'

def choices() -> 'list[dict[str, str]]':
    return [{'key': k, 'name': v[0]} for k, v in LANGUAGES.items()]


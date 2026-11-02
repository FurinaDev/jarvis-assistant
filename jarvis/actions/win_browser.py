"""Tarayıcı kontrolü (Windows): Mac'teki browser.py ile aynı eylemler ve cevaplar; `open` yerine varsayılan
tarayıcı (os.startfile → ShellExecute). YouTube'da ilk videoyu bulan işlev platformdan bağımsız, Mac dosyasından.

Güvenlik: modelden gelen adres yalnızca http(s) ise açılır; `file:`, `ms-settings:` ya da bir .exe yolu
ShellExecute'a hiç verilmez.
"""

from __future__ import annotations
import os
import urllib.parse

def _open(url: 'str') -> 'str | None':
    '''Adresi varsayılan tarayıcıda açar; olmazsa hata metni döner.'''

    if not url.startswith(('http://', 'https://')):
        return 'Yalnızca web adresleri açılabilir.'
    try:
        os.startfile(url)
        return
    except OSError as exc:
        return f'Tarayıcı açılamadı: {exc}'

def _first_video(query: 'str') -> 'str | None':
    from .browser import _find_first_youtube_video
    return _find_first_youtube_video(query)

def browser_control(action: 'str', url: 'str | None'=None, query: 'str | None'=None) -> 'str':
    if action == 'open_url':
        if not url:
            return 'URL belirtilmedi.'
        if '://' in url and not url.startswith(('http://', 'https://')):
            return 'Yalnızca web adresleri açılabilir (dosya ya da uygulama değil).'
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return _open(url) or f'Açıldı: {url}'
    if action == 'search':
        if not query:
            return 'Arama sorgusu belirtilmedi.'
        return _open(f'https://www.google.com/search?q={urllib.parse.quote(query)}') or f"'{query}' için arama açıldı."
    if action in ('play_youtube', 'youtube_play', 'play_music'):
        if not query:
            return 'YouTube için arama sorgusu belirtilmedi.'
        results = f'https://www.youtube.com/results?search_query={urllib.parse.quote(query)}'
        try:
            video_id = _first_video(query)
        except Exception as exc:
            return _open(results) or f'YouTube ilk sonucu alınamadı ({exc}). Arama sonuçları açıldı: {query}'
        if not video_id:
            return _open(results) or f"YouTube'da doğrudan video bulunamadı. Arama sonuçları açıldı: {query}"
        return _open(f'https://www.youtube.com/watch?v={video_id}&autoplay=1') or f"YouTube'da oynatılıyor: {query}"
    return f'Bilinmeyen eylem: {action}'


"""Konum, adres arama ve yol tarifi.

- Bulunduğun yer: Ayarlar › Genel › KONUM'a bir yer yazılmışsa o (kaydedilirken
  bir kez Nominatim'de aranır, kısa Türkçe adı ve koordinatı saklanır: `choose`).
  Boşsa hava durumunun zaten kullandığı wttr.in yanıtındaki en yakın bölgenin
  koordinatları (IP'ye göre); izin penceresi çıkarmaz, şehir düzeyinde yaklaşıktır.
- Adres arama: OpenStreetMap Nominatim (ücretsiz, anahtar gerektirmez). Kullanım
  kuralı gereği yalnızca kullanıcı sorduğunda, tek istek olarak çağrılır.
- Yol tarifi: macOS'ta Apple Haritalar, Windows'ta Google Haritalar açılır.
"""

from __future__ import annotations
import math
import urllib.parse
import webbrowser
from typing import Any
import requests
from . import (VERSION, paths, settings)
from .log import log
NOMINATIM = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = f'JARVIS-V4/{VERSION} (+https://unlualp.com)'
MODES = {'car': ('d', 'driving'), 'walk': ('w', 'walking'), 'transit': ('r', 'transit')}

def geocode(query: 'str', details: 'bool'=False) -> 'dict[str, Any] | None':
    """details: adresin parçaları da gelsin (address, addresstype; KONUM'un kısa adı için)."""

    query = (query or '').strip()
    if not query:
        return
    params = {'q': query, 'format': 'jsonv2', 'limit': 1, 'accept-language': 'tr'}
    if details:
        params['addressdetails'] = 1
    r = requests.get(NOMINATIM, params=params, headers={'User-Agent': USER_AGENT}, timeout=10)
    r.raise_for_status()
    found = r.json()
    if not found:
        return
    hit = found[0]
    bbox = [float(x) for x in hit.get('boundingbox', [])] if hit.get('boundingbox') else None
    spot = {'lat': float(hit['lat']), 'lon': float(hit['lon']), 'label': hit.get('display_name', query), 'name': hit.get('name') or query, 'bbox': bbox, 'kind': hit.get('type', '')}
    if details:
        spot.update(address=hit.get('address') or {}, addresstype=hit.get('addresstype', ''))
    return spot

def short(label: 'str', parts: 'int'=3) -> 'str':
    """'Galata Kulesi, Büyük Hendek Cd., Kuledibi, …, Türkiye' → ilk birkaç parça (sesli okunacak)."""

    return ', '.join((p.strip() for p in (label or '').split(',')[:parts] if p.strip()))

def zoom_for(kind: 'str') -> 'int':
    if kind in ('city', 'administrative', 'state', 'province', 'country', 'town'):
        return 11
    if kind in ('suburb', 'neighbourhood', 'quarter', 'village', 'district'):
        return 14
    return 16

_WIDE = {'city', 'town', 'state', 'county', 'region', 'country', 'province', 'municipality', 'city_district'}

def short_tr(spot: 'dict[str, Any]') -> 'str':
    '''Yazılan yerin kısa Türkçe adı: "Moda, Kadıköy, İstanbul", "Kadıköy, İstanbul", "Berlin, Almanya".'''

    a = spot.get('address') or {}
    city = a.get('city') or a.get('province') or a.get('state') or ''
    district = '' if spot.get('addresstype') in _WIDE else a.get('town') or a.get('city_district') or a.get('county') or a.get('municipality') or ''
    parts = [spot.get('name') or '', district, city]
    if a.get('country_code', 'tr') != 'tr':
        parts = [spot.get('name') or '', city, a.get('country') or '']
    out = []
    for part in parts:
        if not part:
            continue
        if part not in out:
            out.append(part)
    return ', '.join(out) or short(spot.get('label', ''), 2)

def _panel_zoom(bbox: 'list[float] | None') -> 'int':
    '''Küçük harita panelinde yerin sınırı sığsın: semt 13–14, ilçe 12, şehir ve üstü 11.'''

    if not bbox or len(bbox) != 4:
        return 13
    span = max(bbox[1] - bbox[0], bbox[3] - bbox[2], 0.001)
    return max(11, min(14, int(math.log2(420 / span))))

def coords(spot: 'dict[str, Any]') -> 'str':
    '''wttr.in sorgusu: "40.9876,29.0300".'''

    return f'{spot['lat']:.4f},{spot['lon']:.4f}'

def chosen() -> 'dict[str, Any] | None':
    """KONUM'a yazılıp bulunmuş yer ({label, lat, lon, zoom, country}); yazılmamışsa None (IP'den otomatik)."""

    text = str(settings.get('location') or '').strip()
    spot = settings.get('location_spot')
    if text and isinstance(spot, dict) and spot.get('for') == text and spot.get('lat') is not None:
        return spot

def choose(text: 'str') -> 'str':
    '''KONUM kaydedilince: yazılan yer bir kez aranır, kısa Türkçe adı ve koordinatıyla saklanır. Boş: otomatiğe
    döner. Bulunamazsa ya da servise ulaşılamazsa eski konum değişmez; nedeni döner (boşsa kaydedildi).'''

    text = ' '.join((text or '').split())[:120]
    if not text:
        settings.save({'location': '', 'location_spot': {}})
        log('konum: otomatik (internet bağlantısından)')
        return ''
    if chosen():
        if text == str(settings.get('location') or '').strip():
            return ''
    try:
        hit = geocode(text, details=True)
    except (requests.RequestException, ValueError, KeyError):
        return 'Konum servisine ulaşılamadı; konum değişmedi. İnternet bağlantını kontrol edip yeniden dene.'
    if not hit:
        return f'“{text}” haritada bulunamadı; konum değişmedi. İlçe ya da semti şehirle yaz (ör. Kadıköy, İstanbul).'
    spot = {'for': text, 'label': short_tr(hit), 'lat': round(hit['lat'], 5), 'lon': round(hit['lon'], 5), 'zoom': _panel_zoom(hit.get('bbox')), 'country': (hit.get('address') or {}).get('country', '')}
    settings.save({'location': text, 'location_spot': spot})
    log('konum:', spot['label'], '(yazılan)')
    return ''

def status() -> 'str':
    '''KONUM kutusunun altındaki satır: şu an hangi yer kullanılıyor, nereden.'''

    spot = chosen()
    text = str(settings.get('location') or '').strip()
    if spot or text:
        if spot:
            return f'Şu an: {spot['label']} · senin yazdığın'
        return f'{None}{text} · senin yazdığın'
    from . import panels
    wx = panels.weather()
    if wx.get('lat') is None:
        return 'Konum şu an bulunamadı: internet bağlantısı yok gibi. Bağlanınca kendiliğinden bulunur.'
    return f'Şu an: {wx.get('region') or wx.get('place')} · internet bağlantından, yaklaşık'

def here() -> 'dict[str, Any] | None':
    '''Bulunduğun yer (hava paneliyle aynı kaynak, önbellekten). Yakınlık panelinkinden bir fazla.'''

    from . import panels
    wx = panels.weather()
    if wx.get('lat') is None:
        return
    return {'lat': wx['lat'], 'lon': wx['lon'], 'name': wx.get('place', ''), 'label': wx.get('place', ''), 'zoom': int(wx.get('zoom') or 11) + 1}

def show_on_map(query: 'str') -> 'tuple[str, dict[str, Any] | None]':
    '''Bir yeri bulur → (sesli cevap için metin, ekrana gidecek harita verisi).'''

    wanted = (query or '').strip().lower()
    if wanted in ('', 'burası', 'neredeyim', 'konumum', 'bulunduğum yer', 'here'):
        spot = here()
        if not spot:
            return ('Konumunu şu anda belirleyemedim.', None)
        return f'Haritada bulunduğun yeri gösteriyorum: {spot['name']}.', dict(spot, here=True)
    from . import story
    spot = story.map_station(query)
    if spot:
        return f'Haritada gösteriyorum: {spot['label']}.', spot
    try:
        spot = geocode(query)
    except requests.RequestException:
        return ('Harita servisine ulaşılamadı.', None)
    if not spot:
        return f"'{query}' haritada bulunamadı.", None
    spot = dict(spot, zoom=zoom_for(spot['kind']))
    spot = story.map_spot(spot)
    return f'Haritada gösteriyorum: {short(spot['label'])}.', spot

def directions(destination: 'str', origin: 'str'='', mode: 'str'='car') -> 'tuple[str, dict[str, Any] | None]':
    destination = (destination or '').strip()
    if not destination:
        return ('Nereye gitmek istediğini söylemedin.', None)
    apple_flag, google_mode = MODES.get(mode, MODES['car'])
    if paths.IS_MAC:
        params = {'daddr': destination, 'dirflg': apple_flag}
        if origin:
            params['saddr'] = origin
        url = 'https://maps.apple.com/?' + urllib.parse.urlencode(params)
        app = 'Apple Haritalar'
    else:
        params = {'api': '1', 'destination': destination, 'travelmode': google_mode}
        if origin:
            params['origin'] = origin
        url = 'https://www.google.com/maps/dir/?' + urllib.parse.urlencode(params)
        app = 'Google Haritalar'
    webbrowser.open(url)
    spot = None
    try:
        spot = geocode(destination)
    except requests.RequestException:
        pass
    how = {'car': 'arabayla', 'walk': 'yürüyerek', 'transit': 'toplu taşımayla'}.get(mode, 'arabayla')
    if spot:
        return f"{destination} için {how} yol tarifini {app}'da açtım.", dict(spot, zoom=zoom_for(spot['kind']))
    return None, None

# WARNING: Decompyle incomplete

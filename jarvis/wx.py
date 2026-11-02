'''Hava durumu verisi (wttr.in, anahtar gerekmez) — panel, büyük görünüm ve sesli araç için.

Tek istekle anlık durum, 3 günlük tahmin, 3 saatlik ölçümler, gün doğumu/batımı
ve ay evresi gelir. `panel()` ekranın, `summary()` asistanın kullanacağı hâle
çevirir.
'''

from __future__ import annotations
import datetime as dt
import urllib.parse
from typing import Any
import requests
TR_DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
WIND_SHORT = {'N': 'K', 'NNE': 'KKD', 'NE': 'KD', 'ENE': 'DKD', 'E': 'D', 'ESE': 'DGD', 'SE': 'GD', 'SSE': 'GGD', 'S': 'G', 'SSW': 'GGB', 'SW': 'GB', 'WSW': 'BGB', 'W': 'B', 'WNW': 'BKB', 'NW': 'KB', 'NNW': 'KKB'}
WIND_LONG = ['kuzeyden', 'kuzeydoğudan', 'doğudan', 'güneydoğudan', 'güneyden', 'güneybatıdan', 'batıdan', 'kuzeybatıdan']
MOON = {'New Moon': 'Yeni Ay', 'Waxing Crescent': 'Büyüyen hilal', 'First Quarter': 'İlk dördün', 'Waxing Gibbous': 'Büyüyen şişkin ay', 'Full Moon': 'Dolunay', 'Waning Gibbous': 'Küçülen şişkin ay', 'Last Quarter': 'Son dördün', 'Waning Crescent': 'Küçülen hilal'}
TR_DESC = {113: 'Güneşli', 116: 'Parçalı bulutlu', 119: 'Bulutlu', 122: 'Kapalı', 143: 'Puslu', 176: 'Yer yer yağmur', 179: 'Yer yer kar', 182: 'Yer yer karla karışık yağmur', 185: 'Yer yer donan çisenti', 200: 'Yer yer gök gürültüsü', 227: 'Tipi', 230: 'Kar fırtınası', 248: 'Sisli', 260: 'Dondurucu sis', 263: 'Yer yer hafif çisenti', 266: 'Hafif çisenti', 281: 'Donan çisenti', 284: 'Yoğun donan çisenti', 293: 'Yer yer hafif yağmur', 296: 'Hafif yağmur', 299: 'Ara ara orta yağmur', 302: 'Orta şiddette yağmur', 305: 'Ara ara şiddetli yağmur', 308: 'Şiddetli yağmur', 311: 'Hafif donan yağmur', 314: 'Donan yağmur', 317: 'Hafif karla karışık yağmur', 320: 'Karla karışık yağmur', 323: 'Yer yer hafif kar', 326: 'Hafif kar', 329: 'Yer yer orta kar', 332: 'Orta şiddette kar', 335: 'Yer yer yoğun kar', 338: 'Yoğun kar', 350: 'Buz topakları', 353: 'Hafif sağanak', 356: 'Sağanak yağmur', 359: 'Çok şiddetli sağanak', 362: 'Hafif karla karışık sağanak', 365: 'Karla karışık sağanak', 368: 'Hafif kar sağanağı', 371: 'Kar sağanağı', 374: 'Hafif buz topağı sağanağı', 377: 'Buz topağı sağanağı', 386: 'Gök gürültülü hafif yağmur', 389: 'Gök gürültülü sağanak', 392: 'Gök gürültülü hafif kar', 395: 'Gök gürültülü yoğun kar'}

def fetch(location: 'str'='') -> 'dict[str, Any]':
    r = requests.get(f'https://wttr.in/{urllib.parse.quote(location)}', params={'format': 'j1', 'lang': 'tr'}, timeout=10, headers={'User-Agent': 'JARVIS V4'})
    r.raise_for_status()
    return r.json()

def glyph(code: 'int') -> 'str':
    if code == 113:
        return '☀︎'
    if code == 116:
        return '◐'
    if code in (119, 122):
        return '☁︎'
    if code in (143, 248, 260):
        return '≋'
    if code in (200, 386, 389, 392, 395):
        return 'ϟ'
    if code in (179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377):
        return '❄︎'
    return '☂︎'

def _i(value: 'Any', default: 'int'=0) -> 'int':
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def _desc(node: 'dict', night: 'bool'=False) -> 'str':
    code = _i(node.get('weatherCode'), -1)
    if code == 113 and night:
        return 'Açık'
    if code in TR_DESC:
        return TR_DESC[code]
    return ((node.get('lang_tr') or node.get('weatherDesc') or [{}])[0].get('value', '') or '').strip()

def _clock24(text: 'str') -> 'str':
    '''"06:55 PM" → "18:55".'''

    try:
        return dt.datetime.strptime(text.strip(), '%I:%M %p').strftime('%H:%M')
    except (ValueError, AttributeError):
        return ''

def _day_name(day: 'dt.date', today: 'dt.date') -> 'str':
    if day == today:
        return 'Bugün'
    if day == today + dt.timedelta(days=1):
        return 'Yarın'
    return TR_DAYS[day.weekday()]

def _hours(raw: 'dict', now: 'dt.datetime', count: 'int'=8) -> 'list[dict[str, Any]]':
    '''Şu andan başlayarak 3 saatlik ölçümler (yaklaşık 24 saat).'''

    out = []
    for day in raw.get('weather') or []:
        try:
            date = dt.date.fromisoformat(day.get('date', ''))
        except ValueError:
            continue
        for h in day.get('hourly') or []:
            at = dt.datetime.combine(date, dt.time(_i(h.get('time')) // 100))
            if at < now - dt.timedelta(hours=1, minutes=30):
                pass
        continue
        out.append({'t': at.strftime('%H:%M'), 'c': _i(h.get('tempC')), 'r': _i(h.get('chanceofrain')), 'g': glyph(_i(h.get('weatherCode'), 116)), 'd': _desc(h, not 6 <= at.hour < 19), 'w': _i(h.get('windspeedKmph'))})
        continue
        continue
    return out[:count]

def _days(raw: 'dict', today: 'dt.date') -> 'list[dict[str, Any]]':
    out = []
    for day in raw.get('weather') or []:
        try:
            date = dt.date.fromisoformat(day.get('date', ''))
        except ValueError:
            continue
        hourly = day.get('hourly') or [{}]
        noon = hourly[min(4, len(hourly) - 1)]
        astro = (day.get('astronomy') or [{}])[0]
        out.append({'n': _day_name(date, today), 'date': f'{date.day} {TR_MONTHS[date.month]}', 'hi': _i(day.get('maxtempC')), 'lo': _i(day.get('mintempC')), 'g': glyph(_i(noon.get('weatherCode'), 116)), 'd': _desc(noon), 'r': max((_i(h.get('chanceofrain')) for h in hourly), default=0), 'sun': round(float(day.get('sunHour') or 0), 1), 'sunrise': _clock24(astro.get('sunrise', '')), 'sunset': _clock24(astro.get('sunset', ''))})
        continue
    return out

def panel(raw: 'dict', location: 'str'='') -> 'dict[str, Any]':
    '''Ekrandaki hava paneli + büyük görünümün bütün verisi.'''

    now = dt.datetime.now()
    cur = (raw.get('current_condition') or [{}])[0]
    today_raw = (raw.get('weather') or [{}])[0]
    area = (raw.get('nearest_area') or [{}])[0]
    place = location or (area.get('areaName') or [{}])[0].get('value', '')
    country = (area.get('country') or [{}])[0].get('value', '')
    region = (area.get('region') or [{}])[0].get('value', '')
    try:
        lat, lon = float(area.get('latitude')), float(area.get('longitude'))
    except (TypeError, ValueError):
        lat = lon = None
    temp = _i(cur.get('temp_C'))
    low, high = _i(today_raw.get('mintempC'), temp), _i(today_raw.get('maxtempC'), temp)
    span = high - low or 1
    astro = (today_raw.get('astronomy') or [{}])[0]
    desc = _desc(cur, not 7 <= now.hour < 19)
    return {'key': 'weather', 'label': 'HAVA', 'kind': 'weather', 'value': f'{temp}°', 'place': place, 'detail': desc.lower(), 'feels': _i(cur.get('FeelsLikeC'), temp), 'high': high, 'low': low, 'ratio': round(max(0.0, min(1.0, (temp - low) / span)), 3), 'glyph': glyph(_i(cur.get('weatherCode'), 116)), 'day': 7 <= now.hour < 19, 'humidity': cur.get('humidity', ''), 'wind': cur.get('windspeedKmph', ''), 'lat': lat, 'lon': lon, 'country': country, 'region': region, 'more': {'temp': temp, 'desc': desc, 'pressure': _i(cur.get('pressure')), 'visibility': _i(cur.get('visibility')), 'uv': _i(cur.get('uvIndex')), 'cloud': _i(cur.get('cloudcover')), 'precip': float(cur.get('precipMM') or 0), 'wind_dir': WIND_SHORT.get(cur.get('winddir16Point', ''), ''), 'wind_deg': _i(cur.get('winddirDegree')), 'sunrise': _clock24(astro.get('sunrise', '')), 'sunset': _clock24(astro.get('sunset', '')), 'moon': MOON.get(astro.get('moon_phase', ''), astro.get('moon_phase', '')), 'moon_light': _i(astro.get('moon_illumination')), 'hourly': _hours(raw, now), 'days': _days(raw, now.date()), 'updated': now.strftime('%H:%M')}}

def summary(raw: 'dict', target: 'str'='') -> 'str':
    '''Asistan için: şimdi, bugünün kalanı ve önümüzdeki iki gün.'''

    data = panel(raw, target)
    more = data['more']
    place = data['place'] or 'Bulunduğun yer'
    wind_from = WIND_LONG[round(more['wind_deg'] / 45) % 8] if data.get('wind') else ''
    parts = [f'{place}: şu an {more['temp']} derece, {more['desc'].lower()}']
    if data['feels'] != more['temp']:
        parts.append(f'hissedilen {data['feels']}')
    parts.append(f'nem yüzde {data['humidity']}, rüzgâr saatte {data['wind']} km {wind_from}'.rstrip())
    text = ', '.join(parts) + '.'
    rain_soon = max((h['r'] for h in more['hourly'][:4]), default=0)
    text += f' Önümüzdeki saatlerde yağmur olasılığı en fazla yüzde {rain_soon}.'
    for day in more['days']:
        text += f' {day['n']}: {day['lo']}–{day['hi']} derece, {day['d'].lower()}, yağmur olasılığı yüzde {day['r']}.'
    if more['sunset']:
        text += f' Gün batımı {more['sunset']}.'
    return text


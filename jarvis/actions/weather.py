"""Hava durumu özeti (wttr.in): şimdi, bugünün kalanı ve önümüzdeki iki gün.

Konum verilmezse Ayarlar › KONUM'daki yer (bulunduysa koordinatıyla), o da boşsa IP adresinden bulunan konum
kullanılır. Veriyi okuma işi `jarvis.wx`'te; ekrandaki panel de aynı veriyi kullanır.
"""

from __future__ import annotations
from .. import (geo, settings, wx)

def get_weather_summary(location: 'str | None'=None) -> 'str':
    asked = (location or '').strip()
    spot = None if asked else geo.chosen()
    target = asked or str(settings.get('location') or '').strip()
    try:
        if spot:
            return wx.summary(wx.fetch(geo.coords(spot)), spot['label'])
        return wx.summary(wx.fetch(target), target)
    except Exception:
        return 'Hava durumu bilgisi şu anda alınamadı.'


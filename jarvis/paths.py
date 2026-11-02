"""Nerede ne durur.

İki ayrı yer var ve karıştırılmamalı:
- PACKAGE_DIR: uygulamanın kendi dosyaları (kod, HUD, fontlar). Paketlenmiş bir
  uygulamada salt okunur olabilir, bu yüzden buraya hiçbir şey yazılmaz.
- DATA_DIR: kullanıcıya ait her şey (ayarlar, hafıza, rehber, derlenen
  yardımcılar). Klasör taşınsa da, uygulama güncellense de kaybolmaz.

Paketlenmiş uygulamada (JARVIS.app, scripts/build_mac.py) PACKAGE_DIR paketin
içindedir; yardımcılar (takvim, ekran, ses) hazır derlenmiş olarak Contents/Helpers'ta durur.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
IS_MAC = sys.platform == 'darwin'
IS_WIN = sys.platform == 'win32'
FROZEN = bool(getattr(sys, 'frozen', False))
PACKAGE_DIR = Path(__file__).resolve().parent
HUD_DIR = PACKAGE_DIR / 'ui' / 'hud'
HELPERS_SRC = PACKAGE_DIR / 'helpers'
PROMPTS_DIR = PACKAGE_DIR / 'prompts'
BUNDLED_HELPERS = Path(sys.executable).resolve().parent.parent / 'Helpers' if FROZEN else None
CALENDAR_HELPER = 'JARVIS Takvim' if FROZEN else 'JARVIS Calendar Helper'
SCREEN_HELPER = 'JARVIS Ekran' if FROZEN else 'JARVIS Screen Helper'
VOICE_HELPER = 'JARVIS Ses' if FROZEN else 'JARVIS Voice Helper'
APP_NAME = 'JARVIS V4'
WIN_APP_ID = 'AlpUnlu.JARVIS.V4'

def _data_dir() -> 'Path':
    override = os.environ.get('JARVIS_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if IS_MAC:
        return Path.home() / 'Library' / 'Application Support' / APP_NAME
    if IS_WIN:
        return Path(os.environ.get('APPDATA', Path.home())) / APP_NAME
    return Path.home() / '.local' / 'share' / APP_NAME

DATA_DIR = _data_dir()
SETTINGS_FILE = DATA_DIR / 'settings.json'
MEMORY_FILE = DATA_DIR / 'memory.json'
PHONEBOOK_FILE = DATA_DIR / 'phone_book.json'
HELPERS_BUILD = DATA_DIR / 'helpers'
LOG_FILE = DATA_DIR / 'jarvis.log'

def ensure_dirs() -> 'None':
    for folder in DATA_DIR, HELPERS_BUILD:
        folder.mkdir(parents=True, exist_ok=True)


"""Kullanıcı ayarları ve API anahtarları.

Ayarlar DATA_DIR/settings.json'da durur. API anahtarları ise dosyaya değil,
işletim sisteminin anahtar deposuna yazılır (macOS Anahtar Zinciri, Windows
Kimlik Bilgisi Yöneticisi). Böylece proje klasörü zip'lenip paylaşılsa bile
anahtar içinde gitmez.
"""

from __future__ import annotations
import json
import os
import threading
import time
from typing import Any
from . import paths
KEYRING_SERVICE = paths.APP_NAME
DEFAULTS: 'dict[str, Any]' = {'persona': 'jarvis', 'chip_names': {}, 'location': '', 'location_spot': {}, 'mic_enabled': True, 'sfx_enabled': True, 'sfx_volume': 20, 'onboarded': False, 'onboard_step': '', 'files_asked': False, 'first_used': 0, 'follow_last': 0, 'follow_count': 0, 'follow_off': False, 'ultron_awakened': False, 'ambient_enabled': True, 'think_enabled': True, 'voice_volume': 100, 'panels_off': ['notes'], 'language': 'auto', 'render_quality': 'high', 'mic_device': '', 'aec_enabled': True, 'mic_off_reason': '', 'panel_layout': None, 'proactive_enabled': True, 'proactive_minutes': 20, 'water_enabled': True, 'break_enabled': True, 'event_alerts': True, 'ultron_silence_step': 0, 'proactive_history': {}, 'proactive_topics': [], 'ultron_openings': [], 'disabled_personas': [], 'chains_used': False, 'chains_broken_at': '', 'chains_restore_locked_until': 0, 'ultron_seconds': 0, 'story_enabled': True, 'story': {}, 'phone_autostart': False, 'phone_shell': False, 'phone_relay': True}
_lock = threading.RLock()
_RETRIES = 10

def _read(strict: 'bool'=False) -> 'dict[str, Any]':
    for attempt in range(_RETRIES):
        try:
            data = json.loads(paths.SETTINGS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
        except PermissionError:
            if attempt == _RETRIES - 1:
                if strict:
                    raise
            continue
        except (OSError, ValueError):
            return {}
        try:
            pass
        except PermissionError:
            if attempt == _RETRIES - 1:
                if strict:
                    raise
            continue
        except (OSError, ValueError):
            return {}
        return {}
    return {}

def load() -> 'dict[str, Any]':
    with _lock:
        data = _read()
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged

def get(key: 'str', default: 'Any'=None) -> 'Any':
    return load().get(key, DEFAULTS.get(key, default))

def save(changes: 'dict[str, Any]') -> 'dict[str, Any]':
    with _lock:
        paths.ensure_dirs()
        current = dict(DEFAULTS)
        current.update(_read(strict=True))
        current.update(changes)
        tmp = paths.SETTINGS_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        for attempt in range(_RETRIES):
            try:
                tmp.replace(paths.SETTINGS_FILE)
            except PermissionError:
                if attempt == _RETRIES - 1:
                    raise
                time.sleep(0.02)
                continue
            break
        return current

_ENV = {'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}
_ENV['phone'] = 'JARVIS_PHONE_TOKEN'

def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return

def get_secret(name: 'str') -> 'str':
    env = os.environ.get(_ENV.get(name, ''), '').strip()
    if env:
        return env
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(KEYRING_SERVICE, f'{name}_api_key')
            if value:
                return value.strip()
        except Exception:
            pass
    return str(load().get(f'_{name}_api_key_fallback', '') or '').strip()

def set_secret(name: 'str', value: 'str') -> 'str':
    """Anahtarı saklar; nereye yazıldığını döner ('keyring' veya 'file')."""

    value = (value or '').strip()
    kr = _keyring()
    if kr is not None:
        try:
            if value:
                kr.set_password(KEYRING_SERVICE, f'{name}_api_key', value)
            else:
                kr.delete_password(KEYRING_SERVICE, f'{name}_api_key')
            save({f'_{name}_api_key_fallback': ''})
        except Exception:
            pass
        return 'keyring'
    save({f'_{name}_api_key_fallback': value})
    return 'file'

def has_secret(name: 'str') -> 'bool':
    return bool(get_secret(name))

def get_app_config_value(key: 'str', default: 'Any'=None) -> 'Any':
    if key == 'gemini_api_key':
        return get_secret('gemini')
    return get(key, default)


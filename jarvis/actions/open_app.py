"""
Uygulama açma — macOS 'open' komutu ile çalışır.
"""

import subprocess
import shutil
APP_ALIASES = {'safari': 'Safari', 'chrome': 'Google Chrome', 'firefox': 'Firefox', 'terminal': 'Terminal', 'iterm': 'iTerm', 'iterm2': 'iTerm', 'finder': 'Finder', 'spotify': 'Spotify', 'vscode': 'Visual Studio Code', 'vs code': 'Visual Studio Code', 'code': 'Visual Studio Code', 'xcode': 'Xcode', 'notion': 'Notion', 'slack': 'Slack', 'discord': 'Discord', 'whatsapp': 'WhatsApp', 'telegram': 'Telegram', 'zoom': 'zoom.us', 'mail': 'Mail', 'calendar': 'Calendar', 'takvim': 'Calendar', 'notes': 'Notes', 'notlar': 'Notes', 'music': 'Music', 'müzik': 'Music', 'photos': 'Photos', 'fotoğraflar': 'Photos', 'maps': 'Maps', 'haritalar': 'Maps', 'calculator': 'Calculator', 'hesap makinesi': 'Calculator', 'system preferences': 'System Preferences', 'system settings': 'System Settings', 'ayarlar': 'System Settings', 'activity monitor': 'Activity Monitor', 'aktivite monitörü': 'Activity Monitor', 'preview': 'Preview', 'önizleme': 'Preview', 'textedit': 'TextEdit', 'numbers': 'Numbers', 'pages': 'Pages', 'keynote': 'Keynote', 'figma': 'Figma', 'postman': 'Postman', 'docker': 'Docker', 'sequel pro': 'Sequel Pro', 'tableplus': 'TablePlus'}

def open_app(app_name: str) -> str:
    '''Uygulamayı açar, başarı/hata mesajı döndürür.'''

    if not app_name:
        return 'Uygulama adı belirtilmedi.'
    normalized = app_name.lower().strip()
    resolved = APP_ALIASES.get(normalized, app_name)
    try:
        result = subprocess.run(['open', '-a', resolved], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return f'{resolved} açıldı.'
        result2 = subprocess.run(['open', resolved], capture_output=True, text=True, timeout=10)
        if result2.returncode == 0:
            return f'{app_name} açıldı.'
        return f"'{app_name}' bulunamadı veya açılamadı."
    except subprocess.TimeoutExpired:
        return f"'{app_name}' açılırken zaman aşımı."
    except Exception as e:
        return f'Hata: {e}'

_NEVER_CLOSE = {'dock', 'finder', 'loginwindow', 'controlcenter', 'systemuiserver'}

def _running_apps():
    from AppKit import NSApplicationActivationPolicyRegular, NSWorkspace
    import os
    me = os.getpid()
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.activationPolicy() != NSApplicationActivationPolicyRegular:
            continue
        if app.processIdentifier() == me:
            continue
        yield app

def close_app(app_name: str, force: bool=False) -> str:
    '''Açık bir uygulamayı kapatır (⌘Q ile aynı: kaydedilmemiş belge varsa uygulama sorar).

    Kapalı bir uygulamaya dokunmaz; AppleScript'teki `quit` gibi önce açıp sonra
    kapatmaz. `force` yalnızca kullanıcı açıkça "zorla kapat" dediğinde kullanılır.
    '''

    if not app_name:
        return 'Kapatılacak uygulamanın adı belirtilmedi.'
    wanted = app_name.lower().strip()
    resolved = APP_ALIASES.get(wanted, app_name).lower()
    if wanted in _NEVER_CLOSE or resolved in _NEVER_CLOSE:
        return f'{app_name} bir sistem bileşeni; kapatmıyorum.'
    try:
        apps = list(_running_apps())
    except Exception as exc:
        return f'Açık uygulamalar okunamadı: {exc}'
    def name(app) -> str:
        return str(app.localizedName() or '')

    def names(app) -> list[str]:
        found = [name(app).lower()]
        url = app.bundleURL()
        if url is not None:
            found.append(str(url.lastPathComponent() or '').removesuffix('.app').lower())
        return [n for n in found if n]

    matches = [a for a in apps if any((n in (wanted, resolved) for n in names(a)))]
    if not matches:
        matches = [a for a in apps if any((wanted in n or resolved in n for n in names(a)))]
    if not matches:
        return f'{app_name} şu anda açık değil.'
    closed = []
    for app in matches:
        ok = app.forceTerminate() if force else app.terminate()
        if ok:
            closed.append(name(app))
    if not closed:
        return f'{name(matches[0])} kapatılamadı.'
    how = 'zorla kapatıldı' if force else 'kapatıldı'
    return f'{', '.join(dict.fromkeys(closed))} {how}.'


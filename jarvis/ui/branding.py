'''Dock'ta ve menü çubuğunda "Python" yerine "JARVIS" görünsün.

Kaynak koddan çalışırken işlem Python yorumlayıcısıdır; macOS adını ve
simgesini oradan alır. NSApplication oluşmadan önce paket bilgisindeki adı
değiştirir, Dock simgesini de çalışma anında çizeriz. Paketlenmiş bir
uygulamada (.app) bunların hiçbiri gerekmez, zararı da yoktur.
'''

from __future__ import annotations
from .. import paths
ICON = paths.DATA_DIR / 'icon.png'

def render_icon(size: 'int'=512, inset: 'float'=24):
    """Halka simgesi: siyah zemin, camgöbeği ışık (PIL görüntüsü). `inset` 512'lik
    ölçekte kenar boşluğu; JARVIS.app'in .icns'i Apple'ın ızgarasıyla (50) buradan üretilir."""

    from PIL import (Image, ImageDraw, ImageFilter)
    k = size / 512
    b = (512 - 2 * inset) / 464
    def box(r: 'float') -> 'tuple[float, float, float, float]':
        c = size / 2
        return c - r * b * k, c - r * b * k, c + r * b * k, c + r * b * k

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    base = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle((inset * k, inset * k, size - inset * k, size - inset * k), radius=110 * b * k, fill=(4, 8, 12, 255))
    img.alpha_composite(base)
    glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse(box(150), outline=(94, 216, 255, 255), width=max(1, round(10 * b * k)))
    g.ellipse(box(112), outline=(94, 216, 255, 150), width=max(1, round(5 * b * k)))
    g.ellipse(box(60), fill=(94, 216, 255, 255))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18 * b * k)))
    img.alpha_composite(glow)
    ImageDraw.Draw(img).ellipse(box(26), fill=(255, 255, 255, 255))
    return img

def _draw_icon() -> 'None':
    '''Bir kez çizilir.'''

    paths.ensure_dirs()
    render_icon().save(ICON)

def apply(name: 'str'='JARVIS') -> 'None':
    if paths.IS_WIN:
        from . import win_window
        win_window.prepare()
        return
    if not paths.IS_MAC or paths.FROZEN:
        return
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info['CFBundleName'] = name
            info['CFBundleDisplayName'] = name
    except Exception:
        pass
    try:
        if not ICON.exists():
            _draw_icon()
        from AppKit import NSApplication, NSImage
        image = NSImage.alloc().initWithContentsOfFile_(str(ICON))
        if image is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(image)
            return
    except Exception:
        pass


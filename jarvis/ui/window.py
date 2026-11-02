'''Uygulama penceresi: pywebview.

pywebview gerçek bir yerel pencere açar ve içine HUD'ı yükler: macOS'ta
WKWebView (Safari'nin motoru), Windows'ta WebView2 (Edge'in motoru). Tarayıcı
açılmaz; bu bir web sitesi değil, bir uygulama penceresidir.

Köprü iki yönlüdür:
  sayfa → Python : window.pywebview.api.post(tür, veri)  → Api.post
  Python → sayfa : Hud.call("state", ...) → window.jarvis.state(...)

Python'dan sayfaya giden çağrılar bir kuyrukta toplanır ve ayrı bir iş
parçacığı onları ~40 ms'de bir tek seferde gönderir. Böylece beyin (ses
akışı) ekran güncellemesini asla beklemez; saniyede onlarca gelen ses seviyesi
güncellemesi de tek bir değere indirgenir.
'''

from __future__ import annotations
import json
import queue
import threading
import time
from typing import Any, Callable
import webview
from .. import paths
INDEX = paths.HUD_DIR / 'index.html'
webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
if paths.IS_WIN:
    webview.settings['DRAG_REGION_SELECTOR'] = '.surukle-yalniz-mac'
FLUSH_EVERY = 0.04

def _fit_to_screen(width: 'int', height: 'int') -> 'tuple[int, int]':
    '''İstenen boyut ekrana sığmıyorsa ekranın biraz içine küçült.'''

    try:
        screen = webview.screens[0]
        return min(width, screen.width - 80), min(height, screen.height - 100)
    except Exception:
        return width, height

class Api:
    '''Sayfanın çağırabildiği tek yöntem. Adı `_` ile başlayan her şey gizlidir.'''

    def __init__(self, handler: 'Callable[[str, dict], Any]') -> 'None':
        self._handler = handler

    def post(self, kind: 'str', data: 'dict | None'=None) -> 'Any':
        return self._handler(str(kind), dict(data or {}))


class Hud:
    def __init__(self, handler: 'Callable[[str, dict], Any]', title: 'str'='JARVIS') -> 'None':
        self._queue = queue.Queue()
        self._level = None
        self._ready = threading.Event()
        width, height = _fit_to_screen(1440, 900)
        self.window = webview.create_window(title, url=str(INDEX), js_api=Api(handler), width=width, height=height, min_size=(1100, 720), background_color='#000000', text_select=True)
        self.window.events.shown += self._style_native
        if paths.IS_WIN:
            from . import win_window
            win_window.install(self.window)
        self.window.events.closing += self._closing
        self.allow_close = False
        self.on_close_request = None
        threading.Thread(target=self._pump, daemon=True, name='hud-pump').start()

    def _style_native(self) -> 'None':
        """macOS: başlık çubuğu HUD'la aynı siyah, trafik ışıkları siyahın üstünde.

        İçerik bilerek başlık çubuğunun ALTINA uzatılmaz: yeni macOS sürümleri
        (Liquid Glass) başlığın altındaki kaydırılabilir görünümün (WKWebView)
        üstüne gri bir bulanıklık şeridi çiziyor ve bu şerit üst çubuğu örtüyor.
        Bunun yerine başlık çubuğunun kendisini siyaha boyuyoruz; pencere yine
        oradan sürüklenir. Görünüm her zaman koyu, sistem açık temada olsa bile.
        """

        if not paths.IS_MAC:
            return
        try:
            import AppKit
            import Quartz
            from PyObjCTools import AppHelper
        except ImportError:
            pass
        else:
            def apply() -> 'None':
                ns = self.window.native
                if ns is None:
                    return
                black = AppKit.NSColor.blackColor()
                ns.setTitlebarAppearsTransparent_(True)
                ns.setTitleVisibility_(AppKit.NSWindowTitleHidden)
                ns.setBackgroundColor_(black)
                ns.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
                ns.setCollectionBehavior_(ns.collectionBehavior() | AppKit.NSWindowCollectionBehaviorFullScreenPrimary)
                frame_view = ns.contentView().superview()
                for view in frame_view.subviews() if frame_view else []:
                    if view.className() == 'NSTitlebarContainerView':
                        view.setWantsLayer_(True)
                        view.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0, 0, 0, 1))
                        for inner in view.subviews():
                            if inner.className() == 'NSTitlebarBackgroundView':
                                inner.setHidden_(True)

            AppHelper.callAfter(apply)

    def call(self, method: 'str', *args: 'Any') -> 'None':
        if method == 'level':
            if args:
                self._level = float(args[0])
                return
            self._level = 0.0
            return
        encoded = ','.join((json.dumps(a, ensure_ascii=False) for a in args))
        self._queue.put(f'window.jarvis&&window.jarvis.{method}({encoded});')

    def mark_ready(self) -> 'None':
        self._ready.set()

    def _pump(self) -> 'None':
        self._ready.wait()
        time.sleep(FLUSH_EVERY)
        parts = []
        while True:
            try:
                parts.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if self._level is not None:
            parts.append(f'window.jarvis&&window.jarvis.level({self._level:.4f});')
            self._level = None
        if parts:
            try:
                self.window.run_js(''.join(parts))
            except Exception:
                pass

    def toggle_fullscreen(self) -> 'None':
        if not paths.IS_WIN:
            self.window.toggle_fullscreen()
            return
        from . import win_window
        entering = not win_window.is_fullscreen(self.window)
        if entering:
            self._was_maximized = win_window.is_maximized(self.window)
        self.window.toggle_fullscreen()
        win_window.restyle(self.window)
        if not entering:
            if getattr(self, '_was_maximized', False):
                win_window.maximize(self.window)

    def bring_to_front(self) -> 'None':
        '''Pencereyi öne getirip klavye odağını ver (ör. asistan haritayı açınca Esc çalışsın).'''

        if paths.IS_MAC:
            try:
                import AppKit
                from PyObjCTools import AppHelper
                def front() -> 'None':
                    ns = self.window.native
                    if ns is None:
                        return
                    if ns.isMiniaturized():
                        ns.deminiaturize_(None)
                    AppKit.NSApp.activateIgnoringOtherApps_(True)
                    ns.makeKeyAndOrderFront_(None)

                AppHelper.callAfter(front)
                return
            except ImportError:
                pass
        try:
            if paths.IS_WIN:
                from . import win_window
                if win_window.is_maximized(self.window):
                    self.window.show()
                    return
            self.window.restore()
            self.window.show()
        except Exception:
            return

    def _closing(self) -> 'bool':
        '''False dönerse kapanma iptal olur; uygulama kendi vedasını yapıp sonra kapatır.'''

        if self.allow_close or self.on_close_request is None:
            return True
        self.on_close_request()
        return False

    def closing(self) -> 'None':
        '''Kapanış başladı (veda sesi sürüyor, pencere birazdan kapanacak).'''

        if paths.IS_WIN:
            from . import win_window
            win_window.closing(self.window)

    def close(self) -> 'None':
        self.allow_close = True
        self.window.destroy()

    def pick_files(self) -> 'list[str]':
        '''Sistemin "Aç" penceresi; birden çok dosya seçilebilir. Vazgeçilirse boş liste.'''

        try:
            chosen = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        except Exception:
            return []
        return [str(p) for p in chosen or []]

    def listen_drops(self, callback: 'Callable[[list[str], list[str]], None]') -> 'None':
        """Pencereye bırakılan dosyalar → callback(yollar, yolu_olmayan_adlar).

        Dosyanın gerçek yolunu yalnızca pywebview'in kendi bırakma olayı verir
        (sayfadaki JS dosya adını görür, yolunu göremez). Tarayıcıdan sürüklenen
        bir resmin ya da Fotoğraflar'dan gelen bir kopyanın yolu yoktur; onların
        adı ikinci listede gelir ve sayfa içeriklerini kendisi okuyup gönderir.
        """

        from webview.dom import DOMEventHandler
        def on_drop(event: 'dict') -> 'None':
            files = ((event or {}).get('dataTransfer') or {}).get('files') or []
            found = [f['pywebviewFullPath'] for f in files if f.get('pywebviewFullPath')]
            missing = [f.get('name', '') for f in files if not f.get('pywebviewFullPath')]
            if found or missing:
                callback(found, missing)

        self.window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)


def start(on_started: 'Callable[[], None] | None'=None, debug: 'bool'=False) -> 'None':
    '''Pencere döngüsünü başlatır; pencere kapanınca döner (ana iş parçacığında çağrılmalı).'''

    extra = {}
    if paths.IS_WIN:
        from . import win_window
        extra['icon'] = win_window.icon_path()
    webview.start(on_started, http_server=True, debug=debug, private_mode=True, **extra)

# WARNING: Decompyle incomplete

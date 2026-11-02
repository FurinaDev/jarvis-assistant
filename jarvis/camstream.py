"""Kamera önizlemesi için yerel MJPEG akışı.

Ekrandaki önizleme akıcı olsun (saniyede ~24 kare) ama bilgisayarı yormasın
diye kareler JavaScript'e tek tek gönderilmez: bu küçük sunucu onları
`multipart/x-mixed-replace` olarak yayınlar, HUD'daki <img> etiketi de
tarayıcı motorunun kendi çözücüsüyle gösterir.

Yalnızca 127.0.0.1'i dinler ve adres rastgele bir belirteç içerir; aynı
bilgisayardaki başka bir program bile adresi tahmin edip kameraya bakamaz.
"""

from __future__ import annotations
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
BOUNDARY = 'jarvisframe'

class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class MJPEGStream:
    '''`next_frame(son_kimlik, zaman_aşımı)` → (yeni_kimlik, JPEG) ya da None.'''

    ''
    ''
    ''
    ''
    def __init__(self, next_frame: 'Callable[[int, float], tuple[int, bytes] | None]', is_active: 'Callable[[], bool]') -> 'None':
        self.token = secrets.token_urlsafe(16)
        self._next_frame = next_frame
        self._is_active = is_active
        stream = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path.split('?')[0] != f'/cam/{stream.token}.mjpg':
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', f'multipart/x-mixed-replace; boundary={BOUNDARY}')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                last = -1
                try:
                    while stream._is_active():
                        got = stream._next_frame(last, 1.0)
                        if got is None:
                            continue
                        last, frame = got
                        self.wfile.write(f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n'.encode())
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return


        self._server = _Server(('127.0.0.1', 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True, name='camstream').start()

    @property
    def url(self) -> 'str':
        return f'http://127.0.0.1:{self.port}/cam/{self.token}.mjpg'

    def close(self) -> 'None':
        self._server.shutdown()



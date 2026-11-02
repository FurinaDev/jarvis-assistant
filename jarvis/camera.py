"""Kamera: bir kez yakala, iki farklı hızda kullan.

- Ekran önizlemesi: saniyede en fazla PREVIEW_FPS kare, küçük JPEG, yerel MJPEG
  akışıyla (camstream) HUD'a gider. Akıcıdır ama her kare yalnızca bir kez ve
  küçük boyutta sıkıştırılır.
- Gemini: `latest()` yalnızca çağrıldığında (beyin saniyede bir ister) son ham
  kareyi sıkıştırır. Model boşuna kare yağmuruna tutulmaz, işlemci de her kareyi
  iki kez sıkıştırmaz.

Kamera 640×480 istenir; yakalama hızı kameranın kendi hızıdır (genelde 30).
"""

from __future__ import annotations
import threading
import time
from typing import Callable
from .camstream import MJPEGStream

class Webcam:
    MODEL_DIM, MODEL_QUALITY = 640, 72
    PREVIEW_DIM, PREVIEW_QUALITY, PREVIEW_FPS = 480, 70, 24
    def __init__(self) -> 'None':
        self._cond = threading.Condition()
        self._raw = None
        self._raw_id = 0
        self._model = None
        self._preview = None
        self._preview_id = 0
        self._stream = None
        self.active = False
        self.on_fail = None

    def start(self) -> 'bool':
        if self.active:
            return True
        try:
            import cv2
        except ImportError:
            return False
        self.active = True
        threading.Thread(target=self._run, daemon=True, name='webcam').start()
        return True

    def stop(self) -> 'None':
        with self._cond:
            self.active = False
            self._cond.notify_all()

    def stream_url(self) -> 'str':
        if self._stream is None:
            self._stream = MJPEGStream(self._next_preview, (lambda: self.active))
        return self._stream.url

    def latest(self) -> 'bytes | None':
        '''Gemini için son kare (640 px). Aynı ham kare için tekrar sıkıştırmaz.'''

        import cv2
        with self._cond:
            raw, raw_id, cached = self._raw, self._raw_id, self._model
        if raw is None:
            return
        if cached and cached[0] == raw_id:
            return cached[1]
        h, w = raw.shape[:2]
        if max(h, w) > self.MODEL_DIM:
            s = self.MODEL_DIM / max(h, w)
            raw = cv2.resize(raw, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', raw, [cv2.IMWRITE_JPEG_QUALITY, self.MODEL_QUALITY])
        if not ok:
            return
        data = buf.tobytes()
        with self._cond:
            self._model = raw_id, data
        return data

    def _next_preview(self, last_id: 'int', timeout: 'float') -> 'tuple[int, bytes] | None':
        with self._cond:
            if self._preview_id == last_id or self._preview is None:
                self._cond.wait(timeout)
            if self._preview is None or self._preview_id == last_id:
                return
            return self._preview_id, self._preview

    def _open(self):
        import cv2
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def _run(self) -> 'None':
        try:
            try:
                while self.active:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frame = cv2.flip(frame, 1)
                    with self._cond:
                        self._raw = frame
                        self._raw_id += 1
                    now = time.monotonic()
                    if now + 0.004 < next_preview:
                        continue
                    next_preview = max(next_preview + 1.0 / self.PREVIEW_FPS, now - 0.05)
                    h, w = frame.shape[:2]
                    small = cv2.resize(frame, (self.PREVIEW_DIM, int(h * self.PREVIEW_DIM / w)), interpolation=cv2.INTER_AREA)
                    ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, self.PREVIEW_QUALITY])
                    if ok:
                        with self._cond:
                            self._preview = buf.tobytes()
                            self._preview_id += 1
                            self._cond.notify_all()
            finally:
                import cv2
                cap = self._open()
                if not cap.isOpened():
                    self.stop()
                    if self.on_fail:
                        self.on_fail()
                for _ in range(4):
                    cap.read()
                next_preview = 0.0
        finally:
            self._raw = frame
            self._raw_id += 1
            now = time.monotonic()
            if now + 0.004 < next_preview:
                pass
            next_preview = max(next_preview + 1.0 / self.PREVIEW_FPS, now - 0.05)
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (self.PREVIEW_DIM, int(h * self.PREVIEW_DIM / w)), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, self.PREVIEW_QUALITY])
            if ok:
                with self._cond:
                    self._preview = buf.tobytes()
                    self._preview_id += 1
                    self._cond.notify_all()
            if self.active:
                pass
            cap.release()
            with self._cond:
                self._raw = self._preview = self._model = None
                self.active = False
                self._cond.notify_all()



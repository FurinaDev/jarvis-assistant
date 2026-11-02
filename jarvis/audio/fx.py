'''Kişiliğe özel ses efektleri.

Gemini Live'ın bütün sesleri insan sesi. ULTRON'un robotik duyulması için
modelden gelen ses, hoparlöre gitmeden önce burada işlenir:

  1. Halka modülasyonu: sesi düşük frekanslı bir taşıyıcıyla çarpar. Metalik,
     "makineden gelen" tınıyı veren şey budur.
  2. Tarak filtresi: çok kısa, geri beslemeli bir gecikme. Sese boru/kasa
     içindeymiş gibi rezonans katar.
  3. Kuru/ıslak karışım: anlaşılırlık kaybolmasın diye orijinal ses korunur.

Ses parça parça (akış hâlinde) geldiği için taşıyıcının fazı ve gecikme hattı
parçalar arasında korunur; yoksa her parçanın başında tık sesi olurdu.

Tepeler sert kırpılmaz (np.clip yüksek hecelerde cızırtı yapıyordu): soft_limit yumuşakça sınırlar.
'''

from __future__ import annotations
import numpy as np
SAMPLE_RATE = 24000
KNEE = 0.8

def soft_limit(x: 'np.ndarray') -> 'np.ndarray':
    """Yumuşak sınırlayıcı (yerinde, -1…1 ölçeğinde): ±KNEE'nin altı aynen kalır, üstü ±1'e yumuşakça yaklaşır,
    hiç aşmaz. Durumsuzdur: parça parça uygulamak parça sınırında tık sesi yapmaz."""

    over = np.abs(x) > KNEE
    if over.any():
        v = x[over]
        x[over] = np.sign(v) * (KNEE + (1 - KNEE) * np.tanh((np.abs(v) - KNEE) / (1 - KNEE)))
    return x

class VoiceFX:
    def process(self, pcm: 'bytes') -> 'bytes':
        return pcm

    def reset(self) -> 'None':
        pass


class RoboticFX(VoiceFX):
    def __init__(self, carrier_hz: 'float'=62.0, ring_mix: 'float'=0.55, comb_ms: 'float'=7.5, comb_feedback: 'float'=0.42, comb_mix: 'float'=0.35, gain: 'float'=0.9) -> 'None':
        self.carrier = 2 * np.pi * carrier_hz / SAMPLE_RATE
        self.ring_mix = ring_mix
        self.delay = max(1, int(SAMPLE_RATE * comb_ms / 1000))
        self.feedback = comb_feedback
        self.comb_mix = comb_mix
        self.gain = gain
        self.reset()

    def reset(self) -> 'None':
        self.phase = 0.0
        self.line = np.zeros(self.delay, dtype=np.float32)
        self.pos = 0

    def process(self, pcm: 'bytes') -> 'bytes':
        if not pcm:
            return pcm
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        n = x.size
        phases = self.phase + self.carrier * np.arange(n, dtype=np.float32)
        self.phase = float((self.phase + self.carrier * n) % (2 * np.pi))
        ringed = x * np.sin(phases)
        y = (1 - self.ring_mix) * x + self.ring_mix * ringed * 1.6
        d, fb = self.delay, self.feedback
        state = np.concatenate([self.line, np.zeros(n, dtype=np.float32)])
        out = np.empty_like(y)
        for start in range(0, n, d):
            end = min(start + d, n)
            prev = state[start:end]
            state[start + d:end + d] = y[start:end] + fb * prev
            out[start:end] = y[start:end] + self.comb_mix * prev
        self.line = state[n:n + d].copy()
        out *= self.gain
        soft_limit(out)
        return (out * 32767.0).astype(np.int16).tobytes()


def for_persona(fx_name: 'str') -> 'VoiceFX':
    if fx_name == 'robotic':
        return RoboticFX()
    return VoiceFX()


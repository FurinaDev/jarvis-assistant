"""Sessiz bağlantı testi: `python -m jarvis.selftest [kişilik ...]`

Mikrofon açılmaz, hoparlörden ses çıkmaz. Her kişilik için Gemini Live'a
bağlanır, selamı ve bir araç çağrısını bekler, gelen sesi sayar.
"""

from __future__ import annotations
import sys
import threading
import time
from . import personas, settings
from .brain.gemini_live import GeminiLiveBrain

class Recorder:
    def __init__(self) -> 'None':
        self.lines = []
        self.tools = []
        self.states = []
        self.event = threading.Event()

    def on_state(self, state, label=''):
        if not self.states or self.states[-1] != state:
            self.states.append(state)

    def on_transcript(self, who, text):
        self.lines.append((who, text))
        self.event.set()

    def on_tool(self, name, ok, summary):
        self.tools.append((name, ok, summary))

    def on_level(self, peak):
        pass

    def on_panel(self, name):
        pass

    def on_sfx(self, name):
        pass

    def on_webcam(self, active):
        pass

    def on_map(self, spot):
        self.tools.append(('map', True, str(spot.get('label', ''))[:60]))


def wait_for(rec: 'Recorder', who: 'str', after: 'int', timeout: 'float') -> 'str | None':
    end = time.time() + timeout
    while time.time() < end:
        for w, text in rec.lines[after:]:
            if w == who:
                return text
            if w == 'error':
                return
        rec.event.wait(0.25)
        rec.event.clear()

def check(key: 'str') -> 'bool':
    persona = personas.get(key)
    rec = Recorder()
    brain = GeminiLiveBrain(rec, persona, audio_io=False)
    brain.start()
    print(f'\n── {persona.name} ({persona.voice}, efekt: {persona.fx})')
    greeting = wait_for(rec, 'ai', 0, 30)
    print('  selam   :', greeting or 'YOK', f'| ses: {brain.audio_bytes / 48000:.1f} sn')
    n = len(rec.lines)
    brain.send_text('Pil durumum nedir?')
    answer = wait_for(rec, 'ai', n, 30)
    print('  araç    :', rec.tools[-1][:2] if rec.tools else 'çağrılmadı')
    print('  cevap   :', answer or 'YOK')
    errors = [t for w, t in rec.lines if w in ('error', 'sys')]
    if errors:
        print('  uyarılar:', errors)
    print('  durumlar:', ' → '.join(rec.states))
    brain.stop()
    return bool(greeting and answer and brain.audio_bytes > 0)

def main() -> 'int':
    if not settings.has_secret('gemini'):
        print('Gemini API anahtarı yok (GEMINI_API_KEY ya da uygulamadan girilmeli).')
        return 2
    keys = sys.argv[1:] or list(personas.PERSONAS)
    results = {k: check(k) for k in keys}
    print('\nSONUÇ:', ', '.join((f'{k}={'✓' if ok else '✗'}' for k, ok in results.items())))
    return 0 if all(results.values()) else 1

if __name__ == '__main__':
    sys.exit(main())

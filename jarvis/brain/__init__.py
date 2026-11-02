'''Beyin sağlayıcıları. Bugün: Gemini Live. İleride: Claude.'''

from .base import Brain, Listener

def create(provider: str, listener: Listener, persona) -> Brain:
    if provider == 'gemini':
        from .gemini_live import GeminiLiveBrain
        return GeminiLiveBrain(listener, persona)
    raise ValueError(f'Bilinmeyen beyin: {provider}')

__all__ = ['Brain', 'Listener', 'create']

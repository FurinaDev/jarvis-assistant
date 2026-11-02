'''İnternet araması (web_search aracı): ana Gemini Live oturumunun yanında kısa, ayrı bir oturum.

Ücretsiz anahtarlarda ana modele (3.8) Google araması verilince oturum 1011 "exceeded your current quota" ile
kapanıyor; yedek model (2.5 native audio) ise arayabiliyor. Ana model web_search aracını çağırınca soru arkada yedek
modelin kısa bir oturumunda Google'da aratılır: soru yazıyla gider, ses atılır, yalnızca sesin yazıya dökümü alınır ve
araç sonucu olarak döner. Cevabı ana model kendi sesi ve karakteriyle söyler. Söz üretimi bitince dönülür, tur sonu
beklenmez: Mac'te 7 sn (dolar/TL, maç sonuçları), uzun cevapta ~15 sn (9 Ekim 2026); sonuçlar güncel.

Araç iş parçacığında çalışır (gemini_live._run_tool); arama ayrı bir iş parçacığında, kendi kısa olay döngüsüyle
yapılır ve en geç TIMEOUT'ta dönülür (bağlantının kapanışı ya da takılan bir DNS sorgusu arkada biter). Hiçbir hata
dışarı taşmaz: başarısızlıkta modelin kullanıcıya aktaracağı kısa bir "Hata: …" metni döner.
'''

from __future__ import annotations
import asyncio
import concurrent.futures
import datetime as dt
import re
import threading
import time
from .. import settings
from ..log import log
MODEL = 'models/gemini-2.5-flash-native-audio-latest'
TIMEOUT = 25.0
PARALLEL = 2
_slots = threading.BoundedSemaphore(PARALLEL)
TAIL = 0.4
INSTRUCTION = 'Sen bir arama yardımcısısın. Her soruyu Google aramasıyla yanıtla. Yalnızca bulduğun bilgiyi olabildiğince kısa, en fazla iki cümleyle, Türkçe söyle; tarihleri, skorları ve sayıları ver. Doğrudan bilgiyle başla: "arama sonuçlarına göre" gibi giriş, kaynak ya da site adı, selam, yorum, uyarı ve soru ekleme. Bulamazsan yalnızca "Bulamadım." de. Bugünün tarihi ve saati: {now}.'
FAILED = 'Hata: internet araması yapılamadı ({why}). Kullanıcıya bunu kısaca söyle; tahmin yürütme, bilgi uydurma.'
_CONTROL = re.compile('<ctrl\\d+>', re.I)
_THOUGHT = re.compile('^\\s*(\\w+\\{[^}]*\\}\\s*)?\\**thought\\b', re.I)
_BAD_KEY = re.compile('api key not valid|api_key_invalid|invalid api key|api key expired', re.I)
_QUOTA = re.compile('quota|resource.?exhausted|\\b429\\b|rate.?limit|billing', re.I)
_SERVER = re.compile('\\b10(11|13)\\b|internal error|unavailable|overloaded|\\b50[03]\\b', re.I)
_OFFLINE = re.compile('getaddrinfo|nodename|name or service|network is unreachable|no route to host|connection refused|timed out|ssl|1006', re.I)

class _Garbled(Exception):
    '''Dökümde düşünce metni var: sonuç kullanılamaz.'''

def search(query: 'str') -> 'str':
    '''Soruyu arar; ana modele gidecek metni döner (başarısızsa kullanıcıya ne söyleneceği). Asla istisna fırlatmaz.'''

    query = ' '.join(str(query or '').split())
    if not query:
        return 'Aranacak bir soru verilmedi. Kullanıcıya ne aramak istediğini sor.'
    key = settings.get_secret('gemini')
    if not key:
        return FAILED.format(why='Gemini API anahtarı yok')
    began = time.monotonic()
    try:
        text = _search(key, query, began + TIMEOUT)
    except Exception as exc:
        why = _why(exc)
        detail = str(exc).replace(key, '…')[:120]
        log(f'arama: başarısız, {time.monotonic() - began:.1f} sn ({why}; {type(exc).__name__}: {detail})')
        return FAILED.format(why=why)
    log(f'arama: {time.monotonic() - began:.1f} sn · {len(text)} harf')
    if not text:
        return 'Arama sonuç vermedi. Kullanıcıya bunu kısaca söyle; tahmin yürütme.'
    return f'İnternet araması sonucu: {text}'

def _search(key: 'str', query: 'str', deadline: 'float') -> 'str':
    """Aramayı ayrı bir iş parçacığında başlatır, sonucu en geç `deadline`'a kadar bekler (geçerse TimeoutError).

    Süre dolunca arama iptal edilir ama kapanışı beklenmez: yarı kopuk ağda websockets bağlantıyı kapatırken 10 sn'ye
    kadar, asyncio.run takılan bir DNS sorgusunu dakikalarca bekleyebiliyor. Bunlar arkada biter."""

    if not _slots.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise TimeoutError('arama sırası gelmedi')
    done = concurrent.futures.Future()
    try:
        threading.Thread(target=_run, args=(key, query, deadline, done), name='internet araması', daemon=True).start()
    except BaseException:
        _slots.release()
        raise
    return done.result(max(0.0, deadline - time.monotonic()))

def _run(key: 'str', query: 'str', deadline: 'float', done: 'concurrent.futures.Future') -> 'None':
    freed = threading.Event()
    def free() -> 'None':
        if not freed.is_set():
            freed.set()
            _slots.release()

    async def main() -> 'None':
        try:
            done.set_result(await asyncio.wait_for(_ask(key, query), max(0.0, deadline - time.monotonic())))
        except Exception as exc:
            done.set_exception(exc)
        free()

    try:
        asyncio.run(main())
    finally:
        free()

async def _ask(key: 'str', query: 'str') -> 'str':
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key, http_options={'api_version': 'v1alpha'})
    config = types.LiveConnectConfig(response_modalities=['AUDIO'], output_audio_transcription={}, system_instruction=INSTRUCTION.format(now=f'{dt.datetime.now():%d.%m.%Y %H:%M}'), tools=[types.Tool(google_search=types.GoogleSearch())])
    said = []
    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            await session.send_client_content(turns={'role': 'user', 'parts': [{'text': query}]}, turn_complete=True)
            replies = session.receive()
            end = None
            wait = None if end is None else max(0.0, end - time.monotonic())
    except TimeoutError as exc:
        raise ConnectionError(f'bağlantı kurulamadı ({exc})') from exc
    try:
        response = await asyncio.wait_for(anext(replies), wait)
    except (StopAsyncIteration, asyncio.TimeoutError):
        pass
    else:
        sc = response.server_content
        if not sc:
            pass
        if sc.output_transcription and sc.output_transcription.text:
            said.append(sc.output_transcription.text)
        if sc.turn_complete:
            pass
        elif sc.generation_complete and end is None:
            end = time.monotonic() + TAIL
    try:
        pass
    except TimeoutError as exc:
        raise ConnectionError(f'bağlantı kurulamadı ({exc})') from exc
    text = ' '.join(_CONTROL.sub(' ', ''.join(said)).split())
    if _THOUGHT.search(text):
        raise _Garbled('döküm düşünce metni içeriyor')
    return text

def _why(exc: 'BaseException') -> 'str':
    '''Hatanın kullanıcıya söylenecek kısa nedeni.'''

    message = f'{type(exc).__name__} {exc}'
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, concurrent.futures.TimeoutError)):
        return f'arama {int(TIMEOUT)} saniyede bitmedi'
    if isinstance(exc, _Garbled):
        return 'arama sonucu okunamadı'
    if _BAD_KEY.search(message):
        return 'Gemini API anahtarı geçersiz'
    if _QUOTA.search(message):
        return "Google'daki arama hakkı şimdilik dolmuş"
    if _SERVER.search(message):
        return "Google'ın arama hizmeti şu an yanıt vermiyor"
    if isinstance(exc, OSError) or _OFFLINE.search(message):
        return 'internete bağlanılamadı'
    return 'beklenmeyen bir sorun çıktı'


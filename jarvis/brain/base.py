'''Beyin arayüzü.

"Beyin", kullanıcıyla konuşan ve araçları çağıran yapay zekadır. Bugün tek
uygulaması Gemini Live (ses ↔ ses). İleride Claude eklenecek; o zaman yalnızca
bu arayüzü uygulayan yeni bir sınıf yazılır. Araçlar (`jarvis.tools`) ve ekran
(`Listener`) aynen kalır.

Beyin ekrana doğrudan dokunmaz; olan biteni `Listener` üzerinden bildirir.
Bu sayede aynı beyin masaüstü penceresine, telefona ya da bir teste
bağlanabilir.
'''

from __future__ import annotations
import time
from abc import ABC, abstractmethod
from typing import Protocol
from ..personas import Persona

class Listener(Protocol):
    def on_state(self, state: 'str', label: 'str'='') -> 'None':
        '''connecting | listening | thinking | speaking | idle | error | paused'''

    def on_transcript(self, who: 'str', text: 'str') -> 'None':
        """who: 'you' | 'ai' | 'sys' | 'error' — tamamlanmış bir konuşma satırı."""

    def on_tool(self, name: 'str', ok: 'bool', summary: 'str') -> 'None':
        pass

    def on_level(self, peak: 'float') -> 'None':
        pass

    def on_panel(self, name: 'str') -> 'None':
        '''Bir araç çalışırken ilgili paneli öne çıkar.'''

    def on_sfx(self, name: 'str') -> 'None':
        """'done' | 'error' | 'start' — kısa ses efekti."""

    def on_webcam(self, active: 'bool') -> 'None':
        pass

    def on_map(self, spot: 'dict') -> 'None':
        '''Haritayı bir yere odakla (lat, lon, label, zoom).'''

    def on_files(self, file_paths: 'list[str]', made: 'bool') -> 'None':
        '''Asistanın bulduğu ya da hazırladığı dosyaları sohbette kart olarak göster.'''

    def on_mic_status(self, state: 'str', badge: 'str') -> 'None':
        '''Mikrofon: ok | blocked | busy | none | unreachable. Sorun sürdükçe ekranda rozet (badge).'''

    def on_mic_permission(self) -> 'None':
        '''İlk açılışta izin yüzünden kapalı kalan mikrofonun izni geldi: uygulama mikrofonu açar.'''

    def on_awakening(self, stage: 'str') -> 'None':
        '''ULTRON ilk kez takılı, selam yerine uyanış ("start"): sahneyi uygulama yürütür (jarvis.awakening).'''

    def on_scene_turn(self, replied: 'bool') -> 'None':
        '''Sahne sürerken modelin bir turu bitti; replied: öncesinde kullanıcı konuştu/yazdı mı.'''

    def on_net_refused(self) -> 'None':
        '''Hikâye işlerken ULTRON internete çıkamadığını söyledi: ekranda kısa bildirim.'''


class Brain(ABC):
    '''Her beyin sağlayıcısının uyması gereken sözleşme.'''

    provider: 'str' = 'base'
    def __init__(self, listener: 'Listener', persona: 'Persona') -> 'None':
        self.listener = listener
        self.persona = persona
        self.asleep = False
        self.mic_enabled = True
        self.last_exchange = time.monotonic()
        self.last_user_at = time.monotonic()
        self.last_user_text = ''
        self.last_ai_text = ''
        self.last_ai_proactive = False
        self.proactive_said = {}
        self.scene_hold = False
        self.mic_hold_until = 0.0
        self.scene_active = False
        self.tool_reply = False
        self.story_hold = False
        self.next_greeting = ''

    @abstractmethod
    def start(self) -> 'None':
        '''Arka planda çalışmaya başlar (bloklamaz).'''

    @abstractmethod
    def stop(self) -> 'None':
        pass

    @abstractmethod
    def send_text(self, text: 'str') -> 'None':
        '''Yazılı bir komutu konuşmaya ekler.'''

    @abstractmethod
    def set_persona(self, persona: 'Persona') -> 'None':
        '''Kişiliği değiştirir; ses/karakter değiştiği için oturum yenilenebilir.'''

    @abstractmethod
    def set_mic(self, enabled: 'bool') -> 'None':
        pass

    def reconnect(self) -> 'None':
        '''Ayar değişince (ör. yeni API anahtarı) oturumu yeniler.'''

    def set_language(self) -> 'None':
        '''Konuşma dili değişti (jarvis.language). Varsayılan: oturumu yenile.'''

        self.reconnect()

    def renamed(self, persona: 'Persona', greeting: 'str'='') -> 'None':
        '''Çip adları değişti (jarvis.brand): aynı kişilik yeni adlarla, temiz oturum. `greeting` doluysa (takılı
        çipin adı değişti) yeni oturum olağan selam yerine onunla açılır. Varsayılan: oturumu yenile.'''

        self.persona = persona
        if greeting:
            self.next_greeting = greeting
        self.reconnect()

    def announce(self, note: 'str') -> 'None':
        '''Uygulamadaki bir olayı (zamanlayıcı bitti…) asistana söyletir. Varsayılan: yok say.'''

    def announce_wait(self, note: 'str', wait: 'float'=12.0) -> 'bool':
        '''announce gibi, ama not asistana gerçekten gittiyse True (anımsatıcı ancak o zaman tamamlanır).
        Varsayılan: gönderemez.'''

        return False

    def busy(self) -> 'bool':
        '''Asistan konuşuyor ya da bir tur sürüyor mu.'''

        return False

    def idle(self) -> 'bool':
        '''Kimse konuşmuyor, araç çalışmıyor, cevap beklenmiyor: araya girilebilir.'''

        return not self.busy()

    def set_voice_volume(self, percent: 'int') -> 'None':
        '''Asistanın ses seviyesi (0–150 %). Sesi olmayan beyinler yok sayar.'''

    def replay_awakening(self) -> 'None':
        '''Kişiliğin ilk uyanış sahnesini yeniden oynatır (varsa).'''

    def restart_with(self, greeting: 'str') -> 'None':
        '''Temiz oturum (talimat yeniden kurulur); olağan selam yerine `greeting` gider. İyi sonda kalan çip zaten
        takılıyken. Varsayılan: notu bırak, oturumu yenile.'''

        self.next_greeting = greeting
        self.reconnect()

    def drop_greeting(self) -> 'None':
        '''Bekleyen açılış sözü gitmesin (★ › TEKRAR OYNA: iyi sonda kalanın [SON] sözü henüz söylenmediyse yeni
        hikâyede söylenmesin). Varsayılan: uygulamanın notunu at.'''

        self.next_greeting = ''

    def story_page(self, on: 'bool') -> 'None':
        '''ANAHTAR ya da ÇİP TAMİRİ açıldı/kapandı: açıkken komut alınmaz, asistan cevap vermez. Varsayılan: yalnızca
        bayrak.'''

        self.story_hold = bool(on)

    def story_pass(self) -> 'None':
        '''Bu tur sayfa açık olsa da duyulur (anahtarı açan söz). Varsayılan: yok say.'''

    def send_files(self, parts: 'list', text: 'str'='', what: 'str'='bu dosyayı') -> 'None':
        '''Dosya/fotoğraf gönderir. parts: [("text", str) | ("image", jpeg_bayt)] (jarvis.attachments).

        `text` kullanıcının sorusudur; boşsa soru beklenir (sesle ya da yazıyla).
        Görsel alamayan beyinler için varsayılan: yalnızca metin parçaları gider.
        '''

        body = '\n'.join((value for kind, value in parts if kind == 'text'))
        self.send_text(f'{body}\n{text or f'(Kullanıcı {what} gönderdi.)'}')

    def note_typing(self) -> 'None':
        '''Kullanıcı yazma satırında yazıyor (dosya ekledikten sonra sözünü kesmemek için).'''

    def say_scene(self, note: 'str') -> 'None':
        '''Bir sahnenin sözünü hemen söyletir (kullanıcı ekranda bir düğmeye bastı).'''

    def stage_note(self, note: 'str') -> 'None':
        '''Cevap istemeden bağlama not bırakır (kullanıcının sıradaki sözüne nasıl karşılık verileceği).'''

    def speak_up(self, note: 'str', wait: 'float'=20.0) -> 'bool':
        '''Kendiliğinden söz: sessiz bir anda nota göre konuşur. Sessiz an gelmezse vazgeçer.

        Çağıranı bekletir (en fazla `wait` sn); söz gittiyse True.
        '''

        return False



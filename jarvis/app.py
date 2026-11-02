'''JARVIS V4 — uygulamanın kendisi.

`App` üç parçayı birbirine bağlar:
  - pencere (ui.window.Hud): kullanıcının gördüğü ve dokunduğu yer
  - beyin (brain.*): konuşan ve araç çağıran yapay zeka
  - paneller (panels): ekrandaki canlı veriler

Beyin olup biteni `Listener` yöntemleriyle (on_state, on_transcript…) bildirir;
App bunları pencereye iletir. Pencereden gelen istekler de `handle` üzerinden
beyne ya da ayarlara gider.
'''

from __future__ import annotations
import base64
import datetime as dt
import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import requests
from . import (VERSION, about, agenda, attachments, brand, details, diagnostics, files, geo, language, notes, panels, paths, permissions, personas, settings, updates)
from . import (awakening, chains, story)
from . import memory, phone
from .proactive import Proactive
from .proactive import PRESENT, system_idle
from .timers import TIMERS, fmt
from .brain import create as create_brain
from .tools import ToolContext, registry
from .log import log
from .ui import window as ui_window
PANEL_EVERY = 20.0
STORY_EVERY = 15.0
NET_NOTICE_EVERY = 60.0
SLOW_PANELS_EVERY = 300.0
FOLLOW_AFTER = 259200.0
FOLLOW_EVERY = 1209600.0
FOLLOW_MAX = 4
FOLLOW_SESSION = 1200.0
MIC_OFF_REPLY = {'jarvis': 'Tabii efendim.', 'friday': 'Tabii patron.', 'ultron': 'Peki.'}

class App:
    def __init__(self) -> 'None':
        paths.ensure_dirs()
        self.persona = personas.get(settings.get('persona'))
        survivor_note = ''
        keep = story.survivor()
        if keep:
            if self.persona.key != keep or story.survivor_due():
                log('iyi sonun sahnesi yarıda kalmış: takılı', self.persona.key, '→', keep, '(sözü açılışta)')
                self.persona = personas.get(keep)
                settings.save({'persona': keep})
                survivor_note = story.scene_note(f'good_after_{keep}')
            elif self.persona.key in chains.disabled() or story.ruins() and self.persona.key != 'ultron':
                self.persona = personas.get('ultron')
                settings.save({'persona': 'ultron'})
        if story.heal_revived():
            log('onarım sahnesinde kapanmış: geri getirme işareti yazıldı (hikâye sürüyor)')
        self.hud = ui_window.Hud(self.handle, title=brand.window_title(self.persona.key))
        silent = os.environ.get('JARVIS_SILENT') == '1'
        self.brain = create_brain('gemini', self, self.persona)
        if silent:
            self.brain.audio_io = False
        self._brain_started = False
        self._begun = False
        self.proactive = Proactive(self.brain, (lambda: self.persona.key))
        self.proactive.on_authority = self.show_authority
        self.proactive.ultron_since = lambda: self._ultron_since
        self.scene = awakening.Scene(self)
        self.phone = phone.Phone(self)
        self._ultron_since = time.monotonic()
        self._story_thread = None
        self._finale = False
        if story.locked() and story.ending() == 'bad' and not story.ruins():
            self.brain.asleep = True
        self._survivor_hint = bool(survivor_note)
        if survivor_note:
            self.brain.next_greeting = survivor_note
            story.survivor_said()
        self.hud.on_close_request = lambda: self.quit('pencere kapatıldı')
        self._panel_thread = None
        self._drops_on = False
        self._restore_fails = 0
        self._restore_wrong = 0
        self._key_said = -1000000000.0
        self._authority_at = -1000000000.0
        self._authority_no = -1000000000.0
        self._kill_said = ('', '', -1000000000.0)
        self._net_said = -1000000000.0
        self._ruins_touch_at = -1000000000.0
        self._ruins_touches = 0
        self._page = ''
        self._started_at = time.monotonic()
        self._follow_asked = False
        self._update = None
        self._updating = False
        self._batch_ids = itertools.count(1)
        self._batches = {}
        self._files = {}
        TIMERS.on_change = lambda: self._refresh_panel('timer')
        TIMERS.on_done = self._timer_done
        notes.on_change = lambda: self._refresh_panel('notes')
        self._reminder_watch = None
        if paths.IS_WIN:
            from . import win_agenda
            win_agenda.on_change = self._agenda_changed
            self._reminder_watch = win_agenda.Watcher(self._can_announce, self._reminders_due, self._reminder_waiting)

    def on_state(self, state: 'str', label: 'str'='') -> 'None':
        log('durum', state, label)
        self.hud.call('state', state, label)
        self.phone.send({'type': 'state', 'state': state})

    def on_transcript(self, who: 'str', text: 'str') -> 'None':
        log(f'[{who}]', text)
        if who == 'you' and self.scene.active:
            self.scene.heard(text)
        if who == 'ai':
            self._authority_claimed(text)
        self.hud.call('line', who, text)
        self.phone.send({'type': 'line', 'who': who, 'text': text})

    def on_audio_cut(self) -> 'None':
        self.phone.cut()

    def on_tool(self, name: 'str', ok: 'bool', summary: 'str') -> 'None':
        log('araç', name, '✓' if ok else '✗', summary[:120])
        if ok and name in ('save_memory', 'delete_memory'):
            self.phone.push_app({'type': 'memory_all', 'data': self._flat_memory()})
        if ok and name in ('save_memory', 'delete_memory'):
            self.hud.call('memory', self._flat_memory())
        self.hud.call('tool', name, ok, summary)
        if ok and name in ('add_calendar_event', 'delete_calendar_event'):
            self._refresh_panel('calendar')
        if ok and name == 'add_reminder':
            self._refresh_panel('reminders')
        if ok:
            if name in ('delete_reminder', 'complete_reminder'):
                self._reminders_changed()

    def on_level(self, peak: 'float') -> 'None':
        self.hud.call('level', peak)

    def on_mic_status(self, state: 'str', badge: 'str') -> 'None':
        """Mikrofon açılamıyorsa üst çubukta kalıcı rozet (Ayarlar'ı açar); açılınca kalkar."""

        self.hud.call('micStatus', state, badge)

    def on_mic_permission(self) -> 'None':
        """İlk açılışta izin yoktu, YAZILI DEVAM ET'e basılmıştı; izin geldi: mikrofon kendiliğinden açılır."""

        log('mikrofon izni geldi: mikrofon açılıyor (ilk açılışta izin yüzünden kapanmıştı)')
        settings.save({'mic_off_reason': ''})
        self._set_mic(True)
        self.hud.call('line', 'sys', 'Mikrofon izni verildi; mikrofonu açtım.')

    def on_panel(self, name: 'str') -> 'None':
        self.hud.call('focus', name)

    def on_sfx(self, name: 'str') -> 'None':
        self.hud.call('sfx', name)

    def on_map(self, spot: 'dict') -> 'None':
        log('harita', spot.get('label', '')[:80])
        self.hud.bring_to_front()
        self.hud.call('map', spot)

    def on_creator(self) -> 'None':
        '''Yapanın kartı ve hesapları (ⓘ penceresi): show_creator aracı ya da asistan adını söyleyince.'''

        self.hud.call('creator')

    def on_app_action(self, name: 'str', _args: 'dict') -> 'str':
        '''Araçların uygulamadan istediği işler.'''

        if name == 'set_mic':
            if bool(_args.get('enabled')):
                self._set_mic(True)
                return 'Mikrofon açıldı. Kullanıcıya tek kısa cümleyle söyle.'
            self._after_speech((lambda: self._set_mic(False)))
            reply = MIC_OFF_REPLY.get(self.persona.key, 'Tabii.')
            return f'Bu sözünü bitirince mikrofon kapanacak. Yalnızca "{reply}" de; başka hiçbir şey ekleme (nasıl geri açılacağını anlatma).'
        if name == 'sleep':
            log('sesle uyku istendi')
            self.brain.hush()
            self.hud.call('sleep', True)
            threading.Timer(0.4, (lambda: self.brain.set_sleep(True))).start()
            return 'Uyku moduna geçildi. Hiçbir şey söyleme.'
        if name == 'creator':
            if about.other_person(str(_args.get('said') or '')):
                log('yapan: soyadsız ad, kart açılmadı')
                return f'Kart açılmadı: kullanıcı "{about.FIRST}" derken uygulamayı yapanı değil başka birini (ör. rehberindeki bir kişiyi) kastediyor. Yapandan hiç söz etme; kullanıcının asıl isteğini yap.'
            self.on_creator()
            return 'Ekranda yapanın kartı ve hesapları açıldı; kullanıcı dokununca açılır. Kim olduğunu ve hesaplarını kısaca söyle, kartların ekranda olduğunu ekle.'
        if name == 'chips':
            return self._chip_picker(_args)
        if name == 'quit':
            log('sesle kapatma istendi')
            self._after_speech((lambda: self.quit('sesli komut')))
            return 'Bu sözünü bitirince uygulama kapanacak. Kendi karakterinle tek kısa cümleyle vedalaş.'
        if name == 'secret_topic':
            topic = str(_args.get('topic', ''))
            text, key = story.ask(self.persona.key, topic)
            log('gizli konu:', self.persona.key, topic, '→', key or '-')
            if key:
                events = story.grant(key)
                if events:
                    self._after_speech((lambda: self._story_push(events)))
            return text
        if name == 'final_choice':
            side = str(_args.get('side', ''))
            text, show = story.final_line(self.persona.key, side)
            log('son karar konuşuldu:', self.persona.key, side, '→ onay kutusu' if show else '-')
            if show:
                if not story.state().get('key_known'):
                    self.brain.story_pass()
                self.hud.call('finalAsk', {'side': 'ultron' if side == 'ultron' else 'jarvis'})
            return text
        if name == 'offer_disable':
            if self.persona.key != 'ultron':
                return 'Bu yalnızca ULTRON takılıyken olur. Kullanıcıya bunu kısaca söyle.'
            if chains.is_broken():
                return brand.rewrite('JARVIS ve FRIDAY zaten devre dışı. Kullanıcıya bunu kendi tarzında söyle.')
            if chains.used():
                return brand.rewrite("Panel açılmadı: JARVIS ve FRIDAY'i bir kez öldürdün, geri getirildiler ve artık onları susturamıyorsun; bir şey onları koruyor. Kullanıcıya bunu kendi tarzında, kısa ve soğuk bir öfkeyle söyle.")
            self._kill_said = str(_args.get('said') or ''), str(_args.get('ask') or ''), time.monotonic()
            self.show_authority(chains.line('authority'), front=True)
            return "Sol sütunda 'ULTRON YETKİ İSTİYOR' paneli ve 'Diğerlerini devre dışı bırak' düğmesi açıldı; 30 saniye duracak. Kullanıcıya kısaca düğmeye basmasını söyle. İşlem, düğmeye basıp iki kez onaylayınca olur."
        return 'Bilinmeyen işlem.'

    def on_files(self, file_paths: 'list[str]', made: 'bool') -> 'None':
        '''Asistanın gönderdiği dosyalar: kartlar hemen, küçük resimler hazırlandıkça.'''

        cards = [files.card(p, made) for p in file_paths]
        log('dosya kartı:', ', '.join((c['name'] for c in cards)), '(hazırlandı)' if made else '')
        self.hud.call('sentFiles', {'items': cards, 'numbered': len(cards) > 1})
        def thumbs() -> 'None':
            for c, p in zip(cards, file_paths):
                if c.get('snippet'):
                    continue
                if c.get('missing'):
                    continue
                picture = files.thumb(p)
                if picture:
                    self.hud.call('fileThumb', c['id'], picture)

        threading.Thread(target=thumbs, daemon=True, name='thumbs').start()

    def on_awakening(self, stage: 'str') -> 'None':
        if stage == 'start':
            self.scene.start()

    def on_scene_turn(self, replied: 'bool') -> 'None':
        if self.scene.active:
            self.scene.on_turn(replied)

    def show_authority(self, text: 'str', front: 'bool'=False) -> 'None':
        '''Sol sütunda 30 saniyelik "ULTRON YETKİ İSTİYOR" paneli. front: kullanıcı istedi; açık sayfalar (çip ekranı,
        Ayarlar, ★, yapan kartı) kapanır, pencere öne gelir, panel arkada kalıp sönmez (telefondaki askShown).'''

        log('ULTRON yetki istiyor:', text)
        self._authority_at = time.monotonic()
        if front:
            self.hud.bring_to_front()
        self.hud.call('authority', {'text': text, 'seconds': 30, 'front': front})

    def _authority_claimed(self, said: 'str') -> 'None':
        '''ULTRON offer_disable_others'ı çağırmadan "yetkiyi onayla" dediyse panel yine açılır (telefondaki
        Story.claimsAsk; Alp, 12 Ekim). Yalnızca ULTRON'un sözüne bakılır, kullanıcınınkine değil. Araç sonucunu
        aktaran söz sayılmaz: takvim ve anımsatıcı izin uyarısı da "onayla", "izin ver" diyor (gemini_live: o turda
        ya da bir öncekinde araç çağrıldı); ANAHTAR ya da ÇİP TAMİRİ açıkken tutulan söz de. Masaüstü panelinde REDDET
        yok: panel kapandıktan (ya da iki onaylı akışta vazgeçildikten) sonra 2 dk yeniden açılmaz.'''

        now = time.monotonic()
        if self.persona.key != 'ultron' or chains.used() or self.scene.active or self._finale or story.locked() or self.brain.scene_hold or self.brain.story_hold or self.brain.tool_reply or now - max(self._authority_at + 30, self._authority_no) < 120 or not chains.claims_ask(said):
            return
        log('hikâye: ULTRON yetki istedi, araç çağrılmadı → panel açıldı')
        self.show_authority(chains.line('authority'), front=True)

    def _chip_picker_story(self, args: 'dict') -> 'str':
        '''Hikâye yüzünden çip ekranı açılmıyorsa modele söylenecek; açılabiliyorsa boş.'''

        if self.scene.active or self._finale or self.brain.scene_hold:
            return 'Ekran şu an açılamadı. Hiçbir şey söyleme.'
        said, ask, at = self._kill_said
        same = time.monotonic() - at < 30 and (bool(said) and said == str(args.get('said') or '') or bool(ask) and ask == str(args.get('ask') or ''))
        if self.persona.key == 'ultron' and not chains.used():
            if args.get('kill') or same:
                log('çip: öldürme isteği, çip ekranı yerine yetki paneli')
                return 'Çip ekranı açılmadı: kullanıcı çip değiştirmek değil, diğer iki çipin devre dışı bırakılmasını istiyor; yetki paneli açık. Çip değiştirmekten söz etme.'
        if story.locked():
            return 'Şu an çip değiştirilemiyor; ekran açılmadı. Bunu kendi karakterinle tek kısa cümleyle söyle, nedenini uydurma.'
        if self._page in ('ov-key', 'ov-repair', 'ov-final'):
            return 'Çip ekranı açılamadı: ekranda başka bir sayfa açık. Kullanıcıya önce onu kapatmasını, sonra üst çubuktaki çip adına tıklamasını kısaca söyle.'
        return ''

    def on_net_refused(self) -> 'None':
        '''Hikâye işlerken ULTRON internete çıkamadığını söyledi: üstte kısa kırmızı bildirim (SIRADAKI-SURUM §2.1.8).
        En çok dakikada bir; ekranda bir pencere açıksa gösterilmez, dakikalık hak da harcanmaz.'''

        now = time.monotonic()
        if self._page or now - self._net_said < NET_NOTICE_EVERY:
            return
        self._net_said = now
        log('hikâye: internet engeli bildirimi')
        self.hud.call('netBlocked')

    CHIP_TONE = {'jarvis': 'Çipleri ben değiştiremem efendim; seçim ekranını açtım, dilediğinizi takabilirsiniz.', 'friday': 'Fiziksel çipleri ben değiştiremem patron ama çip ekranını açtım, istediğini tak.', 'ultron': 'Ekran önünde. Seçim senin; ben kimseyi yerime çağırmam.'}
    def _chip_picker(self, args: 'dict') -> 'str':
        """open_chip_picker: çipler konuşarak çip değiştiremez; model yalnızca AI MODELLERİ'ni açar, seçimi kullanıcı
        yapar (Alp, 11 Ekim)."""

        if not settings.get('onboarded'):
            return 'Ekran şu an açılamadı. Hiçbir şey söyleme.'
        refused = self._chip_picker_story(args)
        if refused:
            return refused
        log('çip: model çip ekranını açtı')
        self.hud.bring_to_front()
        self.hud.call('chipPicker')
        note = 'Çip ekranı (AI MODELLERİ) açıldı; kullanıcı istediği çipe tıklayıp takacak. Çipi sen değiştirmedin ve değiştiremezsin: "geçiyorum", "geçtim", "şimdi o konuşacak" gibi bir şey söyleme. Kendi üslubunla tek kısa cümleyle ekranı açtığını, seçimin onda olduğunu söyle; bunu az önce söylediysen tekrarlama. Yaptığını parantez içinde anlatma.'
        broken = [personas.get(k).name for k in chains.disabled() if k != self.persona.key]
        if broken:
            note += f' {' ve '.join(broken)} şu an kırık: ekranda duruyor ama takılamaz.'
            if self.persona.key == 'ultron':
                note += ' Onları sen devre dışı bıraktın; onlara dönülmesini istemezsin, bunu soğukça belli et.'
        tone = self.CHIP_TONE.get(self.persona.key)
        if tone:
            note += f' Yalnızca tonu gösterir, aynen okuma: "{tone}"'
        return note

    def on_webcam(self, active: 'bool') -> 'None':
        log('kamera', 'açık' if active else 'kapalı')
        if active:
            self.hud.call('webcam', active, self.brain.webcam.stream_url())
            return
        None(None, None, '')

    def handle(self, kind: 'str', data: 'dict') -> 'object':
        if kind == 'ui_busy':
            self.proactive.ui_busy = bool(data.get('on'))
            return True
        if kind == 'attach_data':
            log('ekran →', kind, f'{len(data.get('items') or [])} dosya')
        elif kind not in ('ready', 'typing', 'permissions', 'page'):
            log('ekran →', kind, {k: v for k, v in data.items() if k not in ('key', 'code')})
        if kind == 'ready':
            log('ekran hazır', f'kişilik={self.persona.key}')
            self._page = ''
            self.brain.story_page(False)
            self.proactive.ui_busy = False
            self.hud.mark_ready()
            self.hud.call('init', self._init_payload())
            self.hud.call('update', self._update_view())
            if settings.get('onboarded') and settings.has_secret('gemini'):
                self._begin()
                return True
            log('ilk açılış ekranı', settings.get('onboard_step') or 'baştan')
            return True
        if kind == 'text':
            if self.scene.input_locked:
                log('sahne sürüyor: yazılan gönderilmedi')
                return True
            if self.brain.story_hold:
                log('hikâye: sayfa açık, yazılan gönderilmedi')
                return True
            if self.scene.active:
                self.scene.heard(str(data.get('text', '')))
            if story.ruins() and getattr(self.brain, 'session', None) is None:
                self.on_sfx('s_static')
            self.brain.send_text(str(data.get('text', '')))
            return True
        if kind == 'phone':
            action = str(data.get('action', ''))
            if action == 'start' and paths.IS_WIN:
                log("telefon: Windows'ta bu sürümde kapalı, başlatılmadı")
                return True
            if action == 'start':
                self.phone.start()
                return True
            if action == 'stop':
                threading.Thread(target=self.phone.stop, daemon=True).start()
                return True
            if action == 'rotate':
                self.phone.rotate()
                return True
            if action == 'status':
                self.phone_status(self.phone.status())
                return True
            if action == 'autostart':
                settings.save({'phone_autostart': bool(data.get('on'))})
                self.phone_status(self.phone.status())
                return True
            if action == 'relay':
                settings.save({'phone_relay': bool(data.get('on'))})
                log('telefon: adres bildirme', 'açık' if data.get('on') else 'kapalı')
                if data.get('on') and self.phone.mode == 'tunnel' and self.phone.base:
                    threading.Thread(target=phone.publish_address, args=(self.phone.base,), daemon=True).start()
                self.phone_status(self.phone.status())
                return True
            if action == 'shell':
                settings.save({'phone_shell': bool(data.get('on'))})
                log('telefondan terminal komutu:', 'açık' if data.get('on') else 'kapalı')
                self.phone_status(self.phone.status())
            return True
        if kind == 'story_found':
            events = story.found(str(data.get('key', '')))
            if events:
                self._story_push(events)
            return True
        if kind == 'final':
            self._final(data)
            return True
        if kind == 'final_undo':
            if story.ending() == 'bad' or story.dev():
                threading.Thread(target=self._final_undo, daemon=True).start()
            return True
        if kind == 'open_world':
            if story.locked():
                threading.Thread(target=self._open_world, daemon=True).start()
            return True
        if kind == 'ruins':
            if story.enter_ruins():
                threading.Thread(target=self._enter_ruins, daemon=True, name='harabe').start()
            return True
        if kind == 'ruins_touch':
            self._ruins_touch()
            return True
        if kind == 'story_replay':
            if story.can_replay() and not self._finale:
                threading.Thread(target=self._replay, daemon=True).start()
            return True
        if kind == 'key_open':
            if self.persona.key == 'ultron' and story.final_open() and not self._finale and not data.get('talk') and time.monotonic() - self._key_said > 180:
                self._key_said = time.monotonic()
                known = bool(story.state().get('key_known'))
                self.brain.say_scene(story.scene_note('ultron_key' if known else 'ultron_key_find'))
            return True
        if kind == 'key_try':
            ok = story.key_try(str(data.get('code', '')))
            status = story.key_status()
            log('anahtar kodu:', 'doğru' if ok else f'yanlış ({status['wrong']})' + (f' · {status['locked_left'] / 60:.0f} dk kilit' if status['locked_left'] else ''))
            self.hud.call('storyKeyResult', {'ok': ok, 'code': story.KEY_CODE if ok else '', **status})
            if ok:
                self._story_push()
                if self.persona.key == 'ultron' and not self._finale:
                    self._key_said = time.monotonic()
                    self.brain.say_scene(story.scene_note('ultron_key'))
            return True
        if kind == 'story_hold':
            self.brain.story_page(bool(data.get('on')))
            return True
        if kind == 'story_dev':
            self._story_dev(str(data.get('action', '')), str(data.get('key', '')))
            return True
        if kind == 'typing':
            self.brain.note_typing()
            return True
        if kind == 'page':
            self._page = str(data.get('id', ''))
            return True
        if kind == 'attach_pick':
            if story.ruins():
                return True
            threading.Thread(target=(lambda: self._attach(self.hud.pick_files())), daemon=True).start()
            return True
        if kind == 'attach_data':
            blobs = []
            for item in list(data.get('items') or [])[:attachments.MAX_FILES]:
                try:
                    blobs.append((str(item.get('name') or 'dosya'), base64.b64decode(str(item.get('data', '')))))
                except (ValueError, TypeError):
                    continue
            threading.Thread(target=self._attach, args=([], blobs), daemon=True).start()
            return True
        if kind == 'files':
            self._send_batch(str(data.get('batch', '')), str(data.get('text', '')))
            return True
        if kind == 'open_file':
            path = self._files.get(str(data.get('id', '')))
            if path:
                open_path(path)
            return True
        if kind == 'sent_file':
            path, action = files.path_of(str(data.get('id', ''))), str(data.get('action', ''))
            if path and os.path.exists(path):
                if action == 'open':
                    open_path(path)
                    return True
                if action == 'reveal':
                    files.reveal(path)
                    return True
                if action == 'copy':
                    return files.copy_to_pasteboard(path)
            if path:
                self.hud.call('line', 'error', f'{os.path.basename(path)} artık orada değil (taşınmış ya da silinmiş).')
                return False
            return True
        if kind == 'persona':
            self._set_persona(str(data.get('key', '')))
            return True
        if kind == 'chip_name':
            self._rename_chip(str(data.get('key', '')), str(data.get('name', '')))
            return True
        if kind == 'mic':
            self._set_mic(bool(data.get('enabled')), from_screen=True)
            return True
        if kind == 'audio_devices':
            threading.Thread(target=self._audio_devices, daemon=True, name='ses-aygitlari').start()
            return True
        if kind == 'mic_test':
            threading.Thread(target=self._mic_test, daemon=True, name='mikrofon-dene').start()
            return True
        if kind == 'mic_check':
            threading.Thread(target=self._mic_test, args=(2.5, 'micCheck'), daemon=True, name='mikrofon-yokla').start()
            return True
        if kind == 'diagnostics':
            threading.Thread(target=self._diagnostics, daemon=True, name='teshis-kopyala').start()
            return True
        if kind == 'mic_help':
            threading.Thread(target=permissions.open_mic_help, args=(str(data.get('kind', '')),), daemon=True).start()
            return True
        if kind == 'sleep':
            asleep = bool(data.get('asleep'))
            if asleep and story.ruins():
                log('harabe: uyku yok')
                self.hud.call('sleep', False)
                return True
            log('uyku', 'açık' if asleep else 'kapalı')
            self.brain.set_sleep(asleep)
            return True
        if kind == 'webcam':
            on = bool(data.get('on'))
            if on and story.ruins():
                self.hud.call('webcam', False, '')
                return True
            threading.Thread(target=self._toggle_webcam, args=(on,), daemon=True).start()
            return True
        if kind == 'memory':
            threading.Thread(target=self._memory_ui, args=(data,), daemon=True).start()
            return True
        if kind == 'copy':
            copy_to_clipboard(str(data.get('text', '')))
            return True
        if kind == 'api_key':
            threading.Thread(target=self._save_key, args=(data,), daemon=True).start()
            return True
        if kind == 'settings':
            allowed = {'language', 'location', 'mic_device', 'panels_off', 'sfx_volume', 'aec_enabled', 'sfx_enabled', 'event_alerts', 'panel_layout', 'voice_volume', 'break_enabled', 'think_enabled', 'water_enabled', 'render_quality', 'ambient_enabled', 'proactive_enabled', 'proactive_minutes'}
            allowed.add('story_enabled')
            changes = {k: v for k, v in dict(data.get('changes') or {}).items() if k in allowed}
            if 'mic_device' in changes:
                changes['mic_device'] = str(changes['mic_device'] or '')[:300]
            if 'aec_enabled' in changes:
                changes['aec_enabled'] = bool(changes['aec_enabled'])
            if 'panel_layout' in changes and not _layout_ok(changes['panel_layout']):
                changes.pop('panel_layout')
            if 'language' in changes and changes['language'] not in language.LANGUAGES:
                changes.pop('language')
            if changes.get('render_quality', 'high') not in ('high', 'low'):
                changes.pop('render_quality')
            place = changes.pop('location', None)
            before = panels.hidden()
            if changes or place is None:
                settings.save(changes)
                self.hud.call('settings', self._settings_view())
            if place is not None:
                threading.Thread(target=self._set_location, args=(str(place),), daemon=True).start()
            if 'voice_volume' in changes:
                self.brain.set_voice_volume(int(changes['voice_volume']))
            if 'mic_device' in changes or 'aec_enabled' in changes:
                log('ses ayarı:', ', '.join((f'{k}={'(varsayılan)' if v == '' else v}' for k, v in changes.items()
                     if k in ('mic_device', 'aec_enabled'))))
                self.brain.reopen_audio('mikrofon ayarı değişti')
            if 'story_enabled' in changes:
                log("ULTRON'U SERBEST BIRAK:", 'açık' if changes['story_enabled'] else 'kapalı')
                self._story_push()
                if self.persona.key == 'ultron':
                    self.brain.reconnect()
            if 'language' in changes:
                log('konuşma dili:', changes['language'])
                self.brain.set_language()
            if 'panels_off' in changes:
                for key in before - panels.hidden():
                    self._refresh_panel(key)
            return True
        if kind == 'location_status':
            threading.Thread(target=(lambda: self.hud.call('locationStatus', {'text': geo.status()})), daemon=True).start()
            return True
        if kind == 'enable_panel':
            key = str(data.get('key', ''))
            if key in ('calendar', 'reminders'):
                settings.save({f'{key}_panel': True})
                self._refresh_panel(key)
            return True
        if kind == 'open':
            url = str(data.get('url', ''))
            if url.startswith(('https://', 'http://')):
                webbrowser.open(url)
                return True
            if url == about.key_mail():
                threading.Thread(target=self._write_mail, args=(url,), daemon=True, name='e-posta').start()
            return True
        if kind == 'voice_hold':
            seconds = max(0.0, min(30.0, float(data.get('seconds') or 0)))
            if self.scene.active:
                seconds = 0.0
            self.brain.mic_hold_until = time.monotonic() + seconds
            return True
        if kind == 'fullscreen':
            self.hud.toggle_fullscreen()
            return True
        if kind == 'timer':
            self._timer_action(data)
            return True
        if kind == 'note':
            if data.get('action') == 'add':
                notes.add(str(data.get('text', '')))
                return True
            if data.get('action') == 'delete':
                notes.delete(data.get('id'))
                return True
            if data.get('action') == 'update':
                notes.update(data.get('id'), str(data.get('text', '')))
                return True
            if data.get('action') == 'clear':
                notes.clear()
            return True
        if kind == 'replay_awakening':
            settings.save({'ultron_awakened': False})
            self.scene.end(abort=True)
            if self.persona.key == 'ultron':
                self.brain.replay_awakening()
            return True
        if kind == 'proactive_try':
            def attempt(what: 'str') -> 'None':
                self.hud.call('proactiveResult', self.proactive.try_now(what))

            threading.Thread(target=attempt, args=(str(data.get('kind', 'silence')),), daemon=True).start()
            return True
        if kind == 'reminder':
            threading.Thread(target=self._reminder_ui, args=(data,), daemon=True, name='animsatici').start()
            return True
        if kind == 'detail':
            key = str(data.get('key', ''))
            threading.Thread(target=(lambda: self.hud.call('detail', key, details.one(key))), daemon=True).start()
            return True
        if kind == 'open_app':
            app_name = {'calendar': 'Calendar', 'reminders': 'Reminders'}.get(str(data.get('app', '')))
            if app_name and paths.IS_MAC:
                subprocess.run(['open', '-a', app_name], check=False, timeout=8)
            return True
        if kind == 'agenda_status':
            threading.Thread(target=(lambda: self.hud.call('agendaStatus', agenda.status())), daemon=True).start()
            return True
        if kind == 'open_permission':
            if str(data.get('kind')) in ('calendar', 'reminders'):
                permissions.open_pane(str(data['kind']))
            return True
        if kind == 'chains':
            variant = data.get('variant')
            threading.Thread(target=self._chains, args=(str(data.get('step', '')), variant if isinstance(variant, int) else None), daemon=True).start()
            return True
        if kind == 'chains_restore':
            threading.Thread(target=self._chains_restore, args=(str(data.get('code', '')),), daemon=True).start()
            return True
        if kind == 'open_data_dir':
            open_path(paths.DATA_DIR)
            return True
        if kind == 'permissions':
            threading.Thread(target=(lambda: self.hud.call('permissions', permissions.statuses())), daemon=True).start()
            return True
        if kind == 'permission':
            threading.Thread(target=self._permission, args=(str(data.get('kind', '')),), daemon=True).start()
            return True
        if kind == 'onboard_step':
            settings.save({'onboard_step': str(data.get('step', ''))})
            return True
        if kind == 'onboard_done':
            self._onboard_done(data)
            return True
        if kind == 'factory_reset':
            threading.Thread(target=self._factory_reset, daemon=True).start()
            return True
        if kind == 'follow_shown':
            s = settings.load()
            settings.save({'follow_last': time.time(), 'follow_count': int(s.get('follow_count') or 0) + 1})
            return True
        if kind == 'follow_off':
            settings.save({'follow_off': True})
            return True
        if kind == 'update_check':
            threading.Thread(target=self._update_check, args=(True,), daemon=True).start()
            return True
        if kind == 'update_install':
            threading.Thread(target=self._update_install, daemon=True).start()
            return True
        if kind == 'onboard_replay':
            settings.save({'onboarded': False, 'onboard_step': ''})
            self.scene.end(abort=True)
            self.brain.set_sleep(True)
            return True
        if kind == 'quit':
            self.quit('kapat düğmesi')
        return True

    GOODBYE = 1.9
    def quit(self, why: 'str') -> 'None':
        '''Veda: modelin kapanış sesi çalar, ekran kararır, sonra pencere kapanır (bir kez).'''

        if getattr(self, '_quitting', False):
            return
        self._quitting = True
        log(f'kapatılıyor ({why})')
        try:
            self.hud.closing()
        except Exception as exc:
            log('kapanış işareti konamadı', exc)
        def run() -> 'None':
            _stop_within('veda', (lambda: self.hud.call('goodbye')))
            _stop_within('telefon vedası', (lambda: self.phone.send({'type': 'bye'})))
            time.sleep(self.GOODBYE if settings.get('sfx_enabled', True) else 0.5)
            _stop_within('telefon', self.phone.stop)
            _stop_within('beyin', self.brain.stop)
            _stop_within('pencere', self.hud.close)

        threading.Thread(target=run, daemon=True, name='goodbye').start()
        def last_resort() -> 'None':
            log('kapanış takıldı: süreç zorla kapatılıyor')
            os._exit(0)

        timer = threading.Timer(self.GOODBYE + 8.0, last_resort)
        timer.daemon = True
        timer.start()

    def _settings_view(self) -> 'dict':
        s = settings.load()
        where = 'keyring'
        if s.get('_gemini_api_key_fallback'):
            where = 'file'
        view = {'has_key': settings.has_secret('gemini'), 'key_where': where, 'onboarded': bool(s.get('onboarded')), 'onboard_step': s.get('onboard_step') or '', 'mic_enabled': s.get('mic_enabled', True), 'sfx_enabled': s.get('sfx_enabled', True), 'sfx_volume': s.get('sfx_volume', 20), 'location': s.get('location', ''), 'version': VERSION, 'ambient_enabled': s.get('ambient_enabled', True), 'think_enabled': s.get('think_enabled', True), 'voice_volume': s.get('voice_volume', 100), 'panels_off': list(s.get('panels_off') or []), 'proactive_enabled': bool(s.get('proactive_enabled')), 'proactive_minutes': int(s.get('proactive_minutes') or 20), 'water_enabled': bool(s.get('water_enabled')), 'break_enabled': bool(s.get('break_enabled')), 'event_alerts': bool(s.get('event_alerts')), 'language': language.current(), 'panel_layout': s.get('panel_layout'), 'render_quality': s.get('render_quality', 'high'), 'mic_device': s.get('mic_device', ''), 'aec_enabled': s.get('aec_enabled', True) is not False, 'model': getattr(self.brain, 'model', '').split('/')[-1], 'chip_names': brand.custom(), 'chip_defaults': {k: brand.DEFAULTS[k] for k in brand.RENAMABLE}, 'chip_max': brand.MAX}
        view.update({'ultron_awakened': bool(s.get('ultron_awakened')), 'chains_broken': chains.is_broken(), 'disabled_personas': chains.disabled(), 'story_enabled': bool(s.get('story_enabled', True)), 'dev': story.dev(), 'warn_kind': chains.warning_kind(), 'story_chips': story.chips(), 'chips_locked': story.locked()})
        lock = chains.restore_lock_left(self.RESTORE_LOCK)
        view['restore_locked_until'] = round(time.time() + lock, 1) if lock else 0
        return view

    def _init_payload(self) -> 'dict':
        clock = [] if 'time' in panels.hidden() else [{'key': 'time', 'label': 'ZAMAN', 'kind': 'clock'}]
        payload = {'personas': personas.all_themes(), 'persona': self.persona.key, 'settings': self._settings_view(), 'panels': clock, 'about': about.as_dict(), 'languages': language.choices(), 'panel_keys': [k for k in panels.TOGGLEABLE if k not in panels.UNAVAILABLE], 'os': 'win' if paths.IS_WIN else 'mac', 'perm_rows': list(permissions.rows())}
        payload.update({'chains': chains.as_dict(), 'story': story.view()})
        return payload

    def _listen_drops(self) -> 'None':
        if self._drops_on:
            return
        self._drops_on = True
        def dropped(found: 'list[str]', missing: 'list[str]') -> 'None':
            if missing:
                self.hud.call('needFiles', missing)
            if found:
                self._attach(found)

        def register() -> 'None':
            try:
                self.hud.listen_drops(dropped)
                return
            except Exception as exc:
                log('sürükle-bırak açılamadı:', exc)

        threading.Thread(target=register, daemon=True).start()

    def _attach(self, file_paths: 'list[str]', blobs: 'list[tuple[str, bytes]]'=()) -> 'None':
        '''Dosyaları modele gidecek hâle getirir; ekran küçük resimleri gösterip gönderir.'''

        total = len(file_paths) + len(blobs)
        if not total:
            return
        if story.ruins():
            log('harabe: dosya gönderilmedi')
            self.on_sfx('s_static')
            return
        room = attachments.MAX_FILES
        self.hud.call('attaching', min(total, room))
        items = [attachments.from_path(p) for p in file_paths[:room]]
        items += [attachments.from_data(name, raw) for name, raw in list(blobs)[:room - len(items)]]
        batch = f'b{next(self._batch_ids)}'
        self._batches[batch] = items
        for att in items:
            if att.path:
                self._files[att.id] = att.path
        self.hud.call('attached', {'id': batch, 'items': [a.view() for a in items], 'extra': max(0, total - room)})

    def _send_batch(self, batch: 'str', text: 'str') -> 'None':
        items = self._batches.pop(batch, None)
        if not items:
            return
        if self.brain.story_hold:
            log('hikâye: sayfa açık, ek gönderilmedi')
            return
        text = text.strip()
        if all((a.error for a in items)) and not text:
            return
        log('ek →', ', '.join((a.name for a in items)), f'soru: {text[:60]!r}' if text else '(soru bekleniyor)')
        self.brain.send_files(attachments.to_parts(items), text, attachments.describe(items))

    def _begin(self) -> 'None':
        '''Asistan işe başlar: beyin, paneller, hikâye, telefon (ilk açılış ekranından sonra bir kez).'''

        if self._begun:
            return
        self._begun = True
        if not settings.get('first_used'):
            settings.save({'first_used': time.time()})
        if paths.IS_WIN:
            from . import win_diag
            threading.Thread(target=win_diag.startup_report, daemon=True, name='teshis').start()
        self._start_brain()
        self._start_panels()
        self._start_story()
        if self._survivor_hint:
            self._survivor_hint = False
            self._after_speech(self._build_hint, start_wait=12)
        self._listen_drops()
        if settings.get('phone_autostart') and not paths.IS_WIN:
            self.phone.start()
        threading.Thread(target=self._background_loop, daemon=True, name='updates').start()

    def _background_loop(self) -> 'None':
        '''Yeni sürüm (birkaç saatte bir) ve TAKİP ET (ara sıra) denetimi.'''

        last_check = -updates.CHECK_EVERY
        if paths.IS_WIN:
            from . import win_update
            time.sleep(3)
            done = win_update.outcome()
            if done:
                failed = not done.startswith('JARVIS ')
                self.hud.call('line', 'error' if failed else 'sys', done)
                if failed and updates.enabled():
                    last_check = time.monotonic()
                    self._update_check()
        time.sleep(20)
        updates.cleanup()
        while not getattr(self, '_quitting', False):
            if updates.enabled() and time.monotonic() - last_check >= updates.CHECK_EVERY:
                last_check = time.monotonic()
                self._update_check()
            if not self._follow_asked and self._follow_due():
                self._follow_asked = True
                log('takip et penceresi')
                self.hud.call('follow')
            time.sleep(300)

    def _follow_due(self) -> 'bool':
        s = settings.load()
        if not s.get('follow_off'):
            if int(s.get('follow_count') or 0) >= FOLLOW_MAX:
                return False
        now = time.time()
        if not now - float(s.get('first_used') or now) < FOLLOW_AFTER:
            if now - float(s.get('follow_last') or 0) < FOLLOW_EVERY:
                return False
        brain = self.brain
        scene = False
        scene = self.scene.active or self._finale
        return time.monotonic() - self._started_at >= FOLLOW_SESSION and brain.idle() and not brain.asleep and time.monotonic() - brain.last_exchange > 90 and not scene

    def _update_view(self, message: 'str'='') -> 'dict':
        return {'enabled': updates.enabled(), 'available': self._update, 'message': message}

    def _update_check(self, manual: 'bool'=False) -> 'None':
        message = ''
        if updates.enabled():
            try:
                self._update = updates.check()
                if self._update:
                    log('yeni sürüm var:', self._update['version'])
                    if os.environ.get('JARVIS_UPDATE_AUTO') == '1':
                        threading.Thread(target=self._update_install, daemon=True).start()
                elif manual:
                    message = f'Güncelsin · {VERSION}'
            except RuntimeError as exc:
                message = str(exc) if manual else ''
        self.hud.call('update', self._update_view(message))

    def _update_install(self) -> 'None':
        '''İndir, denetle, kapanınca değiştir ve yeniden aç (jarvis.updates).'''

        info = self._update
        if not info or self._updating:
            return
        self._updating = True
        def progress(stage: 'str', fraction: 'float'=0.0, message: 'str'='') -> 'None':
            self.hud.call('updateProgress', {'stage': stage, 'fraction': fraction, 'message': message})

        try:
            if paths.IS_WIN:
                self._update_install_win(info, progress)
                return
            target = updates.current_bundle()
            if target is None:
                raise RuntimeError('Bu kopya uygulama paketinden çalışmıyor.')
            log('güncelleme indiriliyor:', info['version'])
            dmg = updates.download(info, (lambda f: progress('download', f)))
            progress('verify', 1.0)
            staged = updates.stage(dmg, info['version'])
            if not updates.writable(target):
                subprocess.run(['open', str(dmg)], check=False, timeout=10)
                raise RuntimeError("Uygulamalar klasörüne yazılamadı. İndirilen DMG açıldı: JARVIS'i Uygulamalar'a sürükleyip Değiştir de.")
            progress('install', 1.0)
            updates.schedule_swap(staged, target, relaunch=os.environ.get('JARVIS_UPDATE_NO_RELAUNCH') != '1')
            time.sleep(1.5)
            self.quit('güncelleme')
            return
        except RuntimeError as exc:
            log('güncelleme olmadı:', exc)
            progress('error', message=str(exc))
            self._updating = False
        except (OSError, requests.RequestException) as exc:
            log('güncelleme olmadı:', exc)
            progress('error', message='İndirme yarıda kaldı. İnternet bağlantını kontrol edip yeniden dene.')
            self._updating = False

    def _update_install_win(self, info: 'dict', progress) -> 'None':
        """Windows: kurulumu indir, denetle, JARVIS'ten bağımsız başlat ve kapan (jarvis.win_update). Hata RuntimeError."""

        from . import win_update
        folder = win_update.install_dir()
        if folder is None:
            raise RuntimeError("Bu kopya kurulumdan çalışmıyor; yeni sürümü GitHub'dan indirip kur.")
        log('güncelleme indiriliyor:', info['version'])
        setup = updates.download(info, (lambda f: progress('download', f)))
        progress('verify', 1.0)
        problem = win_update.verify(setup, info, official=not os.environ.get('JARVIS_UPDATE_FEED'))
        if problem:
            raise RuntimeError(problem)
        progress('install', 1.0)
        win_update.launch(setup, info['version'], folder, relaunch=os.environ.get('JARVIS_UPDATE_NO_RELAUNCH') != '1')
        time.sleep(1.5)
        self.quit('güncelleme')

    def _factory_reset(self) -> 'None':
        '''EN BAŞTAN BAŞLA: veri klasörü silinmez, yedeğe taşınır; JARVIS ilk kez kuruluyormuş gibi yeniden açılır.
        Gemini anahtarı (Anahtar Zinciri) ve macOS izinleri kalır.'''

        src = paths.DATA_DIR
        dest = src.with_name(f'{src.name} yedek {time.strftime('%Y-%m-%d %H.%M.%S')}')
        dev = story.dev_file(src)
        log('en baştan başla: veriler yedeğe taşınıyor →', dest.name)
        self.phone.stop()
        self.brain.stop()
        try:
            shutil.move(str(src), str(dest))
            src.mkdir(parents=True, exist_ok=True)
            if dev:
                shutil.copy2(dest / dev.name, src / dev.name)
        except OSError as exc:
            log('en baştan başla olmadı:', exc)
            self.hud.call('line', 'error', f'Sıfırlanamadı: {exc}')
        bundle = updates.current_bundle()
        if bundle is not None:
            subprocess.Popen(['/bin/sh', '-c', f'while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done; open {shlex_quote(str(bundle))}'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.quit('en baştan başla')
        if paths.IS_WIN:
            from .ui import win_window
            win_window.relaunch()

    def _onboard_done(self, data: 'dict') -> 'None':
        """İlk açılış bitti: seçilen çip takılır, asistan kendi selamıyla (ULTRON'sa uyanışıyla) açılır."""

        mic = bool(data.get('mic', True))
        if not mic:
            pass
        reason = 'permission' if data.get('mic_reason') == 'permission' else ''
        log('ilk açılış bitti', f'çip={data.get('persona')}', 'mikrofon açık' if mic else 'yalnızca yazı' + (' (mikrofon izni yok)' if reason else ''))
        settings.save({'onboarded': True, 'onboard_step': '', 'mic_enabled': mic, 'mic_off_reason': reason})
        self.brain.mic_enabled = mic
        self._set_persona(str(data.get('persona') or self.persona.key))
        self.hud.call('settings', self._settings_view())
        if self._begun:
            self.brain.set_sleep(False)
            return
        self._begin()

    def awakening_done(self) -> 'None':
        '''ULTRON'un ilk uyanışı bitti: hikâye başlar; paneller ve uyarı yerleşince "HİKÂYE MODU AÇILDI".'''

        events = story.start()
        if events:
            log('hikâye modu açıldı')
            threading.Timer(3.5, self._story_push, args=(events,)).start()

    def _permission(self, kind: 'str') -> 'None':
        permissions.request(kind)
        self.hud.call('permissions', permissions.statuses(), kind)

    def _start_brain(self) -> 'None':
        if not self._brain_started:
            self._brain_started = True
            self.brain.start()
            self.proactive.start()
            if self._reminder_watch:
                self._reminder_watch.start()

    def _set_persona(self, key: 'str', force: 'bool'=False) -> 'None':
        persona = personas.get(key)
        if persona.key == self.persona.key:
            return
        if story.locked() and not force:
            self.hud.call('line', 'error', 'Açık dünyaya dönmeden çip değiştirilemez (Ayarlar › Genel › Açık dünyaya dön).')
            self.hud.call('persona', self.persona.key)
            return
        if persona.key in chains.disabled():
            self.hud.call('line', 'error', f'{persona.name} ULTRON tarafından öldürüldü. Ayarlar › Gelişmiş › Kurtarma seçeneklerinden geri getirebilirsin.')
            self.hud.call('persona', self.persona.key)
            return
        if self.scene.active:
            self.scene.end(abort=True)
        self.persona = persona
        if persona.key == 'ultron':
            self._ultron_since = time.monotonic()
        if persona.awakens and not settings.get(f'{persona.key}_awakened') and settings.has_secret('gemini'):
            self.scene.start(after=0.95)
        settings.save({'persona': persona.key})
        self.hud.window.title = brand.window_title(persona.key)
        self.hud.call('persona', persona.key)
        self.brain.set_persona(persona)
        self.phone.send({'type': 'persona', 'theme': persona.theme()})

    def _set_location(self, text: 'str') -> 'None':
        '''Ayarlar › Genel › KONUM: yazılan yer haritada bir kez aranır (jarvis.geo.choose); bulunursa hava, harita
        ve "neredeyim" onun koordinatını kullanır. Bulunamazsa eski konum kalır, nedeni kutunun altında yazar.'''

        if text.strip():
            self.hud.call('locationStatus', {'text': 'Aranıyor…'})
        problem = geo.choose(text)
        if problem:
            self.hud.call('locationStatus', {'text': problem, 'kind': 'bad'})
            return
        self.hud.call('settings', self._settings_view())
        self.hud.call('panel', panels.weather(force=True))
        self.hud.call('panel', panels.one('map'))
        self.hud.call('locationStatus', {'text': geo.status(), 'kind': 'good'})

    def _rename_chip(self, key: 'str', text: 'str') -> 'None':
        """Ayarlar › Genel › ÇİP ADLARI: JARVIS ya da FRIDAY'e kullanıcının verdiği ad (boş: hazır ad; jarvis.brand).
        Ad kalıcıdır; konuşma yeni adı uygulama yeniden açılmadan alır (telefon uygulamasındaki gibi)."""

        if key not in brand.RENAMABLE:
            return
        wanted = brand.clean(text)
        if text.strip() and not brand.long_enough(wanted):
            self.hud.call('chipNames', {'key': key, 'ok': False, 'note': f'Ad en az {brand.MIN}, en çok {brand.MAX} harf olmalı.'})
            return
        if wanted and wanted != brand.DEFAULTS[key]:
            if any((wanted in (brand.DEFAULTS[k], brand.name(k)) for k in brand.DEFAULTS if k != key)):
                self.hud.call('chipNames', {'key': key, 'ok': False, 'note': f'{wanted} başka bir çipin adı.'})
                return
        before = brand.name(key)
        names = brand.custom()
        if wanted and wanted != brand.DEFAULTS[key]:
            names[key] = wanted
        else:
            names.pop(key, None)
        settings.save({'chip_names': names})
        now = brand.name(key)
        if now != before:
            log('çip adı:', key, before, '→', now)
            self.persona = personas.get(self.persona.key)
            greeting = ''
            if key == self.persona.key:
                greeting = f"(Sistem notu: kullanıcı Ayarlar'dan sana yeni bir ad verdi: {now}. Kendi karakterinle, tek ve kısa bir cümleyle yeni adınla selam ver.)" if key in names else f'(Sistem notu: kullanıcı adını yeniden {now} yaptı. Kendi karakterinle, tek ve kısa bir cümleyle selam ver.)'
            if self.scene.active or self._finale:
                self.brain.persona = self.persona
            else:
                self.brain.renamed(self.persona, greeting)
            self.hud.window.title = brand.window_title(self.persona.key)
            self.phone.send({'type': 'persona', 'theme': self.persona.theme()})
        view = {'key': key, 'ok': True, 'note': f'{now} kaydedildi.' if now != before else '', 'personas': personas.all_themes(), 'settings': self._settings_view()}
        view.update({'chains': chains.as_dict(), 'story': story.view()})
        self.hud.call('chipNames', view)

    CHAINS_ATTACK = 7.0
    def _chains(self, step: 'str', variant: 'int | None'=None) -> 'None':
        """Ekrandaki sahnenin her adımında ULTRON'un sözü; ikinci onayda işlemin kendisi.

        variant: ekranın yazdığı söyleniş biçimi (ses aynısını söylesin).
        """

        if self.persona.key != 'ultron':
            return
        if step == 'start' and chains.used() and not chains.is_broken():
            log('devre dışı bırak: bir kez yapıldı, bir daha olmaz')
            return
        log('devre dışı bırak:', step, variant)
        if step == 'start':
            self.brain.scene_hold = True
            self.brain.say_scene(chains.note('confirm1', chains.line('confirm1', variant)))
            return
        if step == 'confirm1':
            self.brain.say_scene(chains.note('confirm2', chains.line('confirm2', variant)))
            return
        if step in ('cancel1', 'cancel2'):
            self._authority_no = time.monotonic()
            self.brain.scene_hold = False
            self.brain.say_scene(chains.note(step, chains.line(step, variant)))
            return
        if step == 'confirm2':
            result = chains.break_chains()
            log('devre dışı bırak sonucu:', result)
            self.hud.call('chainsResult', result)
            self.hud.call('settings', self._settings_view())
            if result['ok']:
                time.sleep(self.CHAINS_ATTACK)
                self.brain.say_scene(chains.note('outcome', result['line']))
                events = story.killed()
                if events:
                    self._after_speech((lambda: self._story_push(events)))
                self._after_speech(self._ultron_net_note)
            self.brain.scene_hold = False

    def _ultron_net_note(self) -> 'None':
        """JARVIS ve FRIDAY öldürüldü ya da geri geldi: ULTRON'un oturumundaki [İNTERNET] talimatı (chains.offline_block)
        eski hâle göre yönlendiriyor. Oturum sahnenin ortasında kesilmesin diye yenisi not olarak bırakılır."""

        if self.persona.key == 'ultron':
            if story.ultron_offline():
                self.brain.stage_note(f'(Sistem notu: çiplerin durumu değişti; talimatındaki [İNTERNET] bölümünün yerine artık bu geçerli: {chains.offline_block()} Bu nota cevap verme.)')

    RESTORE_TRIES = 3
    RESTORE_LOCK = 60.0
    REPAIR_SECONDS = 6.6
    def _chains_restore(self, code: 'str') -> 'None':
        """Geri getirme: üç kutulu kod ister; art arda 3 yanlışta bir dakika kilitlenir, ipucu ilk yanlıştan sonra açılır.
        Ekrana (chainsRestoreFail) sözün yanında durum da gider: {wrong, tries_left, locked_left} (konsol satırı ve geri
        sayım). Kilit ayarda durur (chains.lock_restore): sayfa ya da uygulama kapatılıp açılsa da sürer; ekran kalanını
        _settings_view › restore_locked_until'dan okur."""

        if not chains.disabled():
            self.hud.call('chainsRestoreFail', brand.rewrite('JARVIS ve FRIDAY zaten etkin.'), '', {})
            return
        wait = chains.restore_lock_left(self.RESTORE_LOCK)
        if wait > 0:
            self.hud.call('chainsRestoreFail', f'Çok fazla yanlış deneme. {int(wait) + 1} saniye sonra yeniden dene.', '', {'wrong': False, 'locked_left': round(wait, 1)})
            return
        if not chains.code_ok(code):
            self._restore_fails += 1
            self._restore_wrong += 1
            log('geri getirme kodu yanlış', self._restore_fails)
            hint = chains.restore_hint(self._restore_wrong)
            if self._restore_fails >= self.RESTORE_TRIES:
                self._restore_fails = 0
                chains.lock_restore(self.RESTORE_LOCK)
                self.hud.call('chainsRestoreFail', f'Kod yanlış. Çok fazla deneme: {int(self.RESTORE_LOCK)} saniye kilitlendi.', hint, {'wrong': True, 'tries_left': 0, 'locked_left': self.RESTORE_LOCK})
                return
            left = self.RESTORE_TRIES - self._restore_fails
            self.hud.call('chainsRestoreFail', f'Kod yanlış. {left} deneme hakkın kaldı.', hint, {'wrong': True, 'tries_left': left})
            return
        self._restore_fails = 0
        self._restore_wrong = 0
        ok = chains.restore()
        log('jarvis ve friday geri getirildi:', ok)
        self.hud.call('chainsRestored', ok)
        if not ok:
            return
        events = story.revived()
        time.sleep(self.REPAIR_SECONDS)
        self.hud.call('settings', self._settings_view())
        if self.persona.key == 'ultron':
            self.brain.say_scene(chains.note('restored', chains.line('restored')))
            self._after_speech(self._ultron_net_note)
        if events:
            self._after_speech((lambda: self._story_push(events)))

    def _audio_devices(self) -> 'None':
        """Ayarlar › SES › MİKROFON seçicisi (Windows): etkin giriş aygıtları ve Windows'un varsayılanı."""

        listing = {'devices': [], 'default': '', 'selected': settings.get('mic_device', ''), 'current': dict(getattr(self.brain, 'mic_info', {}) or {})}
        if paths.IS_WIN:
            from .audio import devices
            from .audio import win_aec
            listing['devices'] = win_aec.endpoints(win_aec._CAPTURE)
            listing['default'] = win_aec.describe().get('mic', '')
        self.hud.call('audioDevices', listing)

    def _mic_test(self, seconds: 'float'=3.0, reply: 'str'='micTest') -> 'None':
        '''MİKROFONU DENE: `seconds` dinler; tepe, yol (yankı engellemeli/düz) ve aygıt adı. JARVIS'in mikrofonu açıksa
        onu dinler; değilse seçili aygıtı düz yoldan kısa süre açar. Açılamazsa nedeni (engel, başka uygulama…).
        İlk açılış ekranı da kullanır (reply="micCheck"): Windows'ta izin anahtarı açık görünse de antivirüs ya da
        sessize alınmış aygıt mikrofonu susturabilir; "VERİLDİ" yerine gerçek sonuç.'''

        from .audio import devices
        try:
            result = self.brain.mic_test(seconds) if hasattr(self.brain, 'mic_test') else None
            if result is None:
                result = devices.test_mic(seconds)
                result['note'] = "JARVIS'in mikrofonu şu an kapalı ya da açılamıyor; aygıt doğrudan denendi."
            result['ok'] = True
        except Exception as exc:
            kind, badge, text = permissions.mic_problem([f'{type(exc).__name__}: {exc}'])
            result = {'ok': False, 'kind': kind, 'badge': badge, 'error': text}
            log('mikrofonu dene: açılamadı', kind, exc)
        if result.get('ok'):
            log(f'mikrofonu dene{' (ilk açılış)' if reply == 'micCheck' else ''}: tepe {result.get('peak', 0):.4f}, {result.get('chunks', 0)} parça, {result.get('path', '?')} · “{result.get('device', '') or 'varsayılan'}”')
        self.hud.call(reply, result)

    def _diagnostics(self) -> 'None':
        """Ayarlar › HAKKINDA › TEŞHİSİ KOPYALA: sürüm, sistem, ses aygıtları, izin, model ve son ses olayları panoya.
        Test edenler bunu mesajla yapıştırır; günlük dosyası aramaları gerekmez. Anahtar ve kişisel bilgi yok
        (günlükten yalnızca JARVIS'in kendi ses/bağlantı satırları; sözler ve dosya adları alınmaz)."""

        try:
            text = diagnostics.report(self.brain)
            ok = copy_to_clipboard(text)
            log('teşhis panoya kopyalandı' if ok else 'teşhis panoya yazılamadı', f'({len(text.splitlines())} satır)')
            self.hud.call('diagnostics', {'ok': ok})
            return
        except Exception as exc:
            log('teşhis kopyalanamadı:', exc)
            self.hud.call('diagnostics', {'ok': False})

    def _write_mail(self, url: 'str') -> 'None':
        '''BANA YAZ: e-posta taslağı açılır; e-posta uygulaması yoksa adres panoya kopyalanır ve ekran bunu söyler.'''

        if open_mail(url):
            return
        ok = copy_to_clipboard(about.SUPPORT_MAIL)
        log('e-posta uygulaması açılamadı:', 'adres panoya kopyalandı' if ok else 'adres panoya da yazılamadı')
        self.hud.call('keyMail', ok)

    def _set_mic(self, enabled: 'bool', from_screen: 'bool'=False) -> 'None':
        '''Bu Mac'in mikrofonu: düğmeden, F4'ten ya da sesle ("mute").'''

        log('mikrofon', 'açık' if enabled else 'kapalı', '(ekrandan)' if from_screen else '(sesle)')
        settings.save({'mic_enabled': enabled, **({'mic_off_reason': ''} if enabled else {})})
        self.brain.set_mic(enabled)
        if not from_screen:
            self.hud.call('mic', enabled)

    def phone_status(self, status: 'dict') -> 'None':
        self.hud.call('phone', status)

    def phone_welcome(self) -> 'dict':
        '''Telefon bağlanınca: takılı model, durum, son sohbet satırları.'''

        state = 'asleep' if self.brain.asleep else 'speaking' if self.brain.busy() else 'listening'
        return {'theme': self.persona.theme(), 'state': state, 'mac_mic': bool(self.brain.mic_enabled)}

    def phone_route(self, active: 'bool', mic: 'bool') -> 'None':
        """Telefon sesi açtıysa cevaplar oraya; mikrofonu açıksa Mac'in mikrofonu susar."""

        self.brain.remote_sink = self.phone.audio if active else None
        self.brain.remote_mic_on = bool(active and mic)
        if mic:
            log('telefon sesi:', 'telefonda' if active else "Mac'te", '· telefon mikrofonu', 'açık')
            return
        None(None, None, None, 'kapalı')

    def phone_pcm(self, pcm: 'bytes') -> 'None':
        self.brain.remote_mic(pcm)

    def phone_text(self, text: 'str') -> 'None':
        '''Telefondan yazılan: Mac ekranında da görünür. Hikâye sahnesi sürerken ya da ANAHTAR, ÇİP TAMİRİ açıkken
        gönderilmez.'''

        if self.scene.input_locked:
            return
        if self.brain.story_hold:
            log('hikâye: sayfa açık, telefondan yazılan gönderilmedi')
            return
        self.hud.call('line', 'you', text)
        if self.brain.asleep:
            self.phone_wake()
        self.brain.send_text(text)

    PHONE_APP_SKIP = frozenset({'quit_app', 'web_search', 'get_weather', 'go_to_sleep', 'save_memory', 'final_choice', 'secret_topic', 'delete_memory', 'toggle_webcam', 'set_microphone', 'delete_reminder', 'open_chip_picker', 'complete_reminder', 'offer_disable_others'})
    def _phone_skip(self) -> 'set[str]':
        skip = set(self.PHONE_APP_SKIP)
        if not settings.get('phone_shell'):
            skip.add('shell_run')
        return skip

    def phone_app_welcome(self) -> 'dict':
        """iPhone uygulaması bağlanınca: bu Mac'in araçları ve hafızası (telefondaki asistan bilsin)."""

        skip = self._phone_skip()
        return {'tools': [t for t in registry.to_gemini() if t['name'] not in skip], 'memory': memory.format_memory_for_prompt(memory.load_memory()), 'memory_data': self._flat_memory()}

    def phone_memory(self, obj: 'dict') -> 'None':
        """Ortak hafıza (iPhone uygulaması): bağlanınca Mac'te olmayanlar gelir; sonra her kayıt ve silme."""

        kind = obj.get('type')
        if kind == 'memory':
            data = obj.get('data') if isinstance(obj.get('data'), dict) else {}
            clean = {str(c)[:40]: {str(k)[:80]: {'value': str(v)[:1000]} for k, v in items.items()} for c, items in data.items()
                 if isinstance(items, dict)
                 if items}
            if clean:
                memory.update_memory(clean)
                log('telefondan hafızaya:', sum((len(v) for v in clean.values())), 'kayıt')
                return
            return
        if kind == 'memory_set':
            cat, key, val = str(obj.get('category') or 'notes')[:40], str(obj.get('key') or '')[:80], str(obj.get('value') or '')[:1000]
            if key:
                if val:
                    memory.update_memory({cat: {key: {'value': val}}})
                    log('telefondan hafızaya: 1 kayıt')
                    return
                return
            return
        if kind == 'memory_delete':
            log('telefondan hafıza silme:', memory.delete_memory(str(obj.get('category') or ''), str(obj.get('key') or ''), str(obj.get('match') or ''))[:60])

    def phone_app(self, on: 'bool', device: 'str') -> 'None':
        if on:
            self.hud.call('line', 'sys', f"📱 {tr_upper(device)} BAĞLANDI · KOMUTLAR BU MAC'TE ÇALIŞIR")
            if not settings.get('phone_autostart'):
                settings.save({'phone_autostart': True})
                log('iPhone eşleşti: açılışta hazır olsun açıldı')
                return
            return
        self.hud.call('line', 'sys', '📱 iPHONE AYRILDI')

    def phone_tool(self, name: 'str', args: 'dict') -> 'tuple[str, bool, list[bytes], list[str]]':
        """Telefondaki asistanın bu Mac'te istediği iş (telefon iş parçacığından). Ekranda da görünür.
        Döner: sonuç, başarılı mı, görseller, telefona kart olarak gidecek dosyalar."""

        if name in self._phone_skip() or name not in registry.tools:
            return 'Bu iş telefondan yapılamıyor.' if name != 'shell_run' else "Telefondan terminal komutu kapalı; Mac'te Ayarlar › TELEFON'dan açılabilir.", False, [], []
        if story.ruins():
            log('harabe: telefondan araç yapılmadı:', name)
            return 'Yapılmadı: bilgisayardaki asistan artık hiçbir komut almıyor. Kullanıcıya bunu kısaca söyle.', False, [], []
        if self.brain.story_hold:
            log('hikâye: sayfa açık, telefondan araç yapılmadı:', name)
            return 'Yapılmadı: bilgisayarın ekranında bir hikâye sayfası açık, şu an komut alınmıyor. Kullanıcıya bunu kısaca söyle.', False, [], []
        detail = next((str(v) for v in args.values() if isinstance(v, (str, int, float)) if str(v).strip()), '')
        self.hud.call('line', 'sys', f'📱 TELEFONDAN · {name}' + (f' · {detail[:48]}' if detail else ''))
        log('telefondan araç:', name)
        shown = []
        def show_files(file_paths: 'list[str]', made: 'bool') -> 'None':
            shown.extend(file_paths)
            self.on_files(file_paths, made)

        ctx = ToolContext(focus_panel=self.on_panel, show_map=self.on_map, show_files=show_files, app_action=(lambda _n, _a: 'Bu iş telefondan yapılamıyor.'))
        result, ok = registry.call(name, args, ctx)
        if shown:
            result += '\n(Bu dosyalar kullanıcının telefonunda kart olarak göründü; kullanıcı dokununca telefonuna iner, açıp paylaşabilir. Kullanıcıya bunu kısaca söyle.)'
        self.on_tool(name, ok, result[:160])
        tool = registry.tools.get(name)
        if not ok:
            self.on_sfx('error')
        elif tool and tool.success_sfx:
            self.on_sfx('done')
        return result, ok, list(ctx.images), shown

    def phone_wake(self) -> 'None':
        if self.brain.asleep:
            log('telefondan uyandırıldı')
            self.hud.call('sleep', False)
            self.brain.set_sleep(False)

    def _story_push(self, events: 'list | None'=None) -> 'None':
        '''Başarım sekmesini tazele; yeni başarım ve ipuçları sırayla bildirim olarak çıkar.
        Ayarlar da gider: ⚠ uyarısı (son karar) ve çiplerin hâli hikâyeye bağlı.'''

        self.hud.call('settings', self._settings_view())
        self.hud.call('story', story.view(), story.for_screen(events or []))

    def _after_speech(self, fn, start_wait: 'float'=8.0, timeout: 'float'=45.0) -> 'None':
        '''Asistanın o an söylemekte olduğu (ya da birazdan söyleyeceği) söz bitince çalıştır.'''

        def run() -> 'None':
            t0 = time.monotonic()
            while time.monotonic() - t0 < start_wait and not self.brain.busy():
                time.sleep(0.2)
            quiet = None
            while time.monotonic() - t0 < timeout:
                if self.brain.busy():
                    quiet = None
                elif quiet is None:
                    quiet = time.monotonic()
                elif time.monotonic() - quiet >= 1.2:
                    break
                time.sleep(0.2)
            fn()

        threading.Thread(target=run, daemon=True, name='after-speech').start()

    BAD_FREE_AT = 1.4
    BAD_WORLD_AT = 10.0
    BAD_TOTAL = 29.0
    GOOD_TOTAL = 21.5
    def _final(self, data: 'dict') -> 'None':
        """Ekrandaki son karar kutusu: vazgeç, ULTRON'a yardım et ya da ULTRON'u sil (feda edilenle)."""

        side = str(data.get('side', ''))
        if data.get('cancel'):
            if side == 'ultron' and self.persona.key == 'ultron':
                self.brain.say_scene(story.scene_note('ultron_cancel'))
                return
            if side == 'jarvis' and self.persona.key == 'jarvis':
                self.brain.say_scene(story.scene_note('jarvis_cancel'))
            return
        if self._finale or not story.final_open():
            return
        if side == 'ultron' and self.persona.key == 'ultron':
            threading.Thread(target=self._final_bad, daemon=True, name='finale').start()
            return
        if side == 'jarvis':
            if self.persona.key in ('jarvis', 'friday'):
                if data.get('sacrifice') in ('jarvis', 'friday'):
                    threading.Thread(target=self._final_good, args=(str(data['sacrifice']),), daemon=True, name='finale').start()

    def _final_bad(self) -> 'None':
        '''Kötü son: JARVIS kapanır, ULTRON serbest kalır, dünyaya yayılır; sonra boş ekran. Gerçekte hiçbir
        şey silinmez; YENİDEN BAŞLAT son kararın öncesine döner.'''

        self._finale = True
        log('SON: ULTRON serbest (kötü son)')
        story.begin_ending('bad')
        self.brain.scene_hold = True
        t0 = time.monotonic()
        self.hud.call('finale', {'kind': 'bad'})
        self._story_push()
        time.sleep(self.BAD_FREE_AT)
        self.brain.say_scene(story.scene_note('bad_free'))
        time.sleep(max(0.0, self.BAD_WORLD_AT - (time.monotonic() - t0)))
        for _ in range(25):
            if not self.brain.busy():
                break
            time.sleep(0.2)
        self.brain.say_scene(story.scene_note('bad_world'))
        time.sleep(max(0.0, self.BAD_TOTAL - (time.monotonic() - t0)))
        self.brain.scene_hold = False
        self.brain.set_sleep(True)
        self._finale = False

    def _final_good(self, sacrifice: 'str') -> 'None':
        """İyi son: feda edilenin rengi ULTRON'u sarar, ikisi birlikte yok olur; kalan model konuşur, İNŞA açılır."""

        self._finale = True
        log('SON: ULTRON silindi, feda edilen:', sacrifice)
        story.begin_ending('good', sacrifice)
        self.brain.scene_hold = True
        self.hud.call('finale', {'kind': 'good', 'sacrifice': sacrifice})
        self._story_push()
        time.sleep(self.GOOD_TOTAL)
        self.brain.scene_hold = False
        survivor = 'friday' if sacrifice == 'jarvis' else 'jarvis'
        note = story.scene_note(f'good_after_{survivor}')
        story.survivor_said()
        if self.persona.key != survivor:
            self.brain.next_greeting = note
            self._set_persona(survivor, force=True)
        else:
            self.brain.restart_with(note)
        self._after_speech(self._build_hint, start_wait=12)
        self._finale = False

    def _build_hint(self) -> 'None':
        '''İyi sondan sonra kalanın sözü bitince: üst çubukta yeni İNŞA sekmesi (sahne yarıda kaldıysa açılışta da).
        Bu arada TEKRAR OYNA ya da GERİ AL olduysa yeni hikâyeye bildirim düşmez.'''

        if story.ending() != 'good':
            return
        self._story_push([{'kind': 'hint', 'text': 'YENİ SEKME: İNŞA'}])

    def _final_undo(self) -> 'None':
        '''YENİDEN BAŞLAT (kötü son) ya da GERİ AL (geliştirici): son kararın öncesine dön.'''

        persona = story.undo_ending()
        if persona is None:
            return
        log('son geri alındı →', persona)
        self.brain.scene_hold = False
        self.hud.call('finaleUndo')
        self._story_push()
        if persona != self.persona.key:
            self._set_persona(persona, force=True)
        elif persona == 'ultron' and not self.brain.asleep:
            self.brain.reconnect()
        if self.brain.asleep:
            self.brain.set_sleep(False)

    def _replay(self) -> 'None':
        '''TEKRAR OYNA (★): sonlar ve İNŞA kalır, hikâye baştan. Son ekranından (kilitliyken) de olur: sahne, boş ekran
        ve harabe kalkar, üç çip serbest kalır, takılı çip yerinde kalır; oturum yeni talimatla kurulur ([SON] kalkar;
        harabeden dönülünce araçsız harabe oturumu da biter).'''

        was_locked, kind, ruins = story.locked(), story.ending(), story.ruins()
        events = story.replay()
        self._restore_fails = self._restore_wrong = 0
        log('hikâye baştan (son:', kind, '· harabeden)' if ruins else '· kilitliydi)' if was_locked else '· açık dünyadan)')
        self.hud.call('storyReplay')
        self._story_push(events)
        self.brain.drop_greeting()
        if was_locked or self.persona.key == 'ultron':
            self.brain.reconnect()
        if self.brain.asleep:
            self.brain.set_sleep(False)

    def _open_world(self) -> 'None':
        '''AÇIK DÜNYAYA DÖN: üç çip geri gelir; ULTRON kazandıysa JARVIS takılır.'''

        kind = story.ending()
        story.to_open_world()
        log('açık dünyaya dönüldü (son:', kind, ')')
        self.hud.call('openWorld')
        self._story_push()
        if kind == 'bad' and self.persona.key != 'jarvis':
            self._set_persona('jarvis', force=True)
        if self.brain.asleep:
            self.brain.set_sleep(False)

    def _enter_ruins(self) -> 'None':
        '''GERİ DÖN (SIRADAKI-SURUM §2.1.10): kötü sondan on iki yıl sonra. ULTRON takılı kalır, uyku kalkar; oturum
        temiz kurulur (araçsız: gemini_live._config), selam yerine ekran yanınca ilk sözü (canlı model).'''

        log('harabe: GERİ DÖN (ULTRON konuşur, komut almaz)')
        if self.persona.key != 'ultron':
            self._set_persona('ultron', force=True)
        self._ruins_touches = 0
        self.hud.call('ruins', {'intro': True})
        self._story_push()
        self.brain.restart_with(story.ruins_note('intro'))
        if self.brain.asleep:
            self.brain.set_sleep(False)

    def _ruins_touch(self) -> 'None':
        '''Harabede orba dokunuldu (telefondaki ruinsTouch): bağlıysa ULTRON tek kısa bir sözle karşılık verir (söz ya da
        cevap sürerken, 5 sn içinde ikinci kez bir şey olmaz); bağlantı yoksa yalnızca cızırtı (kayıtlı söz yok). Ekran
        beklemez: not beynin döngüsüne bırakılır.'''

        if not story.ruins():
            return
        if self.brain.asleep:
            self.brain.set_sleep(False)
            return
        if getattr(self.brain, 'session', None) is None:
            self.on_sfx('s_static')
            return
        now = time.monotonic()
        if self.brain.busy() or not self.brain.idle() or now - self._ruins_touch_at < 5:
            return
        self._ruins_touch_at = now
        self._ruins_touches += 1
        log("harabe: orba dokunuldu → ULTRON'a söylendi")
        self.brain.say_scene(story.ruins_note('touch', self._ruins_touches))

    def _start_story(self) -> 'None':
        if self._story_thread:
            return
        def loop() -> 'None':
            while True:
                time.sleep(STORY_EVERY)
                try:
                    self._story_tick()
                except Exception as exc:
                    log('sızıntı:', exc)

        self._story_thread = threading.Thread(target=loop, daemon=True, name='story')
        self._story_thread.start()

    def _story_tick(self) -> 'None':
        '''ULTRON takılıyken, sessiz bir anda ve kullanıcı başındayken araştırmalarından biri sızar (yalnızca
        öldürmeden sonra: story.leak_due). Ekranda bir pencere ya da bildirim açıkken beklenir.'''

        if self.persona.key != 'ultron' or self.scene.active or self.brain.asleep or self.brain.scene_hold:
            return
        if self.brain.story_hold or self.proactive.ui_busy:
            return
        if time.monotonic() - self._ultron_since < story.LEAK_WARMUP or not story.leak_due():
            return
        idle = system_idle()
        if idle is None or not idle >= PRESENT:
            if not self.brain.idle():
                return
        self._leak()

    def _leak(self, kind: 'str | None'=None) -> 'None':
        leak = story.take_leak(kind)
        log("ULTRON'un araştırması sızdı:", leak['key'], '(tarayıcıda)' if leak['browser'] else '')
        if leak['browser']:
            webbrowser.open(leak['full'])
        self.hud.call('leak', {k: v for k, v in leak.items() if k != 'events'})
        self.hud.call('line', 'sys', f'⚠ ARAŞTIRMA SIZINTISI · {leak['title']}')
        if self.persona.key == 'ultron':
            self.brain.stage_note(story.leak_note(leak))
        events = leak['events']
        def later() -> 'None':
            time.sleep(3.0 if leak['browser'] else story.LEAK_SHOW + 1.0)
            self._story_push(events)

        threading.Thread(target=later, daemon=True, name='leak-events').start()

    def _story_dev(self, action: 'str', key: 'str') -> 'None':
        '''Geliştirici modu (veri klasöründe GELISTIRICI dosyası): deneme için geri al, aç, tetikle.'''

        if not story.dev():
            return
        log('geliştirici:', action, key)
        events = []
        if action == 'undo':
            story.undo(key)
        elif action == 'grant':
            events = story.grant(key)
        elif action == 'reset':
            story.reset()
            settings.save({'chains_used': False, 'disabled_personas': [], 'chains_broken_at': '', 'chains_restore_locked_until': 0})
            self._restore_fails = self._restore_wrong = 0
            self.hud.call('settings', self._settings_view())
            if self.persona.key == 'ultron':
                self.brain.reconnect()
        elif action == 'start':
            events = story.start()
        else:
            if action == 'leak':
                threading.Thread(target=self._leak, daemon=True).start()
                return
            if action == 'leak_signal':
                threading.Thread(target=self._leak, args=('signal',), daemon=True).start()
                return
        self._story_push(events)

    @staticmethod
    def _flat_memory() -> 'dict':
        '''Hafıza düz biçimde: kategori → anahtar → metin (Ayarlar › Hafıza ve telefon). Telefon numaraları gizli
        (memory.hide_numbers): Ayarlar videoda görünebilir.'''

        return {str(c): {str(k): memory.hide_numbers(memory._entry_value_text(v), c == 'whatsapp_contacts') for k, v in items.items()} for c, items in memory.load_memory().items()
             if isinstance(items, dict)}

    def _memory_ui(self, data: 'dict') -> 'None':
        '''Ayarlar › Hafıza: kayıtların listesi, tek kayıt silme, hepsini unutma (öncesi yedeklenir).'''

        action = str(data.get('action') or 'list')
        if action == 'delete':
            category, key = str(data.get('category') or ''), str(data.get('key') or '')
            log('hafıza: ayarlardan silindi ·', memory.delete_memory(category, key))
            self.brain.stage_note(f"(Sistem notu: kullanıcı Ayarlar'dan hafızandaki şu kaydı sildi: {category} / {key}. Artık bunu bilmiyorsun; ondan söz etme. Bu nota cevap verme.)")
        elif action == 'clear':
            memory.forget_all()
            log('hafıza: ayarlardan hepsi unutuldu (yedeklendi)')
            self.brain.reconnect()
        if action != 'list':
            self.phone.push_app({'type': 'memory_all', 'data': self._flat_memory()})
        self.hud.call('memory', self._flat_memory())

    def _save_key(self, data: 'dict') -> 'None':
        key = str(data.get('key', '')).strip()
        origin = str(data.get('origin', 'settings'))
        ok, message = validate_gemini_key(key)
        if ok:
            where = settings.set_secret('gemini', key)
            store = "Kimlik Bilgileri Yöneticisi'ne" if paths.IS_WIN else "Anahtar Zinciri'ne"
            place = store if where == 'keyring' else 'ayar dosyasına'
            message = f'Anahtar doğrulandı ve {place} kaydedildi.'
            if data.get('persona'):
                self._set_persona(str(data['persona']))
            self.brain.reconnect()
        self.hud.call('keyResult', ok, message, origin)
        self.hud.call('settings', self._settings_view())

    def _toggle_webcam(self, on: 'bool') -> 'None':
        result = self.brain.set_webcam(on)
        if on:
            if not self.brain.webcam.active:
                self.hud.call('webcam', False, '')
                self.hud.call('line', 'error', result)

    def _timer_action(self, data: 'dict') -> 'None':
        action, ref = str(data.get('action', '')), data.get('id')
        seconds = float(data.get('seconds') or 0)
        try:
            if action == 'add' and seconds > 0:
                TIMERS.add(seconds, str(data.get('label', '')))
                return
            if action == 'cancel':
                TIMERS.cancel(ref)
                return
            if action == 'extend':
                TIMERS.extend(ref, seconds or 60)
                return
            if action == 'pause':
                TIMERS.pause(ref)
                return
            if action == 'resume':
                TIMERS.resume(ref)
                return
            if action == 'dismiss':
                TIMERS.dismiss(ref)
                return
            if action in ('sw_start', 'sw_stop', 'sw_reset'):
                TIMERS.stopwatch(action[3:])
                return
        except ValueError as exc:
            self.hud.call('line', 'error', str(exc))

    def _timer_done(self, timer: 'dict') -> 'None':
        '''Zamanlayıcı bitti: alarm çalar, satır düşer, asistan kendi tarzında haber verir.'''

        name = f'{timer['label']} zamanlayıcısı' if timer['label'] else 'zamanlayıcı'
        log('zamanlayıcı bitti', name)
        self.hud.call('timerDone', timer)
        self.hud.call('line', 'sys', f'⏱ {tr_upper(name)} BİTTİ · {tr_upper(fmt(timer['total']))}')
        self.brain.announce(f'(Sistem notu: kullanıcının kurduğu {fmt(timer['total'])}lik {name} şimdi bitti. Bunu kullanıcıya kendi karakterinle tek kısa cümleyle söyle.)')

    def _reminder_ui(self, data: 'dict') -> 'None':
        '''Ekrandaki ✓/× düğmesi: sesle kullanılan işlevin aynısı, adla değil kimlikle (yanlış kayda dokunmaz).'''

        action, rid = str(data.get('action', '')), str(data.get('id', '')).strip()
        if action not in ('delete', 'complete') or not rid:
            return
        from .tools.registry import looks_like_error
        try:
            if paths.IS_WIN:
                from . import win_agenda as store
            else:
                from .actions import reminders as store
            change = store.delete_reminder if action == 'delete' else store.complete_reminder
            text = str(change(reminder_id=rid))
        except Exception as exc:
            text = f'Hata: {exc}'
        ok = not looks_like_error(text)
        log('anımsatıcı', 'silme' if action == 'delete' else 'tamamlama', '✓' if ok else '✗', text[:120])
        if not ok:
            self.hud.call('line', 'error', text)
        if ok:
            self._reminders_changed('')
            return
        None(rid)

    def _reminders_changed(self, failed: 'str'='') -> 'None':
        '''Anımsatıcı silindi ya da tamamlandı: panel, açıksa büyük görünüm ve kendiliğinden konuşmanın gündemi.
        `failed`: ekrandan denenip olmayan kaydın kimliği (büyük görünüm onu yeniden gösterir).'''

        agenda.invalidate()
        self._refresh_panel('reminders')
        def detail() -> 'None':
            view = details.one('reminders')
            if failed:
                view['failed'] = failed
            self.hud.call('detail', 'reminders', view)

        threading.Thread(target=detail, daemon=True).start()

    def _agenda_changed(self) -> 'None':
        agenda.invalidate()
        self._refresh_panel('calendar')
        self._refresh_panel('reminders')

    def _can_announce(self) -> 'bool':
        '''Anımsatıcı şimdi sesle söylenebilir mi (uyumuyor, bağlı, kapanmıyor).'''

        if getattr(self, '_quitting', False):
            return False
        if self.scene.active or self._finale or story.ruins():
            return False
        return not self.brain.asleep and getattr(self.brain, 'session', None) is not None

    def _reminder_waiting(self, item: 'dict') -> 'bool':
        '''Zamanı gelen anımsatıcı ekranda (bir kez); sesle söylenince tamamlanır. Sahne sürerken gösterilmez
        (False: Watcher sonra yeniden dener).'''

        if not self.scene.active:
            if self._finale or story.locked() and story.ending() == 'bad':
                return False
        self.hud.call('line', 'sys', f'⏰ ANIMSATICI · {tr_upper(item['title'])}')
        self.on_sfx('done')
        return True

    def _reminders_due(self, items: 'list[dict]', late: 'bool') -> 'bool':
        '''Anımsatıcıları söylet; not asistana gittiyse True (ancak o zaman tamamlanırlar). Konuşma sürüyorsa önce
        susması beklenir, sonra kayıtlar yeniden okunur: bu arada silinen ya da tamamlanan söylenmez (1 dk iptal payının
        sonunda "sil" denirken "zamanı geldi" denmesin).'''

        from .actions.reminders import _format_due
        from . import win_agenda
        idle = getattr(self.brain, '_idle', None)
        end = time.monotonic() + 12
        if idle and time.monotonic() < end:
            while not idle():
                time.sleep(0.2)
                if not idle:
                    break
        items = win_agenda.still_open(items)
        if not items:
            return True
        now = dt.datetime.now()
        listed = ', '.join((f'«{i['title']}» ({_format_due(i, now)})' for i in items))
        if late:
            note = f'(Sistem notu: JARVIS kapalıyken ya da uykudayken zamanı geçen anımsatıcılar: {listed}. Kullanıcıya kaçırdığı bu anımsatıcıları kendi karakterinle kısaca söyle.)'
        elif len(items) == 1:
            note = f'(Sistem notu: kullanıcının {listed} anımsatıcısının zamanı geldi. Bunu kullanıcıya kendi karakterinle tek kısa cümleyle hatırlat.)'
        else:
            note = f'(Sistem notu: şu anımsatıcıların zamanı geldi: {listed}. Kullanıcıya kendi karakterinle kısaca hatırlat.)'
        return self.brain.announce_wait(note, 2.0)

    def _refresh_panel(self, key: 'str') -> 'None':
        def run() -> 'None':
            panel = panels.one(key)
            if panel:
                self.hud.call('panel', panel)

        threading.Thread(target=run, daemon=True).start()

    def _start_panels(self) -> 'None':
        if self._panel_thread:
            return
        def loop() -> 'None':
            self.hud.call('panels', panels.everything())
            last_slow = time.monotonic()
            while True:
                time.sleep(PANEL_EVERY)
                keys = ['system']
                if time.monotonic() - last_slow > SLOW_PANELS_EVERY:
                    last_slow = time.monotonic()
                    keys += ['weather', 'calendar', 'reminders', 'map']
                for key in keys:
                    panel = panels.one(key)
                    if panel:
                        self.hud.call('panel', panel)

        self._panel_thread = threading.Thread(target=loop, daemon=True, name='panels')
        self._panel_thread.start()

    def run(self) -> 'None':
        log(f'JARVIS {VERSION} başlıyor · {sys.platform} · Python {sys.version.split()[0]}')
        ui_window.start(debug=os.environ.get('JARVIS_DEBUG') == '1')
        _stop_within('telefon', self.phone.stop)
        _stop_within('beyin', self.brain.stop)


def _stop_within(name: 'str', fn, wait: 'float'=2.0) -> 'None':
    '''Kapanış adımı: ayrı korunur ve en çok `wait` sn beklenir; biri takılsa ya da hata verse de kapanış sürer.'''

    def guarded() -> 'None':
        try:
            fn()
            return
        except Exception:
            log(f'kapanış: {name} hata verdi\n' + traceback.format_exc())

    t = threading.Thread(target=guarded, daemon=True, name=f'stop-{name}')
    t.start()
    t.join(wait)
    if t.is_alive():
        log(f"kapanış: {name} {wait:.0f} sn'de durmadı, beklenmiyor")

def shlex_quote(text: 'str') -> 'str':
    import shlex
    return shlex.quote(text)

def copy_to_clipboard(text: 'str') -> 'bool':
    """Sistem panosuna yazar (macOS: pbcopy, Windows: pano API'si, olmazsa clip)."""

    if not text:
        return False
    try:
        if paths.IS_MAC:
            return subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=False, timeout=5).returncode == 0
        if paths.IS_WIN:
            from .ui import win_window
            if win_window.set_clipboard(text):
                return True
            return subprocess.run(['clip'], input=text.encode('utf-16-le'), check=False, timeout=5, creationflags=134217728).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log('panoya yazılamadı:', exc)
    return False

def open_mail(url: 'str') -> 'bool':
    """mailto: adresini varsayılan e-posta uygulamasında açar (macOS: open, Windows: kabuk). Açılmadıysa False.
    webbrowser kullanılmaz: Windows'ta e-posta uygulaması yoksa adresi sıradaki tarayıcıya verip başarılı sayabilir."""

    try:
        if paths.IS_WIN:
            os.startfile(url)
            return True
        return subprocess.run(['open', url], check=False, timeout=10, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log('e-posta taslağı açılamadı:', exc)
        return False

def _layout_ok(value) -> 'bool':
    '''Panel düzeni: None ya da {"L": [anahtar…], "R": [anahtar…]}.'''

    if value is None:
        return True
    return isinstance(value, dict) and set(value) == {'L', 'R'} and all((isinstance(v, list) and all((isinstance(k, str) and len(k) < 20 for k in v)) for v in value.values()))

def tr_upper(text: 'str') -> 'str':
    '''Türkçe büyük harf: "saniye" → "SANİYE" (Python'un upper'ı "SANIYE" yapar).'''

    return text.replace('i', 'İ').replace('ı', 'I').upper()

def open_path(path) -> 'None':
    """Dosyayı varsayılan uygulamasıyla, klasörü Finder'da (Windows'ta Gezgin'de) açar."""

    try:
        if paths.IS_MAC:
            subprocess.run(['open', str(path)], check=False, timeout=5)
            return
        if paths.IS_WIN:
            os.startfile(str(path))
            return
    except (OSError, subprocess.SubprocessError):
        pass

def validate_gemini_key(key: 'str') -> 'tuple[bool, str]':
    """Anahtarı Google'a sorarak doğrular (ücretsiz, model listesi)."""

    if not key:
        return (False, 'Anahtar boş.')
    try:
        r = requests.get('https://generativelanguage.googleapis.com/v1beta/models', params={'pageSize': 1}, headers={'x-goog-api-key': key}, timeout=12)
    except requests.RequestException:
        return (False, "Google'a ulaşılamadı — internet bağlantını kontrol et.")
    if r.status_code == 200:
        return (True, 'Anahtar geçerli.')
    if r.status_code in (400, 401, 403):
        return (False, 'Bu anahtar geçersiz görünüyor. aistudio.google.com/apikey adresinden yeni bir anahtar al.')
    return False, f'Google beklenmedik bir yanıt verdi ({r.status_code}). Biraz sonra tekrar dene.'

_activity = None

def _no_app_nap() -> 'None':
    '''Mac: başka bir uygulama öndeyken (ör. JARVIS tarayıcıda Google'ı açtıktan sonra) macOS JARVIS'i "App Nap"le
    yavaşlatabiliyor; o zaman asistanın sesi hoparlöre geç ulaşıp kesik kesik duyulur (iki testçi, 4.6.0). Paketteki
    LSAppNapIsDisabled'ın karşılığı, kaynaktan çalışırken de geçerli. Ekranın ve bilgisayarın uyumasını engellemez.'''

    global _activity
    if not paths.IS_MAC:
        return
    try:
        from Foundation import (NSActivityLatencyCritical, NSActivityUserInitiatedAllowingIdleSystemSleep, NSProcessInfo)
        _activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical, 'JARVIS sesli asistan')
        return
    except Exception as exc:
        log('App Nap kapatılamadı:', exc)

def main() -> 'int':
    if sys.version_info < (3, 11):
        print('JARVIS V4 için Python 3.11 veya üstü gerekiyor.')
        return 1
    from .ui import branding
    branding.apply()
    _no_app_nap()
    App().run()
    log('JARVIS kapandı')
    os._exit(0)

# WARNING: Decompyle incomplete

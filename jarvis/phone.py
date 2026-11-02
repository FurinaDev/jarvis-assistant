'''Telefon: JARVIS'e telefondan bağlan (V3'teki telefonun V4 hâli).

Telefon, bu Mac'teki JARVIS'in uzaktan kulaklığı ve kumandasıdır: aynı konuşma,
aynı model (JARVIS/FRIDAY/ULTRON), aynı hafıza; araçlar Mac'te çalışır. Telefondan
söylenen de Mac ekranındaki sohbette görünür.

- Sunucu uygulamanın içindedir (yalnızca `websockets`): telefon sayfası
  (jarvis/ui/phone/) ve ses/yazı için tek bir WebSocket.
- Her yerden bağlanmak için Cloudflare'ın hızlı tüneli (`cloudflared`) kullanılır:
  geçerli HTTPS (telefon tarayıcısı mikrofonu yalnızca güvenli adreste açar), hesap
  gerekmez. Sunucu o zaman yalnızca bu Mac'e (127.0.0.1) açılır. cloudflared yoksa
  aynı Wi-Fi'dan, kendi imzalı sertifikayla HTTPS (telefon bir kez uyarı gösterir).
- Eşleştirme: QR kodda adres ve erişim kodu vardır. Kod adresin # kısmında gider
  (sunucuya ya da tünele hiç yazılmaz), telefon onu saklar ve adresten siler. Kod
  Anahtar Zinciri'nde durur, günlüğe yazılmaz; YENİ KOD ile eskisi geçersiz olur.
  Yanlış koda art arda deneme kısa süre engellenir. Aynı anda tek telefon.
- Ses: telefon "BAŞLAT"a basınca (tarayıcılar sesi ancak dokunuşla açar) cevaplar
  telefondan çıkar; telefonun mikrofonu açıkken Mac'in mikrofonu susar. Telefon
  kapanınca, kilitlenince ya da bağlantı koparsa her şey kendiliğinden Mac'e döner.

V3'teki sorunlar ve buradaki karşılıkları:
- Telefon ayrı bir Gemini oturumu açıyordu; ~10 dakikada bir sunucu yenileyince
  kopuyordu, araç çalışırken susuyordu → artık Mac'teki beyin kullanılır (oturum
  sürdürme, araçlar ayrı görevde).
- Üç ayrı süreç (sunucu, ajan, tünel) ve açık kalması gereken bir Terminal → tek
  süreç; tünel uygulamayla açılır, uygulamayla kapanır, koparsa yeniden kurulur.
- Erişim kodu proje klasöründe (web_config.json) duruyordu → Anahtar Zinciri.
- Mikrofon sesi süzgeçsiz 16 kHz'e iniyordu, iPhone'da ses dokunuş beklenmeden
  açıldığı için çıkmayabiliyordu → telefon sayfasında (phone.js) düzeltildi.

iPhone uygulaması (Jarvis V4 iPhone) ayrı bir roldür: konuşma telefonun kendi
Gemini'siyle telefonda sürer; bu Mac yalnızca araçları çalıştırır (uygulama aç,
takvim, dosya bul…) ve sonucu telefona döner. Aynı sunucu, aynı erişim kodu (QR):
- Sunucu her zaman HTTPS'tir ve aynı Wi-Fi'a açıktır; Bonjour'la (_jarvis._tcp)
  duyurulur, iPhone Mac'i kendisi bulur. Sertifika kendi imzalıdır: uygulama onu
  anahtarın parmak iziyle tanır (QR'da `k=`), başka sunucuya kod göndermez.
- Evin dışından Cloudflare tüneliyle bağlanır (tünel adresi bağlanınca telefona söylenir).
- Terminal komutu (shell_run) telefondan varsayılan olarak kapalıdır (Ayarlar › TELEFON).
- Evin dışından: tünel adresi her açılışta değişir. Mac yeni adresi şifreleyip (AES-GCM, anahtar
  erişim kodundan türer) açık bir bildirim servisine (ntfy.sh) bırakır; telefon aynı Wi-Fi'da
  değilken oradan alıp çözer. Servis yalnızca şifreli metni ve rastgele görünen konu adını görür;
  erişim kodu gitmez. Ayarlar › TELEFON'dan kapatılabilir.
- Dosya gönderme: telefondaki asistanın bulduğu (find_files) ya da hazırladığı dosya telefona
  kart olarak gider. Kartın kendi tek kullanımlık, 15 dakikalık bağlantısı vardır (/file/<kimlik>);
  erişim kodu adrese yazılmaz, yalnızca kartı çıkmış dosya indirilebilir.
'''

from __future__ import annotations
import asyncio
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import urllib.parse
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from . import paths, settings
from .log import log
PORT = 8765
STATIC = paths.PACKAGE_DIR / 'ui' / 'phone'
FONTS = paths.PACKAGE_DIR / 'ui' / 'hud' / 'fonts'
TUNNEL_WAIT = 45.0
BLOCK_AFTER = 8
BLOCK_FOR = 300.0
OUT_MAX = 600
TOOL_TIMEOUT = 30.0
BONJOUR = '_jarvis._tcp'
SHARE_FOR = 900.0
RELAY = 'https://ntfy.sh'
RELAY_EVERY = 21600.0
SHARE_MAX = 157286400
_URL_RE = re.compile('https://[a-z0-9-]+\\.trycloudflare\\.com')
_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.ttf': 'font/ttf', '.svg': 'image/svg+xml'}
_ROUTES = {'/': STATIC / 'index.html', '/phone.js': STATIC / 'phone.js', '/phone.css': STATIC / 'phone.css', '/worklet.js': STATIC / 'worklet.js', '/manifest.webmanifest': STATIC / 'manifest.webmanifest', '/fonts/Grift-Bold.ttf': FONTS / 'Grift-Bold.ttf', '/fonts/Grift-Regular.ttf': FONTS / 'Grift-Regular.ttf'}

def cloudflared() -> 'str | None':
    if paths.IS_WIN:
        return
    if paths.FROZEN and (paths.BUNDLED_HELPERS / 'cloudflared').is_file():
        return str(paths.BUNDLED_HELPERS / 'cloudflared')
    hit = shutil.which('cloudflared')
    if hit:
        return hit
    for p in ('/opt/homebrew/bin/cloudflared', '/usr/local/bin/cloudflared'):
        if not Path(p).is_file():
            continue
        return p

def lan_ip() -> 'str':
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'

def relay_topic(tok: 'str') -> 'str':
    '''Bildirim servisindeki konu: erişim kodundan türer (kodu bilmeyen tahmin edemez).'''

    return 'jarvis-' + hashlib.sha256(('konum:' + tok).encode()).hexdigest()[:32]

def publish_address(url: 'str') -> 'None':
    '''Tünel adresini şifreleyip bildirim servisine bırakır (iPhone evin dışındayken oradan alır).'''

    if not settings.get('phone_relay', True):
        return
    try:
        import requests
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        tok = token()
        key = hashlib.sha256(('anahtar:' + tok).encode()).digest()
        nonce = secrets.token_bytes(12)
        blob = base64.b64encode(nonce + AESGCM(key).encrypt(nonce, url.encode(), b'jarvis')).decode()
        requests.post(f'{RELAY}/{relay_topic(tok)}', data=blob.encode(), timeout=8)
        log('telefon: adres (şifreli) bildirildi')
        return
    except Exception as exc:
        log('telefon: adres bildirilemedi:', str(exc)[:80])

def computer_name() -> 'str':
    """Bu Mac'in adı (Sistem Ayarları › Genel › Ad), telefonda böyle görünür."""

    if paths.IS_WIN:
        from . import win_phone
        return win_phone.computer_name()
    try:
        out = subprocess.run(['/usr/sbin/scutil', '--get', 'ComputerName'], capture_output=True, text=True, timeout=3)
        if out.stdout.strip():
            return out.stdout.strip()[:60]
    except Exception:
        pass
    return socket.gethostname().removesuffix('.local')[:60]

def _dns_ready(host: 'str') -> 'bool':
    try:
        import requests
        r = requests.get('https://1.1.1.1/dns-query', params={'name': host, 'type': 'A'}, headers={'accept': 'application/dns-json'}, timeout=4)
        return any((a.get('type') == 1 for a in r.json().get('Answer') or []))
    except Exception:
        return False

def token() -> 'str':
    """Erişim kodu (Anahtar Zinciri'nde; yoksa üretilir)."""

    return settings.get_secret('phone') or new_token()

def new_token() -> 'str':
    t = secrets.token_urlsafe(24)
    if os.environ.get('JARVIS_PHONE_TOKEN'):
        os.environ['JARVIS_PHONE_TOKEN'] = t
        return t
    settings.set_secret('phone', t)
    return t

def device_name(agent: 'str') -> 'str':
    a = agent or ''
    kind = 'iPhone' if 'iPhone' in a else 'iPad' if 'iPad' in a else 'Android' if 'Android' in a else 'Mac' if 'Macintosh' in a else 'tarayıcı'
    browser = 'Chrome' if 'CriOS' in a or 'Chrome' in a else 'Firefox' if 'FxiOS' in a or 'Firefox' in a else 'Safari' if 'Safari' in a else ''
    if browser:
        return f'{kind} · {browser}'
    return kind

def _cert() -> 'tuple[str, str]':
    """Aynı Wi-Fi'dan HTTPS için kendi imzalı sertifika (veri klasöründe). Anahtar kalıcıdır:
    iPhone uygulaması bu Mac'i onun parmak iziyle tanır; adres değişince yalnızca sertifika yenilenir."""

    folder = paths.DATA_DIR / 'phone'
    crt, key = folder / 'cert.pem', folder / 'key.pem'
    ip = lan_ip()
    marker = folder / 'cert.ip'
    if crt.exists() and key.exists() and marker.exists() and marker.read_text() == ip:
        return str(crt), str(key)
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    folder.mkdir(parents=True, exist_ok=True)
    if key.exists():
        k = serialization.load_pem_private_key(key.read_bytes(), password=None)
    else:
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        key.chmod(384)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'JARVIS V4')])
    now = dt.datetime.now(dt.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=825)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)), x509.DNSName('localhost')]), critical=False).sign(k, hashes.SHA256())
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    marker.write_text(ip)
    return str(crt), str(key)

_KEY_ID = ''

def key_id() -> 'str':
    """Sunucu anahtarının parmak izi (açık anahtarın PKCS#1 DER'inin SHA-256'sı, onaltılık).
    iPhone'daki SecKeyCopyExternalRepresentation da aynı baytları verir."""

    global _KEY_ID
    if not _KEY_ID:
        from cryptography.hazmat.primitives import serialization
        _crt, key = _cert()
        k = serialization.load_pem_private_key(Path(key).read_bytes(), password=None)
        der = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
        _KEY_ID = hashlib.sha256(der).hexdigest()
    return _KEY_ID

class Phone:
    '''Sunucu, tünel ve bağlı telefon. Uygulamaya olanları `app.phone_*` yöntemleriyle bildirir.'''

    def __init__(self, app) -> 'None':
        self.app = app
        self.loop = None
        self._thread = None
        self._server = None
        self._stop = None
        self._tunnel = None
        self._lock = threading.Lock()
        self.port = 0
        self.mode = ''
        self.base = ''
        self.state = 'off'
        self.note = ''
        self.client = None
        self.device = ''
        self.active = False
        self.mic = False
        self._out = None
        self._fails = {}
        self._starting = False
        self.app_client = None
        self.app_device = ''
        self._bonjour = None
        self._win_advert = None
        self.lan_warn = ''
        self._shares = {}

    @property
    def running(self) -> 'bool':
        return self.state not in ('off', 'error')

    def status(self) -> 'dict[str, Any]':
        url = f'{self.base}/#t={token()}&k={key_id()}' if self.base else ''
        qr = ''
        if url:
            try:
                import segno
                qr = segno.make(url, error='m').svg_data_uri(scale=6, border=2, dark='#000', light='#fff')
            except Exception as exc:
                log('telefon: QR üretilemedi:', exc)
        return {'state': self.state, 'note': self.note, 'mode': self.mode, 'url': url, 'host': self.base.split('//')[-1] if self.base else '', 'qr': qr, 'device': self.device, 'active': self.active, 'mic': self.mic, 'tunnel_ok': cloudflared() is not None or paths.IS_WIN, 'lan_warn': self.lan_warn, 'autostart': bool(settings.get('phone_autostart')), 'app': self.app_device, 'shell': bool(settings.get('phone_shell')), 'relay': bool(settings.get('phone_relay', True))}

    def _set(self, state: 'str', note: 'str'='') -> 'None':
        self.state, self.note = state, note
        self.app.phone_status(self.status())

    def start(self) -> 'None':
        with self._lock:
            if self.running or self._starting:
                return
            self._starting = True
        threading.Thread(target=self._start, daemon=True, name='phone-start').start()

    def _start(self) -> 'None':
        try:
            self._set('starting', 'Sunucu açılıyor…')
            self.mode = 'tunnel' if cloudflared() else 'lan'
            ready = threading.Event()
            self._thread = threading.Thread(target=self._serve_thread, args=(ready,), daemon=True, name='phone')
            self._thread.start()
            if not ready.wait(10) or not self.port:
                self._set('error', 'Sunucu açılamadı (bağlantı noktaları dolu olabilir).')
                self._starting = False
                return
            if self.mode == 'tunnel':
                self._set('starting', 'Genel adres alınıyor (Cloudflare)…')
                url = self._open_tunnel()
                if not url:
                    self._close_tunnel()
                    self._set('error', 'Cloudflare tüneli kurulamadı. İnternet bağlantını kontrol edip yeniden dene.')
                    self._stop_server()
                    self._starting = False
                    return
                self.base = url
                threading.Thread(target=publish_address, args=(url,), daemon=True).start()
                threading.Thread(target=self._watch_tunnel, daemon=True, name='phone-tunnel').start()
            else:
                self.base = f'https://{lan_ip()}:{self.port}'
            self._advertise()
            log('telefon hazır:', self.mode, self.base.split('//')[-1])
            if paths.IS_WIN:
                self._check_network()
                self._set('ready', self.lan_warn or "iPhone uygulamasında QR'I OKUT ile bu kodu okut.")
            else:
                self._set('ready', 'Telefonun kamerasıyla QR kodu okut.')
        except Exception as exc:
            log('telefon başlatılamadı:', exc)
            self._set('error', f'Başlatılamadı: {exc}')
        finally:
            self._starting = False

    def stop(self) -> 'None':
        self._unadvertise()
        self._close_tunnel()
        self._stop_server()
        self.base, self.device = '', ''
        self._drop_client()
        if self.state != 'off':
            self._set('off', '')

    def rotate(self) -> 'None':
        '''Yeni erişim kodu: eski QR ve bağlı telefon geçersiz olur.'''

        new_token()
        log('telefon: yeni erişim kodu üretildi')
        if self.mode == 'tunnel' and self.base:
            threading.Thread(target=publish_address, args=(self.base,), daemon=True).start()
        if self.loop:
            why = "Erişim kodu yenilendi. Mac'teki yeni QR kodu okut."
            if self.client is not None:
                asyncio.run_coroutine_threadsafe(self._kick(why), self.loop)
            if self.app_client is not None:
                asyncio.run_coroutine_threadsafe(self._kick_app(why), self.loop)
        self.app.phone_status(self.status())

    def _serve_thread(self, ready: 'threading.Event') -> 'None':
        try:
            asyncio.run(self._serve(ready))
        except Exception as exc:
            log('telefon sunucusu durdu:', exc)
        finally:
            self.loop = None
            self.port = 0

    async def _serve(self, ready: 'threading.Event') -> 'None':
        from websockets.asyncio.server import serve
        self.loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._out = asyncio.Queue()
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(*_cert())
        last = None
        for port in range(PORT, PORT + 12):
            try:
                self._server = await serve(self._handle, '0.0.0.0', port, process_request=self._http, ssl=tls, max_size=1048576, ping_interval=15, ping_timeout=20, server_header='JARVIS')
                self.port = port
            except OSError as exc:
                last = exc
                continue
            break
        ready.set()
        if not self._server:
            log('telefon sunucusu açılamadı:', last)
            return
        await self._stop.wait()
        self._server.close()
        await self._server.wait_closed()

    def _stop_server(self) -> 'None':
        if self.loop and self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _http(self, connection, request):
        '''Düz HTTP: telefon sayfasının dosyaları. /ws dışındaki her istek buraya düşer.'''

        from websockets.datastructures import Headers
        from websockets.http11 import Response
        path = request.path.split('?')[0].split('#')[0]
        if path == '/ws':
            return
        if path.startswith('/file/'):
            return self._file(connection, path[len('/file/'):])
        target = _ROUTES.get(path)
        if path == '/icon.png':
            target = paths.DATA_DIR / 'icon.png'
            if not target.exists():
                try:
                    from .ui import branding
                    branding._draw_icon()
                except Exception:
                    pass
        if not target or not target.exists():
            return connection.respond(404, 'Bulunamadı\n')
        body = target.read_bytes()
        headers = Headers([('Content-Type', _TYPES.get(target.suffix, 'application/octet-stream')), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer')])
        return Response(200, 'OK', headers, body)

    def share(self, path: 'str') -> 'dict[str, Any]':
        '''Telefona gidecek kart: dosyanın bilgisi ve kısa ömürlü indirme kimliği.'''

        from . import files
        c = files.card(path)
        item = {'name': c.get('name', ''), 'kind': c.get('kind', 'other'), 'label': c.get('label', ''), 'where': c.get('where', '')}
        p = Path(path)
        try:
            ok = p.is_file() and files.allowed(p) and p.stat().st_size <= SHARE_MAX
        except OSError:
            ok = False
        if ok:
            now = time.monotonic()
            self._shares = {k: v for k, v in self._shares.items() if v[1] > now}
            fid = secrets.token_urlsafe(18)
            self._shares[fid] = str(p), now + SHARE_FOR
            item['id'] = fid
            item['size'] = p.stat().st_size
        return item

    def _file(self, connection, fid: 'str'):
        from websockets.datastructures import Headers
        from websockets.http11 import Response
        entry = self._shares.get(fid)
        if not entry or entry[1] < time.monotonic():
            return connection.respond(404, "Bağlantının süresi dolmuş. JARVIS'ten dosyayı yeniden iste.\n")
        p = Path(entry[0])
        try:
            body = p.read_bytes()
        except OSError:
            return connection.respond(404, 'Dosya bulunamadı.\n')
        log('telefona dosya gönderildi:', p.name)
        kind = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        disposition = f"attachment; filename*=UTF-8''{urllib.parse.quote(p.name)}"
        headers = Headers([('Content-Type', kind), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'), ('Content-Disposition', disposition), ('X-Content-Type-Options', 'nosniff')])
        return Response(200, 'OK', headers, body)

    def _who(self, ws) -> 'str':
        peer = ws.remote_address[0] if ws.remote_address else '?'
        req = getattr(ws, 'request', None)
        if peer in ('127.0.0.1', '::1') and req is not None and req.headers.get('Cf-Connecting-Ip'):
            return req.headers['Cf-Connecting-Ip']
        return peer

    def _blocked(self, who: 'str') -> 'bool':
        now = time.monotonic()
        fails = [t for t in self._fails.get(who, []) if now - t < BLOCK_FOR]
        self._fails[who] = fails
        return len(fails) >= BLOCK_AFTER

    async def _handle(self, ws) -> 'None':
        '''Bir telefon: önce kod, sonra ses ve yazı.'''

        who = self._who(ws)
        if self._blocked(who):
            await ws.close(4003, 'cok fazla deneme')
            return
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
        except Exception:
            await ws.close(4000, 'merhaba yok')
        if hello.get('type') != 'hello' or not secrets.compare_digest(str(hello.get('token', '')), token()):
            self._fails.setdefault(who, []).append(time.monotonic())
            log('telefon: yanlış erişim kodu', f'({len(self._fails[who])}. deneme)')
            await ws.send(json.dumps({'type': 'denied', 'text': "Erişim kodu geçersiz. Mac'teki QR kodu yeniden okut."}))
            await ws.close(4001, 'kod')
            return
        self._fails.pop(who, None)
        if hello.get('role') == 'app':
            await self._serve_app(ws, hello)
            return
        if self.client is not None:
            await self._kick('Başka bir cihaz bağlandı.')
        self.client = ws
        self.device = device_name(str(hello.get('device', '')))
        self.active = self.mic = False
        while self._out and not self._out.empty():
            self._out.get_nowait()
        log('telefon bağlandı:', self.device)
        await ws.send(json.dumps({'type': 'welcome', **self.app.phone_welcome()}))
        self._set('connected', '')
        writer = asyncio.create_task(self._writer(ws))
        try:
            pass
        except Exception as exc:
            if '1000' not in str(exc) and '1001' not in str(exc):
                log('telefon bağlantısı koptu:', str(exc)[:80])
        async for _ in ws:
            self._command(json.loads(msg))
        try:
            msg = ws
            if isinstance(msg, bytes):
                if msg[:1] == b'\x01' and self.mic and self.active:
                    self.app.phone_pcm(msg[1:])
                # WARNING: continue outside loop (unrecovered structure)
        except Exception as exc:
            if '1000' not in str(exc) and '1001' not in str(exc):
                log('telefon bağlantısı koptu:', str(exc)[:80])
            try:
                pass
            except Exception as exc:
                if '1000' not in str(exc) and '1001' not in str(exc):
                    log('telefon bağlantısı koptu:', str(exc)[:80])
        finally:
            writer.cancel()
            if self.client is ws:
                self._drop_client()
                log('telefon ayrıldı')
                if self.running:
                    self._set('ready', 'Telefon ayrıldı. Yeniden bağlanabilir.')

    def _command(self, obj: 'dict') -> 'None':
        kind = obj.get('type')
        if kind == 'audio':
            self.active = bool(obj.get('on'))
            if not self.active:
                self.mic = False
            self.app.phone_route(self.active, self.mic)
            self.app.phone_status(self.status())
            return
        if kind == 'mic':
            self.mic = bool(obj.get('on')) and self.active
            self.app.phone_route(self.active, self.mic)
            self.app.phone_status(self.status())
            return
        if kind == 'text':
            text = str(obj.get('text', '')).strip()[:2000]
            if text:
                self.app.phone_text(text)
                return
            return
        if kind == 'wake':
            self.app.phone_wake()

    async def _serve_app(self, ws, hello: 'dict') -> 'None':
        """Konuşma telefonda (kendi Gemini'si); bu Mac yalnızca istenen araçları çalıştırır."""

        if self.app_client is not None:
            await self._kick_app('Başka bir iPhone bağlandı.')
        self.app_client = ws
        self.app_device = str(hello.get('device', '') or 'iPhone')[:60]
        log('iPhone uygulaması bağlandı:', self.app_device)
        where = {'mac': computer_name(), 'key': key_id(), 'lan': {'host': lan_ip(), 'port': self.port}, 'tunnel': self.base if self.mode == 'tunnel' else ''}
        await ws.send(json.dumps({'type': 'welcome', 'role': 'app', **where, **self.app.phone_app_welcome()}, ensure_ascii=False))
        self.app.phone_app(True, self.app_device)
        self.app.phone_status(self.status())
        tasks = set()
        try:
            pass
        except Exception as exc:
            if '1000' not in str(exc) and '1001' not in str(exc):
                log('iPhone bağlantısı koptu:', str(exc)[:80])
        async for _ in ws:
            try:
                msg = ws
                if isinstance(msg, bytes):
                    continue
                obj = json.loads(msg)
                if obj.get('type') == 'call':
                    task = asyncio.create_task(self._app_call(ws, obj))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                else:
                    if not str(obj.get('type', '')).startswith('memory'):
                        continue
                    await asyncio.to_thread(self.app.phone_memory, obj)
            except Exception as exc:
                if '1000' not in str(exc) and '1001' not in str(exc):
                    log('iPhone bağlantısı koptu:', str(exc)[:80])
            continue
            continue
            continue
            continue
        try:
            pass
        except Exception as exc:
            if '1000' not in str(exc) and '1001' not in str(exc):
                log('iPhone bağlantısı koptu:', str(exc)[:80])
        finally:
            for task in tasks:
                task.cancel()
            if self.app_client is ws:
                self.app_client, self.app_device = None, ''
                log('iPhone uygulaması ayrıldı')
                self.app.phone_app(False, '')
                self.app.phone_status(self.status())

    async def _app_call(self, ws, obj: 'dict') -> 'None':
        cid = str(obj.get('id', ''))[:80]
        name = str(obj.get('name', ''))[:64]
        args = obj.get('args') if isinstance(obj.get('args'), dict) else {}
        try:
            result, ok, images, shown = await asyncio.wait_for(asyncio.to_thread(self.app.phone_tool, name, args), TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            result, ok, images, shown = f"{name} {int(TOOL_TIMEOUT)} saniyede bitmedi; Mac'te arka planda sürüyor olabilir. Kullanıcıya bunu kısaca söyle.", False, [], []
        from .tools import registry
        tool = registry.tools.get(name)
        cue = 'error' if not ok else 'done' if tool and tool.success_sfx else ''
        reply = {'type': 'result', 'id': cid, 'ok': ok, 'result': result, 'sfx': cue, 'images': [base64.b64encode(jpeg).decode() for jpeg in images], 'files': [self.share(p) for p in shown[:6]]}
        try:
            await ws.send(json.dumps(reply, ensure_ascii=False))
        except Exception:
            return

    def push_app(self, payload: 'dict') -> 'None':
        '''iPhone uygulamasına bir ileti (her iş parçacığından); bağlı değilse bir şey olmaz.'''

        ws, loop = self.app_client, self.loop
        if ws is not None:
            if loop is not None:
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps(payload, ensure_ascii=False)), loop)

    async def _kick_app(self, why: 'str') -> 'None':
        ws = self.app_client
        if ws is None:
            return
        try:
            await ws.send(json.dumps({'type': 'replaced', 'text': why}))
            await ws.close(4002, 'yerine')
        except Exception:
            return

    def _advertise(self) -> 'None':
        self._unadvertise()
        if paths.IS_WIN:
            if self.port:
                from . import win_phone
                self._win_advert = win_phone.Advert()
                self._win_advert.start(BONJOUR, computer_name(), lan_ip(), self.port, {'id': key_id()[:16], 'ip': lan_ip(), 'port': str(self.port), 'v': '1'})
            return
        exe = '/usr/bin/dns-sd'
        if not Path(exe).exists() or not self.port:
            return
        txt = [f'id={key_id()[:16]}', f'ip={lan_ip()}', f'port={self.port}', 'v=1']
        try:
            self._bonjour = subprocess.Popen([exe, '-R', computer_name(), BONJOUR, 'local', str(self.port), *txt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as exc:
            log('telefon: Bonjour duyurusu açılamadı:', exc)

    def _check_network(self) -> 'None':
        '''Windows: Wi-Fi "Genel" ağ sayılıyorsa güvenlik duvarı iPhone'u çoğunlukla engeller; ekranda söylenir.'''

        from . import win_phone
        kind = win_phone.network_category(lan_ip())
        log('telefon: ağ profili', kind or 'bilinmiyor')
        if kind == 'Public':
            self.lan_warn = 'Wi-Fi ağın Windows\'ta "Genel ağ" görünüyor; iPhone bağlanamayabilir. Windows Ayarları › Ağ ve İnternet › Wi-Fi › bu ağ › Ağ profili türü: Özel ağ.'
            return
        self.lan_warn = ''

    def _unadvertise(self) -> 'None':
        advert, self._win_advert = self._win_advert, None
        if advert is not None:
            advert.stop()
        proc, self._bonjour = self._bonjour, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
                return
            except Exception:
                proc.kill()

    def _drop_client(self) -> 'None':
        was = self.active
        self.client = None
        self.active = self.mic = False
        self.device = ''
        if was:
            self.app.phone_route(False, False)

    async def _kick(self, why: 'str') -> 'None':
        ws = self.client
        if ws is None:
            return
        try:
            await ws.send(json.dumps({'type': 'replaced', 'text': why}))
            await ws.close(4002, 'yerine')
        except Exception:
            pass
        self._drop_client()

    async def _writer(self, ws) -> 'None':
        q = self._out
        frame = await q.get()
        if self.client is ws:
            await ws.send(frame)

    def _queue(self, frame) -> 'None':
        q = self._out
        if q is None:
            return
        if q.qsize() >= OUT_MAX:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(frame)

    def send(self, payload: 'dict') -> 'None':
        '''Durum, sohbet satırı, model… (her iş parçacığından).'''

        if self.client is not None:
            if self.loop:
                self.loop.call_soon_threadsafe(self._queue, json.dumps(payload, ensure_ascii=False))

    def audio(self, pcm: 'bytes') -> 'None':
        '''Modelin sesi (24 kHz, 16 bit): beyin iş parçacığından.'''

        if self.client is not None:
            if self.active:
                if self.loop:
                    self.loop.call_soon_threadsafe(self._queue, b'\x02' + pcm)

    def cut(self) -> 'None':
        '''Söz kesildi: telefondaki sıradaki sesler atılsın.'''

        if self.client is not None:
            if self.loop:
                def clear() -> 'None':
                    q = self._out
                    kept = []
                    while q and not q.empty():
                        frame = q.get_nowait()
                        if not isinstance(frame, bytes):
                            kept.append(frame)
                    for frame in kept:
                        q.put_nowait(frame)
                    q.put_nowait(json.dumps({'type': 'cut'}))

                self.loop.call_soon_threadsafe(clear)

    def _open_tunnel(self) -> 'str | None':
        exe = cloudflared()
        if not exe:
            return
        self._tunnel = subprocess.Popen([exe, 'tunnel', '--no-autoupdate', '--no-tls-verify', '--url', f'https://127.0.0.1:{self.port}'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        found = []
        def read(proc: 'subprocess.Popen') -> 'None':
            for line in proc.stdout:
                if found:
                    continue
                m = _URL_RE.search(line)
                if m:
                    found.append(m.group(0))

        threading.Thread(target=read, args=(self._tunnel,), daemon=True, name='phone-tunnel-log').start()
        end = time.monotonic() + TUNNEL_WAIT
        if time.monotonic() < end:
            if not found and self._tunnel.poll() is None:
                while True:
                    time.sleep(0.25)
                    if not time.monotonic() < end:
                        break
                    if found:
                        break
                    if self._tunnel.poll() is not None:
                        break
        if not found:
            return
        host = found[0].split('//')[1]
        for _ in range(30):
            if _dns_ready(host):
                time.sleep(1.5)
                return found[0]
            time.sleep(1)
        return found[0]

    def _close_tunnel(self) -> 'None':
        proc, self._tunnel = self._tunnel, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
            return
        except Exception:
            try:
                proc.kill()
                return
            except Exception:
                pass

    def _watch_tunnel(self) -> 'None':
        '''Tünel koparsa bir kez yeniden kurulur (adres değişir; QR yenilenir).'''

        proc = self._tunnel
        last_publish = time.monotonic()
        while proc is not None:
            while proc is self._tunnel:
                if time.monotonic() - last_publish > RELAY_EVERY and self.base:
                    publish_address(self.base)
                    last_publish = time.monotonic()
                if proc.poll() is not None:
                    log('telefon: Cloudflare tüneli koptu, yeniden kuruluyor')
                    self._set('starting', 'Tünel koptu, yeniden kuruluyor…')
                    url = self._open_tunnel()
                    if url:
                        self.base = url
                        publish_address(url)
                        last_publish = time.monotonic()
                        self._set('connected' if self.client else 'ready', "Tünel yenilendi: iPhone uygulaması yeni adresi kendisi öğrenir; tarayıcıdan bağlanıyorsan QR'ı yeniden okut.")
                        proc = self._tunnel
                        continue
                    self._close_tunnel()
                    self._stop_server()
                    self._set('error', 'Cloudflare tüneli yeniden kurulamadı.')
                    return
                time.sleep(3)


# WARNING: Decompyle incomplete

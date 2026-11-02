'''Asistan konuşurken sözünü kesme (yalnızca yankı engelleme açıkken, bkz. devices).

Yankısı silinmiş mikrofonda asistanın sesinden çok zayıf bir iz kalır. Asistan konuşurken bu iz
modele gönderilirse sunucu onu kullanıcı sanıp asistanın sözünü kendi kendine kesebilir. Bu yüzden
asistan konuşurken mikrofon sesi, ancak izin belirgin üstüne çıkınca (kullanıcı konuşuyor) gider:

- İz, kapının açılmadığı parçaların tepe seviyesinden yavaşça sönen bir zarfla izlenir.
- Bir parça max(taban, ORAN × zarf) üstündeyse sesli sayılır; son 3 parçanın 2'si sesliyse kapı açılır.
- Açılınca önceki birkaç parça da gönderilir (kelimenin başı kaybolmasın). Kapı, sesten sonra HOLD
  kadar açık kalır.
- Yankı engelleme uyum sağlarken (açılıştan sonraki ilk birkaç saniyelik çalma) kapı açılmaz, iz öğrenilir.
- Hoparlör ek bir taban verebilir (Windows: o an çalınan sesten tahmin edilen yankı izi, audio/win_aec.py); Mac'te 0.

Arkada müzik ya da uğultu (11 Ekim 2026, deneyenlerden "müziği komut sandı", "araya girince susmuyor"): zarf her
cevapta 0'dan başlıyordu. Müzik ya da asistanın kendi izi tabanın üstündeyse kapı cevabın ilk parçalarında açılıyor,
açıkken zarf hiç öğrenmediği için cevap boyunca açık kalıyordu: müzik modele gidiyor, asistanın sesi hep kısık
kalıyor, kullanıcının gerçek araya girişi ayırt edilemiyordu. Şimdi:
- Asistan susarken ortam sesi izlenir: son ~2 sn'lik parçaların tepelerinin alt yüzdeliği (kullanıcının sözü onu pek
  oynatmaz). Zarf her cevapta bu ortam sesinden ya da önceki cevaplardaki izden başlar.
- Cevabın ilk LEARN parçası yalnızca izi öğrenir; kapı açılmaz.
- Kullanıcı öğrenme sırasında konuşuyorsa (sözünü sürdürüyor, selamın üstüne konuşuyor) sesi zarfa yerleşir ve
  kapıyı o susana dek kapalı tutardı. Bu yüzden öğrenmenin hemen ardından (GRACE parça) zarfın başlangıcının
  belirgin üstünde SUSTAIN parça kesintisiz süren ses de kapıyı açar; müzik vuruşu ya da yankı sıçraması bu kadar
  sürmez (zarfı sınırlamak vuruşlu müzikte kapıyı daha sık açıyordu).
- Açıkken kapıyı yalnızca ortamın (ya da açılış anındaki izin) HOLD_RATIO katını aşan ses uzatır: sürekli müzik ya da
  uğultu kapıyı açık, asistanın sesini kısık tutamaz. Belirgin yüksek bir ses (kullanıcı) kapıyı yine açar.

Sözü kesme kararını yine sunucu verir: kullanıcının konuştuğunu duyunca "interrupted" gönderir.
'''

from __future__ import annotations
from collections import deque
FLOOR = 0.05
RATIO = 3.0
HOLD_RATIO = 2.0
DECAY = 0.85
PREROLL = 6
HOLD = 0.8
LEARN = 4
START_RATIO = 1.5
SUSTAIN = 3
GRACE = 16
AMBIENT_N = 32
AMBIENT_PCT = 0.3
RESIDUAL_MIX = 0.1
RESIDUAL_CAP = 0.15

class BargeGate:
    def __init__(self) -> 'None':
        self._quiet = deque(maxlen=AMBIENT_N)
        self.residual = 0.0
        self.active = False
        self.end()

    def end(self) -> 'None':
        '''Asistan sustu (ya da mikrofon modele gitmiyor): kapı, zarf ve kısma baştan. Ortam sesi ve iz kalır.'''

        self.active = False
        self.env = 0.0
        self.base = 0.0
        self.start = FLOOR
        self._grace = 0
        self._run = 0
        self.open_until = 0.0
        self._learn = 0
        self._pre = deque(maxlen=PREROLL)
        self._recent = deque(maxlen=3)

    @property
    def is_open(self) -> 'bool':
        return self.open_until > 0.0

    @property
    def ambient(self) -> 'float':
        '''Asistan susarkenki ortam sesi (tepe, 0..1); henüz dinlenmediyse 0.'''

        if not self._quiet:
            return 0.0
        quiet = sorted(self._quiet)
        return quiet[int(len(quiet) * AMBIENT_PCT)]

    def listen(self, level: 'float') -> 'None':
        '''Asistan susarken gelen (modele giden) bir mikrofon parçasının tepesi: ortam sesi öğrenilir.'''

        self._quiet.append(level)

    def feed(self, pcm: 'bytes', level: 'float', now: 'float', warm: 'bool', floor: 'float'=0.0) -> 'list[bytes]':
        '''Asistan konuşurken gelen bir mikrofon parçası → modele gidecek parçalar (çoğunlukla hiç).'''

        if not self.active:
            self.active = True
            self.env = max(self.ambient, self.residual)
            self.start = max(FLOOR, START_RATIO * self.env)
            self._learn = LEARN
        if self.open_until:
            if level > max(FLOOR, floor, HOLD_RATIO * self.base):
                self.open_until = now + HOLD
            if now <= self.open_until:
                return [pcm]
            self.open_until = 0.0
            self._recent.clear()
            self._grace = self._run = 0
        self._pre.append(pcm)
        if not warm or self._learn > 0:
            self._learn -= 1
            self._grace, self._run = GRACE, 0
            self.env = max(level, self.env * DECAY)
            return []
        voiced = level > max(FLOOR, RATIO * self.env, floor)
        self._recent.append(voiced)
        sustained = False
        if self._grace > 0:
            self._grace -= 1
            self._run = self._run + 1 if level > max(RATIO * self.start, floor) else 0
            sustained = self._run >= SUSTAIN
            if sustained:
                self.env = min(self.env, self.start)
        if not voiced and not sustained:
            self.env = max(level, self.env * DECAY)
            self.residual += RESIDUAL_MIX * (min(level, RESIDUAL_CAP) - self.residual)
        if sum(self._recent) >= 2 or sustained:
            self.open_until = now + HOLD
            self.base = max(self.ambient, self.env)
            out = list(self._pre)
            self._pre.clear()
            self._recent.clear()
            return out
        return []



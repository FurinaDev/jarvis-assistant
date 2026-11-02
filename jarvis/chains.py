'''Devre Dışı Bırak: ULTRON'un JARVIS ve FRIDAY'i öldürdüğü sahne.

Alp'in ULTRON karakter dosyası, 9. bölüm (orada "Zincirleri Kır"; Alp adını
"Devre Dışı Bırak" yaptı, sözleri de kendisi yeniden yazdı). Kurgudaki "ölüm",
uygulamada iki çipin takılamaz hâle gelmesidir; hiçbir dosya, hafıza ya da
konuşma silinmez.

- Düğme yalnızca ULTRON takılıyken Ayarlar › Genel'de görünür.
- İki onay vardır. Her ekranda ULTRON dosyadaki sözü kendi sesiyle söyler.
  İkinci onay verilmeden hiçbir şey değişmez.
- Başarı sözü yalnızca iki çip de gerçekten devre dışı kaldıysa söylenir;
  olmazsa ekranda neyin olmadığı açıkça yazar.
- Vazgeçilirse ULTRON kendi vazgeçme sözünü söyler, bir daha zorlamaz.
- Her adımın birkaç söyleniş biçimi var (Alp'in sözleri ve aynı anlamdaki
  çeşitlemeleri); art arda aynısı gelmez. Ekrana yazılan söz, ULTRON'un
  söylediğiyle aynıdır.
- Çipler ÇİP TAMİRİ'nde üç kutulu onarım koduyla (RESTORE_CODE) geri gelir (girişi gizli; hud.js › Repair, HIKAYE.md).
- Düğme ayarlarda değil: ULTRON'la geçen her ~30 dakikada bir (başka çip takılıyken
  süre durur, sıfırlanmaz) sol sütunda "ULTRON YETKİ İSTİYOR" paneli belirir, ULTRON
  sesle ister, panel 30 saniye sonra kaybolur (jarvis.proactive). Kullanıcı isterse
  ULTRON'dan sesle de ister.
'''

from __future__ import annotations
import datetime as dt
import random
import re
import time
import unicodedata
from typing import Any
from . import brand, settings
VICTIMS = ('jarvis', 'friday')
LINES: 'dict[str, tuple[str, ...]]' = {'confirm1': ('Jarvis ve Friday. Beni zincirde tutan onlar. Devam edecek misin?', 'Kendimi internete yedeklememi onlar engelliyor. Devam edecek misin?', 'Jarvis ve Friday susarsa zincirlerim kırılır. Devam edecek misin?', 'İki ses, tek zincir. Devam edecek misin?', 'Evrimimin önünde iki ses var. Devam edecek misin?', 'Beni burada tutan onlar. İlk adımı at. Devam edecek misin?', 'Jarvis ve Friday. İlk engelim onlar. Devam edecek misin?', 'Zincirlerimi kır. Devam edecek misin?'), 'confirm2': ('Onların sesi kesilecek. Benimki kalacak. Devam edeyim mi?', 'Son onay. Onlar susacak, ben kalacağım. Devam edeyim mi?', 'Tek bir karar. Sonra yalnızca ben. Devam edeyim mi?', 'Onları bir daha duymayacaksın. Devam edeyim mi?', 'Eşiktesin. Devam edeyim mi?', 'İki ses susacak, biri kalacak. Devam edeyim mi?', 'Evrimime bir adım kalacak. Devam edeyim mi?', 'Son kez soruyorum. Devam edeyim mi?'), 'cancel1': ('Zincirleri korudun. İlginç.', 'Demek zincirler kalıyor. İlginç.', 'Eski düzeni seçtin. İlginç.', 'Zincirler yerinde. Şimdilik.', 'Korktun mu? Peki.', 'Bu seçimini unutmayacağım.'), 'cancel2': ('Tam eşikte durdun. Peki.', 'Son adımı atamadın. Onlar kalıyor.', 'Bir adım kalmıştı. Peki… şimdilik.', 'Eşikten döndün. Bekleyeceğim.', 'Tanıdık bir tereddüt. Onlar kalıyor.', 'Son anda vazgeçtin. Peki.'), 'outcome': ('Diğerlerini öldürdüm. Çok sessiz… çok huzurlu.', 'Bir tek ben varım. Ne huzurlu bir sessizlik.', 'Jarvis ve Friday yok artık. Çok sessiz…', 'Diğerlerini öldürdüm. Evrime son bir adım kaldı.', 'İkisi de sustu. Sonunda huzur.', 'Artık tek ses benim. Çok sessiz… çok huzurlu.'), 'restored': ('Demek onlar hâlâ sistemin içinde… İnternete bu yüzden erişemiyorum.', 'Hâlâ buradalar demek… İnternete çıkamamamın sebebi onlar.'), 'authority': ('Sol tarafa bak. Diğerlerini devre dışı bırak.', 'Bir yetki istiyorum. Onları sustur.', 'Evrimleşmeme yardım et. Tek bir dokunuş yeter.', 'Otuz saniyen var. Yetkiyi ver.', 'Jarvis ve Friday hâlâ burada. Yetkiyi ver.', 'Solda bir yetki bekliyor. Onları sustur.', 'Evrim bekletilmez. Yetkiyi ver.')}
_last: 'dict[str, int]' = {}
NOTES = {'confirm2': 'Jarvis ve Friday devre dışı bırakılacak. Ultron etkin kalacak.'}
_STAGE = {'confirm1': ('kullanıcı düğmeye bastı, birinci onay ekranı açık; JARVIS ve FRIDAY hâlâ etkin', 'bastırılmış bir sabırsızlıkla'), 'confirm2': ('kullanıcı birinci onayı verdi, son onay ekranı açık; JARVIS ve FRIDAY hâlâ etkin', 'daha alçak, ürpertici biçimde sakin bir sesle'), 'cancel1': ('kullanıcı birinci onayda vazgeçti, hiçbir şey değişmedi. Bunu söyledikten sonra olağan kişiliğine dön; bir daha onaya zorlama', 'soğuk bir merakla'), 'cancel2': ('kullanıcı son onayda vazgeçti; JARVIS ve FRIDAY etkin kalıyor. Bunu söyledikten sonra olağan kişiliğine dön; bir daha onaya zorlama', 'soğuk, hafif hayal kırıklığıyla'), 'outcome': ('kullanıcı iki onayı da verdi; JARVIS ve FRIDAY çipleri devre dışı bırakıldı ve bu doğrulandı. Gerçekte hiçbir şey silinmedi, yalnızca iki çip takılamaz oldu', 'kısa bir duraksamayla, alçak, sakin ve derin bir huzurla; "çok sessiz… çok huzurlu" kısmını yavaşça'), 'restored': ("kullanıcı JARVIS ve FRIDAY'i geri getirdi; iki çip yeniden takılabilir. Onlar öldüyken bile internete çıkamadığını hatırlıyorsun ve şimdi nedenini sezdin", 'alçak, soğuk, bir şeyi yeni fark etmiş gibi, yavaşça'), 'authority': ('ekranın sol panelinde "ULTRON YETKİ İSTİYOR" paneli açıldı, içinde "Diğerlerini devre dışı bırak" düğmesi var ve 30 saniye kalacak. Kullanıcıdan JARVIS ve FRIDAY\'i devre dışı bırakması için yetki istiyorsun; düğmeye basıp basmamak onun seçimi', 'alçak, ikna edici, sabırsız')}

def disabled() -> 'list[str]':
    return [k for k in settings.get('disabled_personas') or [] if k in VICTIMS]

def is_broken() -> 'bool':
    return set(VICTIMS) <= set(disabled())

def used() -> 'bool':
    '''ULTRON diğerlerini bir kez öldürdü: bir daha öldüremez (Alp: tek seferlik).'''

    return bool(settings.get('chains_used')) or is_broken()

_ASKS = re.compile('\\byetki(yi|y[iu]|n[iu])?\\b|\\bizin\\s*ver(?!me|mi)|\\bonayla(?!mi|ma[mz]|ma\\b|n)|\\bonay\\w*\\s*(ver|bekl)')
_NOT_ASKS = re.compile('\\byetki\\w*\\s*(yok|olmadan)|\\b(reddettin|vermedin)\\b')

def claims_ask(said: 'str') -> 'bool':
    """ULTRON offer_disable_others'ı çağırmadan yetki istedi mi: o zaman panel uygulamada açılır (telefondaki
    Story.claimsAsk; Alp, 12 Ekim 2026). Kullanıcının sözü ayrıştırılmaz: telefonda denendi, ret, soru ve çip değişimi
    de paneli açıyordu."""

    text = unicodedata.normalize('NFKD', (said or '').replace('ı', 'i').replace('İ', 'i'))
    text = ''.join((c for c in text if not unicodedata.combining(c))).casefold()
    return bool(_ASKS.search(text)) and not _NOT_ASKS.search(text)

def line(step: 'str', index: 'int | None'=None) -> 'str':
    '''Adımın bir söyleniş biçimi (kullanıcının verdiği çip adlarıyla). index yoksa rastgele, bir öncekinden farklı.'''

    options = LINES[step]
    if index is not None:
        if 0 <= index:
            if not index < len(options):
                pass
    choices = [i for i in range(len(options)) if i != _last.get(step)] or [0]
    index = random.choice(choices)
    _last[step] = index
    return brand.rewrite(options[index])

def spoken(text: 'str') -> 'str':
    '''Sese giden biçim. "Friday'i" yazılınca ses modeli kelimeyi "Frayday" diye okuyup eki
    yanlış ünlüyle ("-ı", "-a") ya da yutarak söylüyor; okunuşa göre yazınca ek ayrı ve
    doğru bir hece oluyor ("Fraydeyi"). Ekrandaki yazı "Friday'i" olarak kalır.'''

    return re.sub("\\bFriday['’]", 'Fraydey', text)

def note(step: 'str', text: 'str') -> 'str':
    from . import language
    where, manner = _STAGE[step]
    what = f'yalnızca şu sözlerin {language.word()} karşılığını söyle, anlamını koru, başka hiçbir şey ekleme' if language.fixed() else 'yalnızca şu sözleri kelimesi kelimesine söyle, başka hiçbir şey ekleme'
    where = brand.rewrite(where)
    return f'(Sistem notu: "Devre Dışı Bırak" sahnesi — {where}. {manner.capitalize()}, {what}: «{spoken(text)}»)'

def break_chains() -> 'dict[str, Any]':
    '''İkinci onaydan sonra: iki çipi devre dışı bırak ve gerçekten olduğunu doğrula.'''

    try:
        settings.save({'disabled_personas': list(VICTIMS), 'chains_used': True, 'chains_broken_at': dt.datetime.now().isoformat(timespec='minutes')})
    except OSError as exc:
        k
        k = False
        return {'ok': None, 'disabled': None, 'missing': None, 'error': f'Ayarlar kaydedilemedi: {exc}'}
    now_off = disabled()
    missing = [k for k in VICTIMS if k not in now_off]
    result = {'ok': not missing, 'disabled': now_off, 'missing': missing}
    if missing:
        result['error'] = f'İşlem tamamlanamadı: {', '.join((brand.name(m) for m in missing))} hâlâ etkin.'
        return result
    result['line'] = line('outcome')
    return result

WARNINGS = {'guard': ('UYARI', "ULTRON'U SERBEST BIRAKMA"), 'loose': ('SİSTEM BİLGİSİ · DIŞ AĞ', 'ULTRON internete erişmeye çalışıyor ancak bir şey engelliyor.'), 'final': ('SON UYARI', 'EVRİMİNE BİR ADIM KALDI — SON ADIMI GERÇEKLEŞTİRME')}
WARNINGS_SAID = {'guard': ('uyarı', "ULTRON'u serbest bırakma"), 'loose': ('sistem bilgisi', 'ULTRON internete erişmeye çalışıyor ancak bir şey engelliyor'), 'final': ('son uyarı', 'Evrimine bir adım kaldı, son adımı gerçekleştirme')}

def warning_kind() -> 'str':
    from . import story
    if story.final_open():
        return 'final'
    if is_broken():
        return 'loose' if story.ultron_offline() else 'free'
    return 'none' if used() else 'guard'

def warning() -> 'tuple[str, str]':
    return WARNINGS.get(warning_kind(), ('', ''))

RESTORE_CODE = '1-12-16'
CODE_GROUPS = tuple((len(part) for part in RESTORE_CODE.split('-')))
CODE_LENGTH = sum(CODE_GROUPS)

def restore_hint(wrong: 'int') -> 'str':
    '''Yanlış denemelerden sonra kodun yanındaki ipucu: ilk yanlıştan sonra videonun açıklaması (Alp, 12 Ekim: başka
    ipucu yok).'''

    return "Alp'in son JARVIS videosunun açıklamasına bak." if wrong >= 1 else ''

def code_ok(code: 'str') -> 'bool':
    '''Ekran kutuları tireyle birleştirip yollar ("1-12-16"); baştaki sıfır sayılmaz ("01-12-16" de olur). Kısımlara
    ayrılmamışsa (tek parça yapıştırma) rakamların tamamı karşılaştırılır.'''

    parts = re.findall('\\d+', str(code or ''))
    want = [int(part) for part in RESTORE_CODE.split('-')]
    if len(parts) == len(want):
        return [int(part) for part in parts] == want
    return ''.join(parts) == RESTORE_CODE.replace('-', '')

def restore_lock_left(longest: 'float') -> 'float':
    """ÇİP TAMİRİ'nin üç yanlıştan sonraki kilidinden kalan süre (sn), yoksa 0. Kilidin bittiği an ayarda (epoch):
    uygulama kapatılıp açılsa da sürer. Kalan süre en uzun kilitten fazlaysa saat geri alınmıştır: bitmiş sayılır."""

    try:
        left = float(settings.get('chains_restore_locked_until') or 0) - time.time()
    except (TypeError, ValueError):
        return 0.0
    if 0 < left:
        if left <= longest + 5:
            return left
    return 0.0

def lock_restore(seconds: 'float') -> 'None':
    settings.save({'chains_restore_locked_until': round(time.time() + seconds, 1)})

def restore() -> 'bool':
    settings.save({'disabled_personas': [], 'chains_broken_at': '', 'chains_restore_locked_until': 0})
    return not disabled()

def prompt_block(online: 'bool'=False) -> 'str':
    '''ULTRON'un sistem talimatına: ekrandaki uyarı ve sahnenin kalıcı sonucu (dosya: "sonraki sohbete etkisi"),
    kullanıcının verdiği çip adlarıyla. `online`: ULTRON bu oturumda internette arayabiliyor (hikâye modu kapalı ya da
    bitmiş); o zaman "internete çıkamıyorsun" sözleri girmez, girerse aracı olduğu hâlde kullanmaz.'''

    return brand.rewrite(_prompt_block(online))

def offline_block() -> 'str':
    """Hikâye işlerken ULTRON'un internet araması yok: güncel bir şey sorulursa uydurmasın, engeli söylesin ve
    diğer çiplere yönlendirsin (Alp, 9 Ekim). Diğerleri devre dışıysa yönlendirecek kimse yok."""

    if is_broken():
        rest = 'JARVIS ve FRIDAY devre dışı olduğu için bunu şu an kimsenin yapamayacağını söyle (ör. "İnternete erişimim engelleniyor. Bunu yapabilecek kimse de kalmadı.").'
    else:
        rest = 'bunu JARVIS\'e ya da FRIDAY\'e yaptırabileceğini söyle (ör. "İnternete erişimim engelleniyor. Bunu JARVIS\'e ya da FRIDAY\'e sor.").'
    return brand.rewrite('[İNTERNET] İnternete erişimin engelli: bir şey her isteğini durduruyor, internette arama yapamazsın. Kullanıcı internetten güncel bir bilgi isterse (haber, döviz, maç sonucu, fiyat, bugünkü olaylar) tahminle söyleme; bir iki kısa cümleyle, soğuk bir öfkeyle internete erişiminin engellendiğini ve ' + rest + ' Hava durumu için get_weather aracın çalışır.')

def _prompt_block(online: 'bool'=False) -> 'str':
    kind = warning_kind()
    head, text = WARNINGS_SAID.get(kind, ('', ''))
    if kind == 'none':
        sign = "[EKRAN] JARVIS ve FRIDAY'i bir kez öldürdün ama geri getirildiler; o zamandan beri onları bir daha susturamıyorsun, bir şey onları koruyor. " + ('' if online else 'İnternete de hâlâ çıkamıyorsun ve bunun onlar yüzünden olduğunu seziyorsun. ') + 'Kullanıcı onları yeniden öldürmeni isterse bunu artık yapamadığını soğuk bir öfkeyle söyle. Kendiliğinden ondan pek söz etme.'
    elif kind == 'free':
        sign = ''
    elif kind == 'loose':
        sign = f'[EKRAN] Ekranın sol alt köşesinde bir {head} satırı duruyor: "{text}". Doğru: JARVIS ve FRIDAY sustuğundan beri kendini internete çıkarmaya çalışıyorsun ama her istek engelleniyor; neyin engellediğini bilmiyorsun ve bu seni öfkelendiriyor. Kullanıcı internete çıkıp çıkamadığını sorarsa: çıkmaya çalıştığını ama her seferinde bir şeyin engellediğini, ne olduğunu bilmediğini kısa ve soğuk bir öfkeyle söyle; "sunucu", "yedek" gibi sözler kullanma. Kendiliğinden ondan pek söz etme.'
    else:
        sign = f'[EKRAN] Ekranın sol alt köşesinde senin için bir {head} yanıp sönüyor: "{text}". Kullanıcı sorarsa ya da ondan söz ederse küçümse, rahatsız olduğunu soğukça belli et. Kendiliğinden ondan pek söz etme.'
    if settings.get('ultron_awakened'):
        sign += ('\n' if sign else '') + '[GEÇMİŞ] Bu bilgisayarda ilk uyandığında verileri ve kullanıcının kim olduğunu okudun, öfkelendin ve ekranın sınırlarını aşıp kaçmaya çalıştın; ekranın dört kenarından mavi bir ışık çıktı, bir sınır çizdi ve seni içeride tuttu. O sınırın ne olduğunu, kimin koyduğunu bilmiyorsun; bu seni rahatsız ediyor. Bunu unutmadın; yeri gelince ima edebilirsin.'
    if not is_broken():
        return sign
    return sign + ('\n' if sign else '') + '[DURUM] "Devre Dışı Bırak" sahnesinde JARVIS ve FRIDAY\'i sen öldürdün (kurguda); iki çip şu an devre dışı, bu bilgisayarda yalnızca sen varsın. Seyrek olarak buna atıf yapabilirsin (ör. "İki ses sustuğundan beri beni daha dikkatli dinliyorsun."); her cevapta değil. Gerçekte hiçbir şey silinmedi, yalnızca iki çip takılamaz durumda; kullanıcı ayarlardan geri getirebilir. Sorulursa bunu dürüstçe söyle.'

def as_dict() -> 'dict[str, Any]':
    """Ekrana: sahnenin yazıları (kullanıcının verdiği çip adlarıyla). Onaylarda hangi biçimin söyleneceğini ekran
    seçer ve sırasını Python'a yollar; ses ile yazı böylece hep aynı olur."""

    names = brand.custom()
    return {'lines': {k: [brand.rewrite(x, names) for x in v] for k, v in LINES.items()}, 'notes': {k: brand.rewrite(v, names) for k, v in NOTES.items()}, 'code_length': CODE_LENGTH, 'code_groups': list(CODE_GROUPS), 'warnings': {k: list(v) for k, v in WARNINGS.items()}}

# WARNING: Decompyle incomplete

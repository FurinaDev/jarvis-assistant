'''
WhatsApp mesaj gönderme — macOS'ta WhatsApp Desktop (yoksa Web) üzerinden.

Numara sırasıyla: verilen numara → kayıtlı WhatsApp kişileri ve içe aktarılan rehber → Mac'in
Rehber'i (Kişiler). Hiçbirinde yoksa asistan kullanıcıya numarayı sorar, save_whatsapp_contact ile
kaydeder; bir dahaki sefere kayıttan bulunur.

Sohbet `whatsapp://send?phone=…&text=…` ile mesaj yazılmış olarak açılır, Enter'a basılır ve
gönderildiği doğrulanır: yazma kutusunda (Erişilebilirlik) mesaj önce görünmeli, Enter'dan sonra
kaybolmalı. Eskiden WhatsApp'ta ⌘F ile kişi adı aranıp körlemesine Enter'a basılıyor, sonuca
bakılmadan "gönderildi" deniyordu; mesajlar gitmiyordu.

Otomatik gönderim için macOS Erişilebilirlik izni, Rehber için Kişiler izni gerekir.

Ad eşleşmesi sıkı (Windows'takiyle aynı, find_contact): tam ad, takma ad ya da tam sözcük ("Ali" → "Ali Yılmaz");
"Can" kayıtlı "Ercan"a ya da Rehber'deki "Canan"a gitmez, "hangisi?" diye sorulur. Adın eki atılır: kesme işareti
varsa ondan sonrası ("Ahmet'e" → "Ahmet"), yoksa sondaki tek bir yaygın ek ("Anneme" → "Annem"); ekten arınmış ad
yalnızca tek bir kişinin tam adı ya da tam sözcüğüyse kabul edilir. Sonuç metinlerinde (günlüğe ve
ekrana da düşerler) telefon numarası yoktur: Alp videolarında ekranı paylaşıyor.
'''

from __future__ import annotations
import json
import re
import subprocess
import unicodedata
import urllib.parse
from pathlib import Path
from .. import paths, permissions
from ..memory import load_memory, update_memory
PREFERRED_BROWSERS = ['Google Chrome', 'Safari']
AUTO_SEND_DELAY_SECONDS = 2.4
PHONEBOOK_FILE = paths.PHONEBOOK_FILE

def _normalize_phone(phone_number: 'str') -> 'str':
    digits = re.sub('\\D+', '', phone_number or '')
    if len(digits) == 11 and digits.startswith('0'):
        digits = '90' + digits[1:]
    elif len(digits) == 10:
        digits = '90' + digits
    if len(digits) < 8 or len(digits) > 15:
        raise ValueError("Telefon numarası ülke koduyla ve eksiksiz olmalı (Türkiye'de +90 ile başlar). Kullanıcıya numarayı yeniden sor; örnek ya da tahmini bir numara kullanma.")
    return digits

def _normalize_lookup(text: 'str') -> 'str':
    text = (text or '').strip().casefold()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join((ch for ch in text if not unicodedata.combining(ch)))
    text = text.replace('ı', 'i')
    text = re.sub('\\s+', ' ', text)
    return text

_APOSTROPHE = re.compile("^(.+?)['’‘`´]([a-zçğıöşü]{1,6})$")
_SUFFIXES = ('nin', 'nun', 'den', 'dan', 'ten', 'tan', 'ye', 'ya', 'yi', 'yu', 'in', 'un', 'de', 'da', 'me', 'ma', 'mi', 'e', 'a', 'i', 'u', 'm')

def bare_name(name: 'str') -> 'str':
    '''Son sözcükte kesme işaretinden sonraki ek atılır: "Ahmet'e" → "Ahmet", "Ahmet Yılmaz'a" → "Ahmet Yılmaz".'''

    words = (name or '').split()
    match = _APOSTROPHE.match(words[-1]) if words else None
    if match:
        words[-1] = match.group(1)
    return ' '.join(words)

def _contact_key(name: 'str') -> 'str':
    return re.sub('[^a-z0-9]+', '_', _normalize_lookup(name)).strip('_') or 'contact'

def _load_contacts() -> 'dict':
    memory = load_memory()
    contacts = memory.get('whatsapp_contacts', {})
    if isinstance(contacts, dict):
        return contacts
    return {}

def _load_phone_book() -> 'dict':
    try:
        if PHONEBOOK_FILE.exists():
            return json.loads(PHONEBOOK_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return {}

def _save_phone_book(phone_book: 'dict'):
    PHONEBOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    PHONEBOOK_FILE.write_text(json.dumps(phone_book, indent=2, ensure_ascii=False), encoding='utf-8')

def _contact_candidates() -> 'list[dict]':
    candidates = []
    for source_name, source in ('whatsapp', _load_contacts()), ('phone_book', _load_phone_book()):
        if isinstance(source, dict):
            for key, entry in source.items():
                if isinstance(entry, dict):
                    item = dict(entry)
                    item.setdefault('display_name', key)
                    item['_source'] = source_name
                    item['_key'] = key
                    candidates.append(item)
    return candidates

def _match_score(needle: 'str', candidate: 'str') -> 'int':
    candidate_norm = _normalize_lookup(candidate)
    if not candidate_norm:
        return 0
    if candidate_norm == needle:
        return 300
    if candidate_norm.startswith(needle) or needle.startswith(candidate_norm):
        return 220
    if needle in candidate_norm:
        return 160
    needle_parts = needle.split()
    if needle_parts:
        if all((part in candidate_norm for part in needle_parts)):
            return 120
    return 0

def _find_contact(recipient_name: 'str') -> 'dict | None':
    '''Gevşek eşleşme: yalnızca kayıt güncellerken mevcut takma adları bulmak için (mesaj göndermede find_contact).'''

    needle = _normalize_lookup(recipient_name)
    if not needle:
        return
    best_match = None
    best_score = 0
    for entry in _contact_candidates():
        names = [entry.get('display_name', ''), entry.get('_key', '')]
        aliases = entry.get('aliases', [])
        if isinstance(aliases, list):
            names.extend((str(alias) for alias in aliases))
        elif aliases:
            names.append(str(aliases))
        for name in names:
            score = _match_score(needle, name)
            if score > best_score:
                best_score = score
                best_match = entry
    return best_match

def _people() -> 'list[tuple[str, dict, list[str]]]':
    '''Kayıtlı kişiler: (görünen ad, kayıt, karşılaştırılacak adları: ad, anahtar, takma adlar; normalleştirilmiş).'''

    people = []
    for entry in _contact_candidates():
        display = str(entry.get('display_name') or entry.get('_key') or '').strip()
        aliases = entry.get('aliases', [])
        names = [display, str(entry.get('_key', ''))] + ([str(a) for a in aliases] if isinstance(aliases, list) else [str(aliases)] if aliases else [])
        names += [n for n in map(bare_name, names) if n not in names]
        people.append((display, entry, [c for c in (_normalize_lookup(n.replace('_', ' ')) for n in names) if c]))
    return people

def _hits(needle: 'str', people: 'list[tuple[str, dict, list[str]]]') -> 'tuple[dict[str, tuple[int, dict]], set[str]]':
    '''Adın tam (2) ya da tam sözcük (1) tuttuğu kişiler {görünen ad: (puan, kişi)} ve yalnızca içinde geçtiği adlar.'''

    words = needle.split()
    best = {}
    loose = set()
    for display, entry, names in people:
        for cand in names:
            score = 2 if cand == needle else 1 if all((w in cand.split() for w in words)) else 0
            if score:
                if not score > best.get(display, (0, {}))[0]:
                    continue
                best[display] = score, entry
            elif needle in cand or cand in needle:
                loose.add(display)
    return best, loose

def _pick(best: 'dict[str, tuple[int, dict]]') -> 'tuple[dict | None, list[str]]':
    '''En yüksek puanlı tek kişi; birden çoksa (None, adları).'''

    top = max((score for score, _entry in best.values()))
    hits = [(display, entry) for display, (score, entry) in best.items() if score == top]
    if len(hits) == 1:
        return hits[0][1], []
    return None, sorted((display for display, _entry in hits))

def find_contact(name: 'str') -> 'tuple[dict | None, list[str]]':
    '''(kişi, benzer adlar). Yalnızca tam ad/takma ad ya da tam sözcük eşleşmesi kabul edilir; birden çok kişi
    eşleşirse ya da yalnızca sözcük içinde geçiyorsa (Can → Ercan) kişi None, benzer adlar döner.

    Tutmazsa ek atılır: kesme işareti varsa yalnızca ondan sonrası ("Ahmet'e" → "Ahmet"; "Emine'ye" "Emin" olmaz),
    yoksa sondaki tek bir yaygın ek ("Anneme" → "Annem", "Ahmete" → "Ahmet"). Ek atılarak bulunan kişi yalnızca tek
    kişiyse kabul edilir ve "_stripped" işaretiyle döner ("Emine" kayıtlı "Emin"e de uyar; Mac önce Rehber'de adın
    kendisine bakar).'''

    needle = _normalize_lookup(re.sub('[’‘`´]', "'", name or ''))
    if not needle:
        return None, []
    people = _people()
    best, loose = _hits(needle, people)
    if best:
        return _pick(best)
    bare = bare_name(needle) or needle
    if bare != needle:
        best, more = _hits(bare, people)
        if best:
            return _pick(best)
        return None, sorted(loose | more)
    head, _, last = needle.rpartition(' ')
    stemmed = {}
    for suffix in _SUFFIXES:
        if not last.endswith(suffix) or len(last) - len(suffix) < 3:
            continue
        found, _loose = _hits(f'{head} {last[:-len(suffix)]}'.strip(), people)
        for display, (score, entry) in found.items():
            if score > stemmed.get(display, (0, {}))[0]:
                stemmed[display] = score, entry
    if stemmed:
        contact, similar = _pick(stemmed)
        if contact:
            return dict(contact, _stripped=True), []
        loose |= set(similar)
    return None, sorted(loose)

def _saved_contact(name: 'str') -> 'tuple[str, dict] | tuple[None, None]':
    """JARVIS'in kendi kayıtlarında (içe aktarılan rehber değil) adı, görünen adı ya da takma adı tam uyan tek kişi."""

    want = _normalize_lookup(name)
    hits = [(key, entry) for key, entry in _load_contacts().items()
         if isinstance(entry, dict)
         if key == _contact_key(name)
         if _normalize_lookup(str(entry.get('display_name', ''))) == want
         if any((_normalize_lookup(str(a)) == want for a in entry.get('aliases', []) or []))]
    if len(hits) == 1:
        return hits[0]
    return (None, None)

def save_whatsapp_contact(display_name: 'str', phone_number: 'str'='', aliases: 'str'='') -> 'str':
    display_name = bare_name((display_name or '').strip())
    if not display_name:
        return 'Hata: kişi adı boş olamaz.'
    alias_list = []
    if aliases and aliases.strip():
        alias_list = [part.strip() for part in aliases.split(',') if part.strip()]
    if not (phone_number or '').strip():
        key, entry = _saved_contact(display_name)
        if entry is None:
            return f"Hata: '{display_name}' JARVIS'in kayıtlı kişileri arasında yok; yeni kişi için telefon numarası gerekli. Kullanıcıya numarayı sor."
        merged = list(dict.fromkeys([*(str(a) for a in entry.get('aliases', []) or []), *alias_list]))
        shown = str(entry.get('display_name') or display_name)
        update_memory({'whatsapp_contacts': {key: {'value': entry.get('value', ''), 'display_name': shown, 'aliases': merged}}})
        return f'{shown} kaydı güncellendi (numarası aynı). Takma adlar: {', '.join(merged) or 'yok'}'
    try:
        normalized_phone = _normalize_phone(phone_number)
    except ValueError as exc:
        return f'Hata: {exc}'
    key = _contact_key(display_name)
    update_memory({'whatsapp_contacts': {key: {'value': f'+{normalized_phone}', 'display_name': display_name.strip(), 'aliases': alias_list}}})
    if alias_list:
        return f'{display_name.strip()} WhatsApp kişilerine kaydedildi. Takma adlar: {', '.join(alias_list)}'
    return f'{display_name.strip()} WhatsApp kişilerine kaydedildi.'

def _unfold_vcf_lines(text: 'str') -> 'list[str]':
    unfolded = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip('\r\n')
        if line.startswith((' ', '\t')) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded

def import_phone_book_from_vcf(vcf_path: 'str') -> 'str':
    source = Path(vcf_path).expanduser()
    if not source.exists():
        return f'Rehber dosyası bulunamadı: {source}'
    try:
        text = source.read_text(encoding='utf-8', errors='ignore')
    except Exception as exc:
        return f'Rehber dosyası okunamadı: {exc}'
    entries = {}
    current_lines = []
    imported = 0
    skipped = 0
    def _flush_card(lines: 'list[str]'):
        nonlocal skipped, imported
        if not lines:
            return
        display_name = ''
        aliases = []
        numbers = []
        for line in lines:
            upper = line.upper()
            if upper.startswith('FN:'):
                display_name = line.split(':', 1)[1].strip()
                continue
            if upper.startswith('N:'):
                if not display_name:
                    parts = [part.strip() for part in line.split(':', 1)[1].split(';') if part.strip()]
                    if not parts:
                        continue
                    display_name = ' '.join(reversed(parts[:2])).strip()
                    continue
            if 'TEL' not in upper:
                continue
            if ':' not in line:
                continue
            number = line.split(':', 1)[1].strip()
            if not number:
                continue
            numbers.append(number)
            continue
        if not display_name or not numbers:
            skipped += 1
            return
        normalized_numbers = []
        for raw_number in numbers:
            try:
                normalized_numbers.append('+' + _normalize_phone(raw_number))
            except ValueError:
                continue
        if not normalized_numbers:
            skipped += 1
            return
        if ' ' in display_name:
            aliases.extend((part for part in display_name.split() if len(part) > 1))
        key = _contact_key(display_name)
        entries[key] = {'display_name': display_name, 'value': normalized_numbers[0], 'numbers': normalized_numbers, 'aliases': sorted({alias for alias in aliases if _normalize_lookup(alias) != _normalize_lookup(display_name)}), 'source': 'vcf_import'}
        imported += 1

    for line in _unfold_vcf_lines(text):
        if line.upper() == 'BEGIN:VCARD':
            current_lines = []
        elif line.upper() == 'END:VCARD':
            _flush_card(current_lines)
            current_lines = []
        else:
            current_lines.append(line)
    phone_book = _load_phone_book()
    phone_book.update(entries)
    _save_phone_book(phone_book)
    return f'{imported} rehber kişisi içe aktarıldı, {skipped} kayıt atlandı.'

def _contacts_lookup(name: 'str') -> 'tuple[list[tuple[str, str]], str]':
    """Rehber'de ada göre kişiler → ([(ad, numara)], sorun). İzin sorulmadıysa macOS sorar."""

    try:
        import Contacts
    except ImportError:
        return [], 'Rehber okunamıyor.'
    store = Contacts.CNContactStore.alloc().init()
    status = Contacts.CNContactStore.authorizationStatusForEntityType_(Contacts.CNEntityTypeContacts)
    if status == Contacts.CNAuthorizationStatusNotDetermined:
        if permissions.request('contacts') != 'granted':
            return [], 'Rehber izni verilmedi.'
    if status not in (Contacts.CNAuthorizationStatusAuthorized, getattr(Contacts, 'CNAuthorizationStatusLimited', 4)):
        return [], 'Rehber izni kapalı (Ayarlar › İZİNLER › REHBER).'
    keys = [Contacts.CNContactGivenNameKey, Contacts.CNContactFamilyNameKey, Contacts.CNContactNicknameKey, Contacts.CNContactOrganizationNameKey, Contacts.CNContactPhoneNumbersKey]
    found = {}
    for query in dict.fromkeys([name.strip(), name.strip().split()[0] if name.strip() else '']):
        if not query:
            continue
        predicate = Contacts.CNContact.predicateForContactsMatchingName_(query)
        people, _error = store.unifiedContactsMatchingPredicate_keysToFetch_error_(predicate, keys, None)
        for person in people or []:
            numbers = list(person.phoneNumbers() or [])
            if not numbers:
                pass
        continue
        numbers.sort(key=(lambda n: 0 if re.search('mobile|iphone|cep', str(n.label() or ''), re.I) else 1))
        label = ' '.join((x for x in (str(person.givenName() or ''), str(person.familyName() or '')) if x)) or str(person.nickname() or '') or str(person.organizationName() or '')
        found[str(person.identifier())] = label, str(numbers[0].value().stringValue())
        continue
        if found:
            break
    words = _normalize_lookup(name).split()
    people = list(found.values())
    exact = [p for p in people if all((w in _normalize_lookup(p[0]).split() for w in words))]
    if exact or not people:
        return exact, ''
    return [], 'similar:' + ', '.join((label for label, _phone in people[:5]))

def _run_osascript(script: 'str', timeout: 'int'=18) -> 'tuple[bool, str]':
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, f'AppleScript çalıştırılamadı: {exc}'
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip() or 'Bilinmeyen AppleScript hatası'
        return False, permissions.describe_failure(detail)
    return True, (result.stdout or '').strip()

def _open_in_browser(url: 'str') -> 'str':
    for app_name in PREFERRED_BROWSERS:
        result = subprocess.run(['open', '-a', app_name, url], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            continue
        return app_name
    subprocess.run(['open', url], check=False, timeout=10)
    return 'default browser'

def _auto_send_with_osascript(app_name: 'str') -> 'tuple[bool, str]':
    need = permissions.require_accessibility()
    if need:
        return False, need
    script = f'delay {AUTO_SEND_DELAY_SECONDS}\ntell application "{app_name}" to activate\ndelay 0.3\ntell application "System Events"\n    key code 36\nend tell\n'
    return _run_osascript(script, timeout=12)

def _open_whatsapp_desktop_via_scheme(phone_number: 'str', message: 'str') -> 'tuple[bool, str]':
    encoded_message = urllib.parse.quote(message.strip())
    url = f'whatsapp://send?phone={phone_number}&text={encoded_message}'
    try:
        result = subprocess.run(['open', url], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return False, f'WhatsApp Desktop açılamadı ({type(exc).__name__}).'
    if result.returncode != 0:
        return False, f'WhatsApp Desktop açılamadı (open kodu {result.returncode}).'
    return (True, 'WhatsApp Desktop sohbeti açıldı.')

_SEND_AND_CHECK = '\non run argv\n    set wanted to item 1 of argv\n    tell application "WhatsApp" to activate\n    tell application "System Events"\n        tell process "WhatsApp"\n            set box to missing value\n            repeat 60 times\n                try\n                    set f to value of attribute "AXFocusedUIElement"\n                    if (value of f) contains wanted then\n                        set box to f\n                        exit repeat\n                    end if\n                end try\n                delay 0.2\n            end repeat\n            if box is missing value then return "taslak-yok"\n            key code 36\n            delay 1.2\n            try\n                if (value of box) contains wanted then return "duruyor"\n            on error\n                return "belirsiz"\n            end try\n            return "gönderildi"\n        end tell\n    end tell\nend run\n'

def _send_in_desktop(message: 'str') -> 'tuple[str, str]':
    '''Açık sohbette Enter ve doğrulama → (sonuç, ayrıntı).'''

    need = permissions.require_accessibility()
    if need:
        return 'izin', need
    wanted = ' '.join(message.split())[:24]
    try:
        result = subprocess.run(['osascript', '-e', _SEND_AND_CHECK, wanted], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return ('belirsiz', 'WhatsApp yanıt vermedi.')
    if result.returncode != 0:
        return 'hata', permissions.describe_failure((result.stderr or result.stdout or '').strip())
    return (result.stdout or '').strip(), ''

def _open_whatsapp_web(phone_number: 'str', message: 'str') -> 'tuple[bool, str]':
    encoded_message = urllib.parse.quote(message.strip())
    url = f'https://web.whatsapp.com/send?phone={phone_number}&text={encoded_message}'
    try:
        app_name = _open_in_browser(url)
    except Exception as exc:
        return False, f'WhatsApp Web açılamadı ({type(exc).__name__}).'
    return True, app_name

def _desktop_installed() -> 'bool':
    return any((Path(p).exists() for p in ('/Applications/WhatsApp.app', str(Path.home() / 'Applications/WhatsApp.app'))))

def send_whatsapp_message(message: 'str', phone_number: 'str'='', recipient_name: 'str'='', send_now: 'bool'=False, app_target: 'str'='auto') -> 'str':
    if not message or not message.strip():
        return 'Mesaj boş olamaz.'
    app_target = (app_target or 'auto').strip().lower()
    if app_target not in {'web', 'auto', 'desktop'}:
        app_target = 'auto'
    normalized_phone = ''
    if phone_number and phone_number.strip():
        try:
            normalized_phone = _normalize_phone(phone_number)
        except ValueError as exc:
            return str(exc)
    asked = (recipient_name or '').strip()
    resolved_name = bare_name(asked)
    source_note = ''
    if resolved_name and normalized_phone:
        contact, _similar = find_contact(asked)
        if contact and contact.get('_stripped'):
            contact = None
        aliases = ', '.join((str(a) for a in (contact or {}).get('aliases', []) or []))
        save_whatsapp_contact(resolved_name, normalized_phone, aliases=aliases)
    elif resolved_name:
        contact, similar = find_contact(asked)
        rehber = None
        if contact and contact.get('_stripped'):
            rehber = _contacts_lookup(resolved_name)
            if rehber[0]:
                contact = None
        if contact:
            try:
                normalized_phone = _normalize_phone(str(contact.get('value', '')))
                resolved_name = str(contact.get('display_name', resolved_name)).strip() or resolved_name
            except ValueError:
                normalized_phone = ''
        elif similar:
            shown = ', '.join(similar[:5])
            return f"'{resolved_name}' adında tam eşleşen kayıtlı kişi yok; benzer kayıtlı adlar: {shown}. Kullanıcıya hangisini kastettiğini sor; söyleyince recipient_name'i tam o adla yeniden çağır. Hiçbir şey açılmadı."
        if not normalized_phone:
            people, problem = rehber or _contacts_lookup(resolved_name)
            if problem.startswith('similar:'):
                return f"Rehber'de '{resolved_name}' adında tam eşleşen kişi yok; benzer adlar: {problem[8:]}. Kullanıcıya hangisini kastettiğini sor, sonra tam adıyla yeniden gönder. Hiçbir şey açılmadı."
            if len(people) > 1:
                names = ', '.join((name for name, _phone in people[:6]))
                return f"Rehber'de '{resolved_name}' adına uyan birden çok kişi var: {names}. Kullanıcıya hangisi olduğunu sor, sonra tam adıyla yeniden gönder."
            if people:
                resolved_name, number = people[0]
                try:
                    normalized_phone = _normalize_phone(number)
                    source_note = " (Rehber'den)"
                except ValueError:
                    return f"Rehber'deki {resolved_name} kaydının numarası anlaşılamadı. Kullanıcıya numarayı sor; numarayı sesli tekrar etme."
            else:
                why = f' ({problem})' if problem else ''
                return f"'{resolved_name}' için numara bulamadım: kayıtlı kişilerde ve Mac'in Rehber'inde yok{why}. Kullanıcıya bu kişinin telefon numarasını sor; söyleyince mesajı phone_number ve recipient_name ile yeniden gönder (numara adıyla kaydedilir, bir dahaki sefere sorman gerekmez). Numarayı sesli tekrar etme."
    if not normalized_phone:
        return 'WhatsApp mesajı için kişi adı veya telefon numarası gerekli.'
    label = f'{resolved_name or 'verilen numara'}{source_note}'
    if app_target != 'web' and _desktop_installed():
        ok, detail = _open_whatsapp_desktop_via_scheme(normalized_phone, message)
        if not ok:
            return f'WhatsApp açılamadı: {detail}'
        if not send_now:
            return f"WhatsApp'ta {label} sohbeti mesaj yazılmış olarak açıldı; göndermek için Enter'a basılmalı."
        outcome, detail = _send_in_desktop(message)
        if outcome == 'gönderildi':
            return f'WhatsApp üzerinden {label} kişisine mesaj gönderildi (doğrulandı).'
        if outcome == 'taslak-yok':
            return f"WhatsApp'ta {label} sohbeti açılmadı; numara WhatsApp'ta olmayabilir ya da WhatsApp yanıt vermedi. Mesaj GÖNDERİLMEDİ."
        if outcome == 'duruyor':
            return f"WhatsApp'ta {label} sohbeti açıldı ama mesaj gönderilemedi; yazma kutusunda duruyor. Mesaj GÖNDERİLMEDİ."
        if outcome == 'belirsiz':
            return f"WhatsApp'ta {label} sohbetinde Enter'a bastım ama gönderildiğini doğrulayamadım. {detail}".strip()
        return f"WhatsApp'ta {label} sohbeti açıldı ama gönderemedim. {detail}".strip()
    ok, detail = _open_whatsapp_web(normalized_phone, message)
    if not ok:
        return detail
    if not send_now:
        return f"WhatsApp Web {detail} içinde {label} için mesaj yazılmış olarak açıldı. Göndermek için Enter'a bas."
    ok_send, send_detail = _auto_send_with_osascript(detail if detail in PREFERRED_BROWSERS else 'Google Chrome')
    if ok_send:
        return f"WhatsApp Web'de {label} sohbetinde gönder tuşuna bastım; tarayıcıda gönderildiğini doğrulayamıyorum, kullanıcıya bakmasını söyle."
    return f"WhatsApp Web'de {label} sohbeti mesajla açıldı ama gönder tuşuna basamadım; mesaj taslak olarak duruyor. {send_detail}"


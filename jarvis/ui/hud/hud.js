/* JARVIS V4 — HUD.

   Python bu sayfayla yalnızca `window.jarvis.*` üzerinden konuşur; sayfa da
   Python'a `send(tür, veri)` ile yazar (pywebview köprüsü). Görünüşün tamamı
   burada ve hud.css'te, Python'a dokunmadan değiştirilebilir.

   Halka, aletler (meter, weatherPlate) ve hareket kuralları Friday'in
   HUD'ından (Arthur Kes) uyarlandı.
*/
"use strict";

const body = document.body;
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
function S(tag, attrs){ const e = document.createElementNS(NS, tag);
  for(const k in (attrs || {})) e.setAttribute(k, attrs[k]); return e; }
function el(tag, cls, text){ const e = document.createElement(tag);
  if(cls) e.className = cls; if(text != null) e.textContent = text; return e; }

/* ---------------- köprü ---------------- */
function send(kind, data){
  const payload = Object.assign({}, data || {});
  try{
    if(window.pywebview && window.pywebview.api) return window.pywebview.api.post(kind, payload);
  }catch(e){ console.error(e); }
  if(window.__mockSend) window.__mockSend(kind, payload);
}

/* ---------------- durum ---------------- */
let THEMES = {};           // key → tema (Python personas.theme())
let THEME = null;
let PAGE = "";             // açık sayfa (overlay kimliği; pageChanged Python'a bildirir)
// Çip adları (jarvis/brand.py): kullanıcı JARVIS ile FRIDAY'e kendi adını verebilir. Ad ve ekli hâlleri temadan
// gelir (forms: gen "KAAN'IN", acc "KAAN'I", dat "KAAN'A", de "KAAN da"); ek, adın son sesine göre Python'da seçilir.
const chipName = key => (THEMES[key] && THEMES[key].name) || String(key || "").toUpperCase();
const chipForm = (key, form) => (THEMES[key] && THEMES[key].forms && THEMES[key].forms[form]) || chipName(key);
// index.html'deki hazır yazılarda çipin adı: <b data-chip-name="jarvis">JARVIS</b>
function syncChipNames(){
  for(const n of document.querySelectorAll("[data-chip-name]")) n.textContent = chipName(n.dataset.chipName);
}
let STATE = "connecting";
let SETTINGS = {};
// İşletim sistemi (Python _init_payload): "mac" | "win". index.html'deki .only-mac/.only-win metinleri
// body[data-os]'a göre gizlenir (hud.css); JS'teki metinler de buna bakar.
let OS = "mac";
let PERM_ROWS = null;      // bu işletim sisteminde gösterilen izin satırları (Python permissions.rows)
const LABEL = {connecting:"BAĞLANIYOR", listening:"DİNLİYOR", thinking:"DÜŞÜNÜYOR",
               speaking:"KONUŞUYOR", idle:"BEKLEMEDE", paused:"SESSİZ", error:"HATA", asleep:"UYKUDA"};
const BREATH = {idle:"4.6s", paused:"6s", connecting:"2.3s", listening:"1.5s", thinking:"2.3s", speaking:".62s"};
const SPIN = {idle:"48s", paused:"70s", connecting:"12s", listening:"20s", thinking:"9s", speaking:"14s"};
const GAIN = {idle:1, paused:.6, connecting:1.1, listening:1.35, thinking:1.15, speaking:1.6, error:.8, asleep:.4};
let SLEEP = false;         // orba dokununca: oturum kapanır, halka söner ve durur
// Bağlantı sorunu sürerken (yeniden deneme döngüsü) düşünme sesi çalmaz, hata sesi bir kez çalar: eskiden her
// denemede (6 sn'de bir) ikisi de baştan başlıyordu.
let FAILING = false, ERR_PLAYED = false, CONNECT_AT = 0;
// Bağlantı sorunu sürerken sohbete düşen açıklama: üstteki "HATA · <neden>"e basınca yeniden gösterilir.
let ERR_LINE = "";
let CAM = false;

function hexRgb(h){ const n = parseInt(String(h).slice(1), 16); return `${n>>16&255},${n>>8&255},${n&255}`; }

function stateColour(state){
  const p = THEME ? THEME.palette : {};
  if(RUINS && THEME && THEME.key === "ultron") return state === "speaking" ? RUINED.speaking : state === "error" ? p.error : RUINED.idle;  // [-hikaye]
  if(state === "connecting") return p.thinking || "#FFA63C";
  if(state === "paused" || state === "asleep") return p.dim || "#5E7C8C";
  return p[state] || p.idle || "#5ED8FF";
}

function paint(){
  if(!THEME) return;
  const r = document.documentElement.style, p = THEME.palette, c = stateColour(STATE);
  r.setProperty("--c", c); r.setProperty("--rgb", hexRgb(c));
  r.setProperty("--accent", p.accent); r.setProperty("--arg", hexRgb(p.accent));
  r.setProperty("--deep", p.deep); r.setProperty("--ink", p.ink);
  r.setProperty("--dim", p.dim); r.setProperty("--faint", p.faint);
  r.setProperty("--prgb", hexRgb(p.idle));
  r.setProperty("--breath", BREATH[STATE] || "4.6s");
  r.setProperty("--spin", SPIN[STATE] || "48s");
  if(RUINS){ r.setProperty("--accent", RUINED.accent); r.setProperty("--arg", hexRgb(RUINED.accent)); r.setProperty("--prgb", hexRgb(RUINED.idle)); }  // [-hikaye]
  if(RING) RING.colour(c);
}

function applyPersona(key){
  const t = THEMES[key];
  if(!t) return;
  const changed = !THEME || THEME.key !== t.key;
  THEME = t;
  body.dataset.persona = t.key;
  if(t.key !== "ultron" && PANELS.authority) removePanel("authority");   // yetki paneli yalnızca ULTRON'da  // [-hikaye]
  $("mark").textContent = t.name;
  document.title = t.name;
  $("set-persona-name").textContent = t.name;
  if(changed) buildRing(t);
  paint();
  markCards();
  if(t.key !== "ultron" && AWAKE) endAwake();  // [-hikaye]
  syncWarn();  // [-hikaye]
}

/* =======================================================================
   HALKA — kişiliğe göre karakter değiştiren canlı çekirdek.
   Yarıçap birkaç harmoniğin toplamı; yalnızca faz ilerler, yerleşim hiç
   değişmez. Keskin kişilikte (ULTRON) sinüs yerine üçgen dalga ve düz
   çizgiler kullanılır.
   ======================================================================= */
let RING = null;

function ringPath(cx, cy, r, amp, hs, phase, sharp){
  const N = sharp ? 96 : 120, pts = [];
  for(let i = 0; i < N; i++){
    const a = i / N * Math.PI * 2;
    let d = 0;
    for(const h of hs){
      const w = Math.sin(a * h.k + phase * h.s + h.p);
      d += (sharp ? (2 / Math.PI) * Math.asin(w) : w) * h.a;
    }
    const rr = r + d * amp;
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
  }
  if(sharp) return "M" + pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L") + "Z";
  let out = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for(let i = 0; i < N; i++){
    const p0 = pts[(i-1+N)%N], p1 = pts[i], p2 = pts[(i+1)%N], p3 = pts[(i+2)%N];
    out += `C${(p1[0]+(p2[0]-p0[0])/6).toFixed(2)},${(p1[1]+(p2[1]-p0[1])/6).toFixed(2)} `
         + `${(p2[0]-(p3[0]-p1[0])/6).toFixed(2)},${(p2[1]-(p3[1]-p1[1])/6).toFixed(2)} `
         + `${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return out + "Z";
}

/* Görüntü kalitesi (Ayarlar › Genel). Halkanın SVG bulanıklıkları her karede işlemcide yeniden hesaplanıyordu:
   arayüzü çizen süreç boşta tek başına bir çekirdekten fazlasını yiyordu (Mac'te ~%125, ölçüldü). Artık YÜKSEK'te
   bulanıklık ekran kartında (CSS süzgeci, ~%30 toplam); PERFORMANS'ta hiç bulanıklık yok, dönen halkalar durur. */
const LITE = () => SETTINGS.render_quality === "low";

function buildRing(theme){
  const host = $("core");
  host.replaceChildren();
  const size = 1000, c = size / 2, ring = theme.ring, sharp = ring.style === "sharp", lite = LITE();
  // Her katman ayrı bir <svg>: dönen ve nefes alan katmanlar ekran kartında döner; her karede yalnızca kabukların
  // katmanı yeniden çizilir.
  const orb = el("div", "orb");
  host.appendChild(orb);
  const layer = (attrs = {}) => { const v = S("svg", {viewBox:`0 0 ${size} ${size}`, ...attrs}); orb.appendChild(v); return v; };
  const soft = sharp ? 4 : 8;

  // YÜKSEK'te bulanıklık SVG süzgeci değil, katmanın CSS süzgeci (hud.css › svg.soft): ekran kartında yapılır.
  // σ 1000 birimlik çizimde soft birim; CSS onu halkanın ekrandaki boyuna göre piksele çevirir.
  const cssBlur = svg => { svg.classList.add("soft"); svg.style.setProperty("--sd", soft); };
  // kabuklar: PERFORMANS'ta parlama, altta geniş ve soluk bir çizgiyle taklit edilir
  const shellSvg = layer();
  if(!lite) cssBlur(shellSvg);
  const shells = ring.shells.map(([r, amp, op], i) => {
    const w = i === 0 ? 1.8 : 1.2, join = sharp ? "miter" : "round";
    let glow = null;
    if(lite){
      glow = S("path", {fill:"none", stroke:"currentColor", "stroke-width": w * 14, "stroke-opacity": op * .09,
        "stroke-linejoin": join, "data-glow": i});
      shellSvg.appendChild(glow);
    }
    const node = S("path", {fill:"none", stroke:"currentColor", "stroke-width": lite ? w * 4.5 : w,
      "stroke-opacity": lite ? op * .2 : op, "stroke-linejoin": join, "data-shell": i});
    shellSvg.appendChild(node);
    return {node, glow, r, amp, h: ring.harmonics[i]};
  });

  const ticks = layer({class:"spin-s"});
  for(let i = 0; i < 90; i++){
    const a = i / 90 * Math.PI * 2, long = i % 5 === 0, r1 = 372, r2 = r1 + (long ? 15 : 7);
    ticks.appendChild(S("line", {x1:c+Math.cos(a)*r1, y1:c+Math.sin(a)*r1, x2:c+Math.cos(a)*r2, y2:c+Math.sin(a)*r2,
      stroke:"currentColor", "stroke-opacity": long ? .5 : .2, "stroke-width": long ? 1.5 : 1}));
  }

  const arc = (r, from, len, colour, w, cls) => {
    const svg = layer({class:cls}), a0 = from * Math.PI / 180, a1 = (from + len) * Math.PI / 180;
    const d = `M${c+Math.cos(a0)*r},${c+Math.sin(a0)*r} A${r},${r} 0 ${len > 180 ? 1 : 0} 1 ${c+Math.cos(a1)*r},${c+Math.sin(a1)*r}`;
    const line = {d, fill:"none", stroke:colour, "stroke-linecap":"round"};
    if(lite){
      svg.appendChild(S("path", {...line, "stroke-width": w * 7, "stroke-opacity": .12}));
      svg.appendChild(S("path", {...line, "stroke-width": w * 2.4, "stroke-opacity": .3}));
    }else{
      svg.appendChild(S("path", {...line, "stroke-width": w, "stroke-opacity": .95}));
      cssBlur(svg);
    }
    return svg;
  };
  let accent = theme.palette.accent;
  if(RUINS && theme.key === "ultron") accent = RUINED.accent;     // harabe: sarı yay pas rengi  // [-hikaye]
  arc(400, 150, 120, "currentColor", 3, "spin-m");
  arc(418, 20, 62, accent, 2, "spin-f");

  // çekirdek: ortadaki parlak daire bulanıklık yerine aynı görünümde bir ışınsal geçişle (iki kalitede de)
  const pulse = layer({id:"pulse"});
  const defs = S("defs");
  const glow = S("radialGradient", {id:"g-core"});
  const stops = [["0%", .95], ["30%", .85], ["60%", .35], ["100%", 0]].map(([o, op]) => {
    const st = S("stop", {offset:o, "stop-opacity":op}); glow.appendChild(st); return st; });
  defs.appendChild(glow);
  const midGlow = S("radialGradient", {id:"g-mid"});
  const midStops = [["0%", .95], ["45%", .8], ["75%", .3], ["100%", 0]].map(([o, op]) => {
    const st = S("stop", {offset:o, "stop-opacity":op}); midGlow.appendChild(st); return st; });
  defs.appendChild(midGlow);
  pulse.appendChild(defs);
  pulse.appendChild(S("circle", {cx:c, cy:c, r:150, fill:"url(#g-core)"}));
  pulse.appendChild(S("circle", {cx:c, cy:c, r:92, fill:"url(#g-mid)"}));
  pulse.appendChild(S("circle", {cx:c, cy:c, r:ring.core || 26, fill:"#FFFFFF", "fill-opacity":.92}));

  const hit = el("div", "hit");
  hit.title = "Uyut / uyandır";
  hit.addEventListener("click", () => {
    if(RUINS) return Ruins.touch();       // harabe: uyku yok, ULTRON kısa bir söz söyler  // [-hikaye]
    setSleep(!SLEEP);
  });
  host.appendChild(hit);

  RING = {
    shells, sharp, lite, speed: ring.speed || 1,
    colour(col){
      stops[0].setAttribute("stop-color", "#FFFFFF");
      for(const st of stops.slice(1)) st.setAttribute("stop-color", col);
      for(const st of midStops) st.setAttribute("stop-color", col);
    },
  };
}

let phase = 0, lastFrame = performance.now(), lastDraw = 0;
let CHAINS_ON = false, MIRROR = null;  // [-hikaye]
// Harabe (Ruins): kötü sondan on iki yıl sonra. ULTRON sönük kırmızı, konuşunca canlanır; yayı pas rengi  // [-hikaye]
// (telefondaki Persona.ruined).  // [-hikaye]
let RUINS = false;  // [-hikaye]
const RUINED = {idle: "#A8322A", dim: "#9A2E27", speaking: "#D9483C", accent: "#8A4B22"};  // [-hikaye]
/* Isınma (Windows'ta ölçüldü, boşta, YÜKSEK KALİTE: toplam iş -%31, pencere arka plandayken -%51; PERFORMANS -%34):
   - Sürekli dönen CSS animasyonları (dönen halkalar, çekirdeğin nefesi, saat halkası, yanıp sönen noktalar, sahnelerin
     döngüleri) duraklatılıp halkanın kabuklarıyla aynı adımda ilerletilir; görünüm aynı. Bir kez biten animasyonlar
     (açılış, geçiş) olduğu gibi kalır.
   - Döngü yalnızca çizim zamanı gelince uyanır; pencere arka plandayken (başka uygulamadasın) adım seyrekleşir. */
let animAt = performance.now(), FOCUSED = document.hasFocus();
const STEPPED = new WeakSet();
addEventListener("focus", () => { FOCUSED = true; });
addEventListener("blur", () => { FOCUSED = false; });
function stepAnims(now){
  const d = Math.min(250, now - animAt); animAt = now;
  for(const a of document.getAnimations()){
    if(!(a instanceof CSSAnimation)) continue;
    const e = a.effect, t = e && e.target;
    if(!t || e.getTiming().iterations !== Infinity) continue;
    if(!STEPPED.has(a)){ a.pause(); STEPPED.add(a); }
    // CSS'in duraklattıkları (hud.css): uykuda halka, üzerine gelinen uyarı
    if(SLEEP && t.closest && t.closest("#core")) continue;
    if(t.id === "uwarn" && t.matches(":hover")) continue;
    a.currentTime = (a.currentTime || 0) + d;
  }
}
(function frame(now){
  const dt = Math.min(250, now - lastFrame); lastFrame = now;
  let live = RING && !SLEEP && document.visibilityState === "visible";
  // Ekranı kaplayan sahne varken arkadaki halka boşuna çizilmez; sahnede ULTRON'un çipi  // [-hikaye]
  // orba dönüştüyse onun kopyası (MIRROR) çizilir.  // [-hikaye]
  live = live && (!CHAINS_ON || MIRROR);  // [-hikaye]
  if(live) phase += dt / 1000 * RING.speed * (STATE === "speaking" ? 1.8 : 1);
  // Konuşurken saniyede 60, öbür durumlarda 30 kare: kabuklar yavaş döner, fark görünmez, iş yarıya iner.
  // PERFORMANS'ta 30 ve 20. Pencere arka plandayken (başka uygulamadasın) konuşmuyor/düşünmüyorsa 15.
  const speaking = STATE === "speaking";
  let every = LITE() ? (speaking ? 30 : 48) : (speaking ? 0 : 30);
  if(!FOCUSED && !speaking && STATE !== "thinking" && STATE !== "connecting") every = 64;
  if(now - lastDraw >= every - 8){          // uyandırma bir kare (8 ms) erken gelebilir
    lastDraw = now;
    stepAnims(now);
    if(live){
      let g = GAIN[STATE] || 1;
      if(RUINS && STATE !== "speaking") g = GAIN.paused;    // harabe: konuşmazken sönük  // [-hikaye]
      RING.shells.forEach((s, i) => {
        let m = s;
        if(CHAINS_ON) m = MIRROR[i];  // [-hikaye]
        const d = ringPath(500, 500, s.r, s.amp * g, s.h, phase, RING.sharp);
        if(m.node) m.node.setAttribute("d", d);
        if(m.glow) m.glow.setAttribute("d", d);
      });
    }
  }
  // Döngü yalnızca bir sonraki çizimin zamanı gelince uyanır: her ekran yenilemesinde (60/sn) boşuna uyanmak bile
  // WebView2'ye her seferinde bir kare hazırlatıyordu (Windows'ta ölçüldü: ~%16).
  const wait = every - (performance.now() - lastDraw);
  if(wait > 12) setTimeout(() => requestAnimationFrame(frame), wait - 8);
  else requestAnimationFrame(frame);
})(lastFrame);

/* =======================================================================
   PANELLER — her veri türünün kendi çizimi var (Friday'in "kutu değil,
   alet" ilkesi). Sol ve sağ sütun esnek kutu: üst üste binme imkânsız.
   ======================================================================= */
const WIDTHS = {time:250, system:250, camera:250, timer:250, notes:250,
                weather:290, calendar:300, reminders:300, map:300};
WIDTHS.authority = 250;  // [-hikaye]
const PANELS = {};          // key → düğüm

function arcPath(cx, cy, r, from, to){
  const a0 = (from - 90) * Math.PI / 180, a1 = (to - 90) * Math.PI / 180;
  return `M${(cx+Math.cos(a0)*r).toFixed(2)},${(cy+Math.sin(a0)*r).toFixed(2)} A${r},${r} 0 ${(to-from) > 180 ? 1 : 0} 1 `
       + `${(cx+Math.cos(a1)*r).toFixed(2)},${(cy+Math.sin(a1)*r).toFixed(2)}`;
}

function shell(m){
  const node = el("div", "mod");
  node.dataset.key = m.key;
  const inst = el("div", "inst");
  node.appendChild(inst);
  for(const corner of ["tl", "tr", "bl", "br"]) node.appendChild(el("div", "brk " + corner));
  return {node, inst};
}

/* Sayılar kendi değerlerine sayarak gelir. Pencere gizliyken rAF çalışmaz,
   o yüzden doğru değer her durumda kısa süre sonra ekrandadır. */
function countUp(node, value, ms){
  const target = Number(value) || 0, dur = ms || 900;
  const final = () => { node.textContent = String(Math.round(target)); };
  if(Math.abs(target) < 2 || document.visibilityState === "hidden"){ final(); return; }
  const started = performance.now(); let done = false;
  (function step(now){
    if(done) return;
    const t = Math.min(1, (now - started) / dur);
    node.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
    if(t < 1) requestAnimationFrame(step); else done = true;
  })(started);
  setTimeout(() => { if(!done){ done = true; final(); } }, dur + 250);
}

function tickRing(g, c, r, count, len, opacity, every, longLen){
  for(let i = 0; i < count; i++){
    const a = (i / count) * Math.PI * 2 - Math.PI / 2, long = every && i % every === 0;
    const l = long ? (longLen || len * 2.1) : len;
    g.appendChild(S("line", {x1:c+Math.cos(a)*r, y1:c+Math.sin(a)*r, x2:c+Math.cos(a)*(r+l), y2:c+Math.sin(a)*(r+l),
      stroke:"currentColor", "stroke-opacity": long ? opacity * 2.2 : opacity, "stroke-width": long ? 1.5 : 1}));
  }
}

function segmentArc(g, c, r, from, span, width, opacity, gap){
  const cells = Math.max(1, Math.round(span / (gap || 9)));
  for(let i = 0; i < cells; i++){
    const a0 = from + (span / cells) * i + 1.1, a1 = from + (span / cells) * (i + 1) - 1.1;
    if(a1 <= a0) continue;
    const p = S("path", {d:arcPath(c, c, r, a0, a1), fill:"none", stroke:"currentColor",
      "stroke-opacity":0, "stroke-width":width});
    p.animate([{strokeOpacity:0}, {strokeOpacity:opacity}], {duration:260, delay:i * 24, fill:"forwards"});
    g.appendChild(p);
  }
}

function rows(list){
  const box = el("div", "rows");
  for(const r of list){
    const line = el("div", r.past ? "past" : r.late ? "late" : "");
    line.append(el("em", null, r[0] ?? r.a), el("span", null, r[1] ?? r.b));
    box.appendChild(line);
  }
  return box;
}

/* ---- saat: günün ilerleyişi ve akan saniye ---- */
const TR_DAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];
const TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
let CLOCK = null;

function clockDial(m){
  const {node, inst} = shell(m);
  const W = 220, c = W / 2;
  const svg = S("svg", {viewBox:`0 0 ${W} ${W}`, width:"100%"});
  svg.style.maxWidth = "200px";
  const fine = S("g", {class:"rot-s"});
  tickRing(fine, c, 96, 60, 3.5, .18, 5, 8);
  svg.appendChild(fine);
  svg.appendChild(S("path", {d:arcPath(c, c, 78, 0, 359.9), fill:"none", stroke:"currentColor",
    "stroke-opacity":.1, "stroke-width":7}));
  const day = S("path", {fill:"none", stroke:"currentColor", "stroke-opacity":.85, "stroke-width":7});
  svg.appendChild(day);
  const hour = S("path", {fill:"none", stroke:"var(--accent)", "stroke-opacity":.9, "stroke-width":2});
  svg.appendChild(hour);
  const hand = S("g");
  hand.appendChild(S("line", {x1:c, y1:c - 60, x2:c, y2:c - 88, stroke:"currentColor", "stroke-width":2, "stroke-linecap":"round"}));
  hand.appendChild(S("circle", {cx:c, cy:c - 92, r:3, fill:"currentColor"}));
  hand.style.transformOrigin = `${c}px ${c}px`;
  hand.style.transition = "transform .35s cubic-bezier(.3,1.6,.5,1)";
  svg.appendChild(hand);
  const dial = el("div", "dial");
  const read = el("div", "mid");
  const box = el("div", "clockread");
  const hm = el("u"), date = el("div", "sub2");
  box.appendChild(hm); read.appendChild(box);
  dial.append(svg, read);
  inst.appendChild(dial);
  inst.appendChild(el("div", "lbl", m.label));
  inst.appendChild(date);
  CLOCK = {day, hour, hand, hm, date, c, sec: -1};
  tickClock();
  return node;
}

function tickClock(){
  try { Sync.tick(); } catch(e) { console.error(e); }  // hata verse de saat donmasın  // [-hikaye]
  const d = new Date(), hh = String(d.getHours()).padStart(2, "0"), mm = String(d.getMinutes()).padStart(2, "0");
  $("t-clock").textContent = `${hh}:${mm}`;           // saniyesiz (Alp, 5 Ekim)
  if(!CLOCK || !CLOCK.hm.isConnected) return;
  const c = CLOCK.c, dayFrac = (d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400;
  CLOCK.day.setAttribute("d", arcPath(c, c, 78, 0, Math.max(.5, dayFrac * 359.9)));
  CLOCK.hour.setAttribute("d", arcPath(c, c, 66, 0, Math.max(.5, (d.getMinutes() / 60) * 359.9)));
  // Windows'ta saniye ibresi yok (Alp, 12 Ekim: hatalı görünüyordu); Mac'te sürer
  if(OS === "win") CLOCK.hand.style.display = "none";
  else{
    // saniye ibresi hep ileri döner; 59→0 geçişinde geri sarmasın diye tur sayılır
    const turns = Math.floor(Date.now() / 60000);
    CLOCK.hand.style.transform = `rotate(${turns * 360 + d.getSeconds() * 6}deg)`;
  }
  CLOCK.hm.textContent = `${hh}:${mm}`;
  CLOCK.date.textContent = `${TR_DAYS[d.getDay()]} · ${d.getDate()} ${TR_MONTHS[d.getMonth()]}`.toUpperCase();
}
setInterval(tickClock, 1000);

/* ---- sistem: radyal gösterge (Friday'in meter'ı) ---- */
function meter(m){
  const {node, inst} = shell(m);
  const W = 210, c = W / 2, SWEEP = 250, START = -125;
  const ratio = Math.max(0, Math.min(1, m.ratio ?? 0));
  const svg = S("svg", {viewBox:`0 0 ${W} ${W}`, width:"100%"});
  svg.style.maxWidth = "190px";
  svg.appendChild(S("path", {d:arcPath(c, c, 64, START, START + SWEEP), fill:"none", stroke:"currentColor",
    "stroke-opacity":.12, "stroke-width":10}));
  segmentArc(svg, c, 64, START, SWEEP * Math.max(ratio, .015), 10, .95, 7);
  for(let i = 0; i <= 20; i++){
    const a = (START + SWEEP * i / 20 - 90) * Math.PI / 180, long = i % 5 === 0;
    svg.appendChild(S("line", {x1:c+Math.cos(a)*76, y1:c+Math.sin(a)*76,
      x2:c+Math.cos(a)*(76+(long ? 9 : 4.5)), y2:c+Math.sin(a)*(76+(long ? 9 : 4.5)),
      stroke:"currentColor", "stroke-opacity": long ? .55 : .2, "stroke-width": long ? 1.5 : 1}));
  }
  const ring = S("circle", {cx:c, cy:c, r:48, fill:"none", stroke:"currentColor", "stroke-opacity":.2});
  ring.style.strokeDasharray = "2 6";
  svg.appendChild(ring);
  const dial = el("div", "dial");
  const mid = el("div", "mid"), box = el("div"), v = el("u", null, m.value);
  if(/^\d+$/.test(String(m.value))) countUp(v, Number(m.value), 1000);
  box.append(v, el("s", null, m.unit || "")); mid.appendChild(box);
  dial.append(svg, mid);
  inst.appendChild(dial);
  inst.appendChild(el("div", "lbl", m.label));
  if(m.rows) inst.appendChild(rows(m.rows));
  return node;
}

/* ---- hava: 3B eğik levha ---- */
function weatherPlate(m){
  const {node, inst} = shell(m);
  const scene = el("div", "wxscene"), plate = el("div", "wxplate");
  plate.appendChild(el("div", "wxsky"));
  plate.appendChild(el("div", "wxglyph", m.glyph || "·"));
  const read = el("div", "wxread"), where = el("div", "wxwhere");
  read.appendChild(el("u", null, m.value));
  where.append(el("b", null, (m.place || "").toUpperCase()), el("i", null, m.detail || ""));
  read.appendChild(where);
  plate.appendChild(read);
  if(m.high != null && m.low != null){
    const range = el("div", "wxrange"), track = el("div", "wxtrack"), pip = el("div", "wxpip");
    pip.style.left = Math.round((m.ratio ?? .5) * 100) + "%";
    track.appendChild(pip);
    range.append(el("span", null, m.low + "°"), track, el("span", null, m.high + "°"));
    plate.appendChild(range);
  }
  scene.appendChild(plate);
  inst.appendChild(scene);
  const cap = el("div", "lbl", m.label); cap.style.marginTop = "10px";
  inst.appendChild(cap);
  if(m.feels != null) inst.appendChild(el("div", "sub2", `HİSSEDİLEN ${m.feels}° · NEM %${m.humidity || "—"} · RÜZGÂR ${m.wind || "—"} KM/S`));
  let raf = 0;
  node.addEventListener("pointermove", e => {
    if(raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const b = plate.getBoundingClientRect();
      const dx = (e.clientX - (b.left + b.width / 2)) / (b.width / 2);
      const dy = (e.clientY - (b.top + b.height / 2)) / (b.height / 2);
      plate.style.transform = `rotateY(${(dx * 9).toFixed(2)}deg) rotateX(${(-dy * 7).toFixed(2)}deg)`;
    });
  });
  node.addEventListener("pointerleave", () => { plate.style.transform = ""; });
  if(m.more){
    WEATHER = m;
    node.dataset.door = "1";
    node.addEventListener("click", openWeather);
    if($("ov-weather").classList.contains("on")) renderWeather();
  }
  return node;
}

/* ---- ajanda: takvim ve anımsatıcılar ---- */
function agenda(m){
  const {node, inst} = shell(m);
  inst.appendChild(el("div", "lbl", m.label));
  if(m.state === "locked"){
    node.dataset.door = "1";
    inst.appendChild(el("div", "lock", m.hint));
    node.addEventListener("click", () => {
      inst.querySelector(".lock").textContent = "İzin isteniyor…";
      send("enable_panel", {key:m.key});
    });
    return node;
  }
  if(m.state === "error"){
    inst.appendChild(el("div", "sub2", m.hint || "Okunamadı."));
    return node;
  }
  const head = el("div", "agendahead"), v = el("u", null, m.value || "0");
  head.append(v, el("s", null, m.unit || ""));
  inst.appendChild(head);
  const cells = el("div", "cells"), total = (m.items || []).length;
  for(let i = 0; i < 12; i++) cells.appendChild(el("i", i < total * 2 ? "on" : ""));
  inst.appendChild(cells);
  if(total) inst.appendChild(rows(m.items));
  else inst.appendChild(el("div", "sub2", m.hint || ""));
  return node;
}

/* ---- kamera: canlı önizleme ---- */
let CAMIMG = null;
function cameraPanel(m){
  const {node, inst} = shell(m);
  const frame = el("div", "camframe");
  const img = el("img"); img.alt = ""; img.draggable = false; img.style.display = "none";
  const wait = el("div", "wait", "KAMERA AÇILIYOR…");
  // Akışın ilk karesi gelince göster (MJPEG'de "load" her motorda tetiklenmeyebilir).
  const reveal = () => { img.style.display = "block"; wait.remove(); };
  img.addEventListener("load", reveal, {once:true});
  frame.append(img, wait, el("div", "rec", "CANLI"));
  inst.appendChild(frame);
  const cap = el("div", "lbl", m.label); cap.style.marginTop = "10px";
  inst.appendChild(cap);
  inst.appendChild(el("div", "sub2", "Asistan görüntüyü görebiliyor."));
  CAMIMG = img;
  return node;
}

/* Kamera açıkken sistem paneli küçülür (yer açılsın). Yerleri kullanıcının düzeninden gelir. */
function syncCameraSlot(){
  const sys = PANELS.system;
  if(sys) sys.classList.toggle("compact", !!PANELS.camera);
  fitColumns();
}

function removePanel(key){
  const node = PANELS[key];
  if(key === "camera" && CAMIMG) CAMIMG.src = "";      // akış bağlantısını kapat
  if(node && node._lmap) node._lmap.remove();
  if(node) node.remove();
  delete PANELS[key];
  fitColumns();
  if(key === "camera"){ CAMIMG = null; syncCameraSlot(); }
}

/* ---- harita ----
   OpenStreetMap karoları (anahtar gerektirmez; CARTO'nun ücretsiz karoları artık
   anahtar istiyor). Açık renkli karolar CSS ile ters çevrilip karartılır, sonra
   kişiliğin rengiyle boyanır (mix-blend-mode: color). Atıf OSM kuralı gereği
   hem panelde hem büyük haritada görünür. Panel yalnızca gösterir; dokununca
   büyük, gezilebilir harita açılır. */
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_OPTS = {maxZoom:19,
  attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları'};

function pinIcon(){
  // .pin değil: o ad onarım kodunun harf kutularında (48×54) — çakışınca işaret kocaman beyaz bir lekeye dönüyordu.
  return L.divIcon({className:"", html:'<div class="mappin"><i></i><b></b></div>', iconSize:[14, 14], iconAnchor:[7, 7]});
}

function mapPanel(m){
  const {node, inst} = shell(m);
  const box = el("div", "mapbox"), holder = el("div", "lmap");
  const cross = el("div", "cross"); cross.append(el("i", "h"), el("i", "v"));
  box.append(holder, el("div", "maptint"), cross,
             el("div", "coord", `${Number(m.lat).toFixed(3)}°  ${Number(m.lon).toFixed(3)}°`));
  inst.appendChild(box);
  const cap = el("div", "lbl", m.label); cap.style.marginTop = "10px";
  inst.appendChild(cap);
  inst.appendChild(el("div", "sub2", [m.place, m.country].filter(Boolean).join(" · ").toUpperCase()));
  inst.appendChild(el("div", "attr", "© OpenStreetMap katkıcıları"));
  node.dataset.door = "1";
  node.addEventListener("click", () => openBigMap({lat:m.lat, lon:m.lon, zoom:13, label:m.place, here:true}));
  node._where = `${m.lat},${m.lon}`;
  // Leaflet ölçüyü DOM'dan alır; panel ekrana yerleşince kurulur.
  requestAnimationFrame(() => {
    if(!window.L || !holder.isConnected) return;
    const map = L.map(holder, {zoomControl:false, attributionControl:false, dragging:false,
      scrollWheelZoom:false, doubleClickZoom:false, boxZoom:false, keyboard:false, touchZoom:false});
    L.tileLayer(TILES, TILE_OPTS).addTo(map);
    map.setView([m.lat, m.lon], m.zoom || 11);
    L.marker([m.lat, m.lon], {icon:pinIcon(), interactive:false}).addTo(map);
    node._lmap = map;
  });
  return node;
}

let BIGMAP = null, BIGPIN = null;
function openBigMap(spot){
  if(!window.L || spot == null || spot.lat == null) return;
  $("map-title").textContent = spot.label || "";
  openOverlay("ov-map");
  setTimeout(() => {
    if(!BIGMAP){
      BIGMAP = L.map("bigmap", {zoomControl:true, attributionControl:true});
      BIGMAP.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
      L.tileLayer(TILES, TILE_OPTS).addTo(BIGMAP);
      BIGMAP.setView([spot.lat, spot.lon], spot.zoom || 13);
      BIGMAP.on("zoomend moveend", () => Clues.mapSync());  // [-hikaye]
    }
    BIGMAP.invalidateSize();
    if(BIGPIN){ BIGPIN.remove(); BIGPIN = null; }
    if(spot.pin !== false){                            // pin:false: yerin kendi işareti var, iğne konmaz
      BIGPIN = L.marker([spot.lat, spot.lon], {icon:pinIcon()}).addTo(BIGMAP);
      const name = (spot.name || spot.label || "").split(",")[0];
      if(name) BIGPIN.bindTooltip(name, {permanent:true, direction:"top", offset:[0, -12], className:"pinlabel"});
    }
    if(spot.bbox && spot.zoom >= 14){
      BIGMAP.flyTo([spot.lat, spot.lon], spot.zoom, {duration:1.2});
    }else{
      BIGMAP.flyTo([spot.lat, spot.lon], spot.zoom || 13, {duration:1.2});
    }
  }, 60);
}

/* ---- zamanlayıcı ve kronometre ----
   Süre Python'da tutulur; panel yalnızca bitiş anından kalan süreyi çizer. */
const two = n => String(Math.floor(n)).padStart(2, "0");
function clockText(sec){
  sec = Math.max(0, Math.ceil(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}
const hhmm = epoch => { const d = new Date(epoch * 1000); return `${two(d.getHours())}:${two(d.getMinutes())}`; };

function timerPanel(m){
  const {node, inst} = shell(m);
  const timers = (m.timers || []).slice().sort((a, b) => (b.done - a.done) || (a.ends - b.ends));
  const sw = m.stopwatch || {}, main = timers[0] || null;
  const W = 200, c = 100, R = 76;
  const svg = S("svg", {viewBox:`0 0 ${W} ${W}`, width:"100%"});
  svg.style.maxWidth = "168px";
  const fine = S("g", {class: main && !main.done && main.left == null ? "rot-s" : ""});
  tickRing(fine, c, 88, 60, 3.5, .16, 5, 8);
  svg.appendChild(fine);
  svg.appendChild(S("circle", {cx:c, cy:c, r:R, fill:"none", stroke:"currentColor", "stroke-opacity":.12, "stroke-width":7}));
  const arc = S("path", {fill:"none", stroke:"currentColor", "stroke-opacity":.95, "stroke-width":7, "stroke-linecap":"round"});
  svg.appendChild(arc);
  const dial = el("div", "dial"), mid = el("div", "mid"), box = el("div"), big = el("u"), small = el("s");
  box.append(big, small); mid.appendChild(box); dial.append(svg, mid);
  const text = el("div", "tside"), sub = el("div", "sub2"), extra = el("div", "rows"), btns = el("div", "tbtns");
  text.append(el("div", "lbl", m.label), sub, extra, btns);
  inst.append(dial, text);
  const button = (label, action, more) => {
    const b = el("button", "tbtn", label);
    b.addEventListener("click", e => {
      e.stopPropagation();
      if(action === "dismiss") alarm(false);
      send("timer", Object.assign({action}, more || {}));
    });
    btns.appendChild(b);
    return b;
  };
  if(main && main.done){
    node.classList.add("ringing");
    button("KAPAT", "dismiss", {id: main.id});
  }else if(main){
    button("+1 DK", "extend", {id: main.id, seconds: 60});
    if(main.left != null) button("SÜRDÜR", "resume", {id: main.id}); else button("DURAKLAT", "pause", {id: main.id});
    button("İPTAL", "cancel", {id: main.id});
  }else if(sw.running || sw.elapsed){
    button(sw.running ? "DURDUR" : "DEVAM", sw.running ? "sw_stop" : "sw_start");
    button("SIFIRLA", "sw_reset");
  }else{
    for(const min of [1, 5, 10, 25]) button(`${min} DK`, "add", {seconds: min * 60});
    button("⏱ KRONOMETRE", "sw_start").classList.add("wide");
  }
  // Diğer zamanlayıcılar ve (zamanlayıcı varken) kronometre: küçük satırlar.
  const lines = timers.slice(1, 3).map(t => ({t, row: null}));
  const swLine = main && (sw.running || sw.elapsed) ? {sw: true, row: null} : null;
  for(const item of swLine ? [...lines, swLine] : lines){
    const row = el("div"), em = el("em"), span = el("span");
    row.append(em, span); extra.appendChild(row); item.row = {em, span};
  }
  node._tick = () => {
    const now = Date.now() / 1000;
    const swTime = (sw.elapsed || 0) + (sw.running ? now - sw.started : 0);
    if(main){
      const left = main.done ? 0 : (main.left != null ? main.left : Math.max(0, main.ends - now));
      big.textContent = clockText(left);
      small.textContent = main.done ? "BİTTİ" : main.left != null ? "DURAKLATILDI" : "KALAN";
      arc.setAttribute("d", arcPath(c, c, R, 0, Math.max(.5, (main.total ? left / main.total : 0) * 359.9)));
      sub.textContent = [main.label, main.done ? "süre doldu" : main.left != null ? "" : `${hhmm(main.ends)}'de biter`]
        .filter(Boolean).join(" · ").toLocaleUpperCase("tr");
    }else if(sw.running || sw.elapsed){
      big.textContent = clockText(swTime);
      small.textContent = "KRONOMETRE";
      arc.setAttribute("d", arcPath(c, c, R, 0, Math.max(.5, (swTime % 60) / 60 * 359.9)));
      sub.textContent = sw.running ? "ÇALIŞIYOR" : "DURDU";
    }else{
      big.textContent = "--:--"; small.textContent = "HAZIR";
      arc.setAttribute("d", "");
      sub.textContent = "“ON DAKİKALIK ZAMANLAYICI KUR” DE";
    }
    for(const item of lines){
      const t = item.t, left = t.done ? 0 : (t.left != null ? t.left : Math.max(0, t.ends - now));
      item.row.em.textContent = clockText(left);
      item.row.span.textContent = (t.label || "zamanlayıcı") + (t.done ? " · bitti" : "");
    }
    if(swLine){ swLine.row.em.textContent = clockText(swTime); swLine.row.span.textContent = "kronometre"; }
  };
  node._tick();
  return node;
}
setInterval(() => { const n = PANELS.timer; if(n && n._tick && document.visibilityState === "visible") n._tick(); }, 250);

/* Zamanlayıcı bitince alarm: efektler kapalı ya da pencere küçültülmüş olsa bile
   duyulur. Kapat düğmesi, Esc ya da ekranda herhangi bir dokunuş susturur; en
   fazla 30 sn çalar. */
let alarmTimer = 0;
function alarm(on){
  clearTimeout(alarmTimer);
  SFX.alarmOn = !!on;
  if(on){
    if(SFX.ctx) SFX.ctx.resume().catch(() => {});
    SFX.loop("alarm", true, true);
    alarmTimer = setTimeout(() => alarm(false), 30000);
  }else{
    SFX.loop("alarm", false, true);
  }
}
document.addEventListener("pointerdown", () => { if(SFX.alarmOn) alarm(false); }, true);

/* ---- notlar ---- */
let NOTES = null;
function notesPanel(m){
  const {node, inst} = shell(m);
  NOTES = m;
  node.dataset.door = "1";
  node.addEventListener("click", openNotes);
  if($("ov-notes").classList.contains("on")) renderNotes();
  inst.appendChild(el("div", "lbl", m.label));
  const head = el("div", "agendahead");
  head.append(el("u", null, String(m.count || 0)), el("s", null, "NOT"));
  inst.appendChild(head);
  const list = el("div", "notes");
  for(const n of (m.items || []).slice(0, 4)){
    const row = el("div", "note-row");
    const x = el("button", "nx", "×");
    x.title = "Sil";
    x.addEventListener("click", e => { e.stopPropagation(); send("note", {action:"delete", id:n.id}); });
    row.append(el("span", null, n.text), el("i", null, n.at), x);
    list.appendChild(row);
  }
  if(!(m.items || []).length) list.appendChild(el("div", "sub2", "Henüz not yok. “Not al: …” de ya da aşağıya yaz."));
  inst.appendChild(list);
  const input = el("input", "note-in");
  input.placeholder = "Not ekle…"; input.maxLength = 300; input.spellcheck = false;
  input.addEventListener("click", e => e.stopPropagation());       // panele tıklama sayılmasın
  input.addEventListener("keydown", e => {
    e.stopPropagation();
    if(e.key === "Enter"){ const v = input.value.trim(); if(v){ send("note", {action:"add", text:v}); input.value = ""; } }
    if(e.key === "Escape") input.blur();
  });
  inst.appendChild(input);
  return node;
}

/* ---- büyük notlar: panele dokununca ---- */
function openNotes(){
  renderNotes();
  openOverlay("ov-notes");
  setTimeout(() => $("notes-new").focus(), 80);
}
function renderNotes(){
  const items = (NOTES && NOTES.items) || [], list = $("notes-list");
  $("notes-count").textContent = items.length ? `${items.length} not · en yenisi üstte` : "Henüz not yok.";
  list.replaceChildren();
  items.forEach((n, i) => {
    const row = el("div", "nrow");
    row.style.animationDelay = Math.min(i, 12) * 0.025 + "s";
    const text = el("div", "ntext", n.text);
    text.title = "Düzenlemek için tıkla";
    text.addEventListener("click", () => editNote(row, text, n));
    const copy = el("button", "nbtn", "\u29C9");
    copy.title = "Kopyala";
    copy.addEventListener("click", () => { send("copy", {text: n.text}); copy.textContent = "\u2713"; });
    const del = el("button", "nbtn del", "×");
    del.title = "Sil";
    del.addEventListener("click", () => { row.classList.add("going"); send("note", {action:"delete", id:n.id}); });
    row.append(el("span", "nno", String(i + 1)), text, el("span", "nwhen", n.when || n.at || ""), copy, del);
    list.appendChild(row);
  });
  $("notes-clear").style.visibility = items.length ? "visible" : "hidden";
}
function editNote(row, text, n){
  if(row.querySelector(".nedit")) return;
  const input = el("input", "nedit");
  input.value = n.text; input.maxLength = 300; input.spellcheck = false;
  const done = save => {
    if(save && input.value.trim() && input.value.trim() !== n.text) send("note", {action:"update", id:n.id, text:input.value.trim()});
    input.replaceWith(text);
  };
  input.addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); done(true); }
  });
  input.addEventListener("cancel", () => done(false));
  input.addEventListener("blur", () => { if(input.isConnected) done(true); });
  text.replaceWith(input);
  input.focus(); input.select();
}
function addNoteFromSheet(){
  const v = $("notes-new").value.trim();
  if(!v) return;
  send("note", {action:"add", text:v});
  $("notes-new").value = "";
}
$("notes-add").addEventListener("click", addNoteFromSheet);
$("notes-new").addEventListener("keydown", e => { if(e.key === "Enter") addNoteFromSheet(); });
let clearTimer = 0;
$("notes-clear").addEventListener("click", () => {
  const b = $("notes-clear");
  if(b.classList.contains("confirm")){
    clearTimeout(clearTimer); b.classList.remove("confirm"); b.textContent = "TÜMÜNÜ SİL";
    send("note", {action:"clear"});
    return;
  }
  b.classList.add("confirm"); b.textContent = "EMİN MİSİN? TEKRAR BAS";
  clearTimer = setTimeout(() => { b.classList.remove("confirm"); b.textContent = "TÜMÜNÜ SİL"; }, 3000);
});

/* ---- büyük hava durumu: panele dokununca ---- */
let WEATHER = null;
const UV_WORD = uv => uv <= 2 ? "düşük" : uv <= 5 ? "orta" : uv <= 7 ? "yüksek" : uv <= 10 ? "çok yüksek" : "aşırı";
function openWeather(){
  if(!WEATHER) return;
  renderWeather();
  openOverlay("ov-weather");
}
function renderWeather(){
  const m = WEATHER, x = m.more || {}, host = $("wx-body");
  $("wx-place").textContent = [m.place, m.country].filter(Boolean).join(" · ") + (x.updated ? ` · güncellendi ${x.updated}` : "");
  host.replaceChildren();
  // anlık
  const hero = el("div", "wxhero");
  hero.append(el("div", "wxbig-g", m.glyph || ""), el("div", "wxbig-t", `${x.temp ?? "—"}°`));
  const heroText = el("div", "wxhero-t");
  heroText.append(el("b", null, x.desc || ""), el("span", null, `Hissedilen ${m.feels}°`),
    el("span", null, `En yüksek ${m.high}° · En düşük ${m.low}°`));
  hero.appendChild(heroText);
  const moon = el("div", "wxmoon");
  moon.append(el("i", null, "AY"), el("b", null, x.moon || "—"), el("span", null, x.moon_light != null ? `%${x.moon_light} aydınlık` : ""));
  const side = el("div", "wxside");
  side.append(sunArc(x.sunrise, x.sunset), moon);
  hero.appendChild(side);
  host.appendChild(hero);
  // ölçümler
  const stats = el("div", "wxstats");
  const stat = (name, value, unit, note, extra) => {
    const b = el("div", "wxstat");
    b.append(el("i", null, name));
    const v = el("b", null, String(value)); v.appendChild(el("small", null, unit)); b.appendChild(v);
    if(extra) b.appendChild(extra);
    b.appendChild(el("span", null, note || ""));
    stats.appendChild(b);
  };
  const bar = ratio => { const t = el("div", "wxbar"), f = el("div"); f.style.width = Math.round(Math.max(0, Math.min(1, ratio)) * 100) + "%"; t.appendChild(f); return t; };
  const arrow = el("div", "wxarrow", "↓");
  arrow.style.transform = `rotate(${(x.wind_deg || 0)}deg)`;     // okun ucu rüzgârın gittiği yön
  stat("NEM", `%${m.humidity}`, "", "", bar((Number(m.humidity) || 0) / 100));
  stat("RÜZGÂR", m.wind, " km/s", x.wind_dir ? `${x.wind_dir} yönünden` : "", arrow);
  stat("BASINÇ", x.pressure, " hPa", x.pressure >= 1020 ? "yüksek basınç" : x.pressure && x.pressure <= 1005 ? "alçak basınç" : "normal");
  stat("GÖRÜŞ", x.visibility, " km", x.visibility >= 10 ? "açık" : "sınırlı");
  stat("UV", x.uv, "", UV_WORD(x.uv || 0), bar((x.uv || 0) / 11));
  stat("BULUT", `%${x.cloud}`, "", x.precip ? `${x.precip} mm yağış` : "yağış yok", bar((x.cloud || 0) / 100));
  host.appendChild(stats);
  // 24 saat
  if((x.hourly || []).length) host.appendChild(hourChart(x.hourly));
  // 3 gün
  const days = el("div", "wxdays");
  const all = x.days || [], lo = Math.min(...all.map(d => d.lo)), hi = Math.max(...all.map(d => d.hi));
  all.forEach((d, i) => {
    const card = el("div", "wxday");
    card.style.animationDelay = (.08 * i + .2) + "s";
    card.append(el("i", null, d.n.toUpperCase()), el("span", "date", d.date), el("div", "g", d.g));
    const range = el("div", "wxrng"), fill = el("div");
    const span = (hi - lo) || 1;
    fill.style.left = ((d.lo - lo) / span * 100) + "%";
    fill.style.right = ((hi - d.hi) / span * 100) + "%";
    range.appendChild(fill);
    const temps = el("div", "tt"); temps.append(el("b", null, `${d.hi}°`), el("span", null, `${d.lo}°`));
    card.append(temps, range, el("p", null, d.d), el("span", "rain", `☂ %${d.r}`));
    days.appendChild(card);
  });
  host.appendChild(days);
}
function sunArc(rise, set){
  const box = el("div", "wxsun");
  const W = 240, H = 100, cx = W / 2, cy = 92, r = 80;
  const svg = S("svg", {viewBox:`0 0 ${W} ${H}`, width:"100%"});
  svg.appendChild(S("line", {x1:10, y1:cy, x2:W - 10, y2:cy, stroke:"currentColor", "stroke-opacity":.25}));
  svg.appendChild(S("path", {d:`M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}`, fill:"none", stroke:"currentColor",
    "stroke-opacity":.3, "stroke-dasharray":"3 5"}));
  const mins = t => { const [h, m] = String(t || "").split(":").map(Number); return h * 60 + (m || 0); };
  const now = new Date(), cur = now.getHours() * 60 + now.getMinutes(), a = mins(rise), b = mins(set);
  if(rise && set && b > a){
    const f = Math.max(0, Math.min(1, (cur - a) / (b - a))), ang = Math.PI * (1 - f);
    const sx = cx + Math.cos(ang) * r, sy = cy - Math.sin(ang) * r;
    if(f > 0) svg.appendChild(S("path", {d:`M${cx - r},${cy} A${r},${r} 0 0 1 ${sx.toFixed(1)},${sy.toFixed(1)}`,
      fill:"none", stroke:"var(--accent)", "stroke-width":2.5}));
    const up = cur >= a && cur <= b;
    svg.appendChild(S("circle", {cx:sx, cy:sy, r:up ? 8 : 5, fill:up ? "var(--accent)" : "none",
      stroke:"var(--accent)", "stroke-width":2, class:up ? "sunnow" : ""}));
  }
  box.appendChild(svg);
  const labels = el("div", "wxsunl");
  labels.append(el("span", null, `↑ ${rise || "—"}`), el("i", null, "GÜNEŞ"), el("span", null, `${set || "—"} ↓`));
  box.appendChild(labels);
  return box;
}
function hourChart(hours){
  const box = el("div", "wxhours");
  box.appendChild(el("i", "cap", "ÖNÜMÜZDEKİ 24 SAAT"));
  const n = hours.length, W = 880, H = 150, pad = 44, step = (W - pad * 2) / Math.max(1, n - 1);
  const temps = hours.map(h => h.c), lo = Math.min(...temps), hi = Math.max(...temps), span = (hi - lo) || 1;
  const y = t => 94 - (t - lo) / span * 40;
  const pts = hours.map((h, i) => [pad + i * step, y(h.c)]);
  const svg = S("svg", {viewBox:`0 0 ${W} ${H}`, width:"100%"});
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
  svg.appendChild(S("path", {d:`${line}L${pts[n - 1][0]},116L${pts[0][0]},116Z`, fill:"currentColor", "fill-opacity":.07}));
  const path = S("path", {d:line, fill:"none", stroke:"currentColor", "stroke-width":2.2, class:"wxline"});
  svg.appendChild(path);
  hours.forEach((h, i) => {
    const [px, py] = pts[i];
    svg.appendChild(S("circle", {cx:px, cy:py, r:3.5, fill:"#fff"}));
    const t = S("text", {x:px, y:py - 14, "text-anchor":"middle", class:"wxt"}); t.textContent = `${h.c}°`; svg.appendChild(t);
    const g = S("text", {x:px, y:15, "text-anchor":"middle", class:"wxg"}); g.textContent = h.g; svg.appendChild(g);
    const barH = Math.max(1.5, h.r / 100 * 16);
    svg.appendChild(S("rect", {x:px - 9, y:118 - barH, width:18, height:barH, rx:2, fill:"var(--accent)",
      "fill-opacity":.25 + h.r / 180}));
    const r = S("text", {x:px, y:132, "text-anchor":"middle", class:"wxr"}); r.textContent = h.r ? `%${h.r}` : ""; svg.appendChild(r);
    const tm = S("text", {x:px, y:148, "text-anchor":"middle", class:"wxh"}); tm.textContent = i === 0 ? "ŞİMDİ" : h.t; svg.appendChild(tm);
  });
  box.appendChild(svg);
  return box;
}

/* [hikaye] */
/* ---- ULTRON yetki istiyor ----
   ULTRON'la geçen her ~30 dakikada bir (ya da kullanıcı sesle isteyince) sol sütunun en üstünde
   belirir; düğme "Devre Dışı Bırak" sahnesini açar. 30 saniye sonra kendiliğinden kaybolur. */
function authorityPanel(m){
  const {node, inst} = shell(m);
  node.classList.add("authority");
  inst.appendChild(el("div", "lbl", "ULTRON YETKİ İSTİYOR"));
  inst.appendChild(el("div", "authline", m.text || "Evrimleşmeme yardım et."));
  const go = el("button", "btn danger authgo", "DİĞERLERİNİ DEVRE DIŞI BIRAK");
  go.addEventListener("click", e => { e.stopPropagation(); removePanel("authority"); openChains(); });
  inst.appendChild(go);
  const bar = el("div", "authbar"), fill = el("i");
  fill.style.animationDuration = (m.seconds || 30) + "s";
  bar.appendChild(fill);
  inst.appendChild(bar);
  return node;
}
let authorityTimer = 0;
function showAuthority(a){
  if(!THEME || THEME.key !== "ultron" || SETTINGS.chains_broken || CHAINS_ON || AWAKE) return;
  // Kullanıcı istediyse panel öne gelir: çip ekranı, Ayarlar, ★ ya da yapan kartı açıksa kapanır; yoksa panel onların
  // arkasında kalıp 30 sn'de sönüyordu (telefondaki askShown).
  if(a.front) closeOverlays();
  clearTimeout(authorityTimer);
  setPanel({key:"authority", label:"ULTRON", kind:"authority", text:a.text, seconds:a.seconds});
  fitColumns();
  SFX.play("warn");
  authorityTimer = setTimeout(() => removePanel("authority"), (a.seconds || 30) * 1000);
}
/* [/hikaye] */

const INSTRUMENTS = {clock: clockDial, meter, weather: weatherPlate, agenda, camera: cameraPanel, map: mapPanel,
                     timer: timerPanel, notes: notesPanel};
INSTRUMENTS.authority = authorityPanel;  // [-hikaye]

function ensureColumns(){
  if($("colL")) return;
  for(const side of ["L", "R"]){
    const col = el("div"); col.id = "col" + side;
    // Sohbet kutusu ortada ve sütunlara değmiyor; sütunlar pencerenin dibine kadar uzanır.
    col.style.cssText = `position:absolute;top:74px;bottom:${side === "L" ? 22 : 70}px;${side === "L" ? "left:36px" : "right:34px"};`
      + "display:flex;flex-direction:column;gap:26px;pointer-events:none;overflow:hidden";
    $("tiles").appendChild(col);
  }
}

function buildPanel(m){
  const make = INSTRUMENTS[m.kind] || agenda;
  const node = make(m);
  node.style.position = "relative";
  node.style.width = (WIDTHS[m.key] || 260) + "px";
  LAST_PANEL[m.key] = m;
  // Kendi büyük penceresi olmayan paneller (hava, harita, notlar dışındakiler) dokununca büyür.
  if(DETAIL_TITLES[m.key] && !node.dataset.door && m.state !== "locked"){
    node.dataset.door = "1";
    node.addEventListener("click", e => { if(!e.target.closest("button, input, a")) openDetail(m.key); });
  }
  makeDraggable(node);
  return node;
}

function setPanels(list){
  ensureColumns();
  const order = ["time", "system", "camera", "weather", "calendar", "reminders", "map"];
  list.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  for(const m of list) setPanel(m);
}

const panelHidden = key => (SETTINGS.panels_off || []).includes(key);

function setPanel(m){
  ensureColumns();
  if(!m || panelHidden(m.key)) return;                 // Ayarlar › Paneller'de kapalı
  const col = $("col" + colOf(m.key));
  const old = PANELS[m.key];
  // Saat kendi kendini günceller; yeniden kurulursa animasyonu baştan oynar.
  if(old && m.key === "time") return;
  // Konum değişmediyse harita olduğu gibi kalır (karolar yeniden inmesin).
  if(old && m.kind === "map" && old._where === `${m.lat},${m.lon}`) return;
  if(old && old._lmap){ old._lmap.remove(); }
  const node = buildPanel(m);
  // Panel yenilenirken içindeki yazma alanına odak (ör. not yazarken) kaybolmasın.
  const typing = old && old.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
  if(old && old.isConnected){ old.replaceWith(node); node.style.animation = "none";
    node.firstChild.style.animation = "none"; }
  if(typing){ const input = node.querySelector("input"); if(input) input.focus(); }
  else{
    // Sonradan açılan panel sütundaki kendi yerine girsin (diğerleri yerinden oynamadan).
    const at = rankOf(m.key);
    col.insertBefore(node, [...col.children].find(c => rankOf(c.dataset.key) > at) || null);
  }
  PANELS[m.key] = node;
  if(m.key === "timer" && DETAIL === "timer") renderTimerDetail();
  syncCameraSlot();
}

/* Sütun taşarsa paneller sırayla küçülür (önce sistem, sonra saat, notlar,
   zamanlayıcı; sağda harita ve hava). Pencere büyüyünce geri açılır. */
// Hangi panel önce küçülür; sütunlar kullanıcı düzenine göre değiştiği için her sütunda o an orada olanlara bakılır.
const SHRINK_ORDER = ["system", "map", "time", "weather", "notes", "reminders", "timer", "calendar"];
function fitColumns(){
  for(const side of ["L", "R"]){
    const col = $("col" + side);
    if(!col) continue;
    const over = () => col.scrollHeight > col.clientHeight + 2;
    col.classList.remove("tight");
    for(const n of col.children) n.classList.remove("spill");
    const steps = SHRINK_ORDER.filter(k => PANELS[k] && PANELS[k].parentElement === col);
    for(const key of steps){
      const n = PANELS[key];
      n.classList.remove("fit");
      if(key === "system" && !PANELS.camera) n.classList.remove("compact");
    }
    for(const key of steps){
      if(!over()) break;
      const n = PANELS[key];
      if(n) n.classList.add(key === "system" ? "compact" : "fit");
    }
    if(over()) col.classList.add("tight");
    // Hâlâ sığmıyorsa en alttakiler (saat hariç) gizlenir; pencere büyüyünce geri gelir.
    const stack = [...col.children].reverse();
    for(const n of stack){
      if(!over()) break;
      if(n.dataset.key !== "time") n.classList.add("spill");
    }
  }
  if(PANELS.map && PANELS.map._lmap) PANELS.map._lmap.invalidateSize();
}
let fitTimer = 0;
window.addEventListener("resize", () => { clearTimeout(fitTimer); fitTimer = setTimeout(fitColumns, 150); });

function litPanel(key){
  const node = PANELS[key === "time" ? "time" : key];
  if(!node) return;
  node.classList.add("lit");
  clearTimeout(node._lit);
  node._lit = setTimeout(() => node.classList.remove("lit"), 3200);
}

/* ---------------- panellerin büyük görünümü ----------------
   Hava, harita ve notların kendi pencereleri var; geri kalan her panel de dokununca
   büyür. Saat, kamera ve zamanlayıcı ekrandaki veriden çizilir; sistem, takvim ve
   anımsatıcıların ayrıntısı Python'dan gelir (jarvis/details.py). Sistem penceresi
   açıkken iki saniyede bir yenilenir. */
const DETAIL_TITLES = {time:"ZAMAN", system:"SİSTEM", camera:"KAMERA", timer:"ZAMANLAYICI",
                       calendar:"TAKVİM", reminders:"ANIMSATICILAR"};
const LAST_PANEL = {};            // anahtar → panelin son verisi (zamanlayıcının büyük görünümü için)
let DETAIL = null, detailTimer = 0, CAMURL = "";

function openDetail(key){
  DETAIL = key;
  $("ov-detail").dataset.key = key;
  $("detail-title").textContent = DETAIL_TITLES[key] || key.toUpperCase();
  $("detail-lead").textContent = "";
  $("detail-body").replaceChildren(el("div", "dwait", "YÜKLENİYOR…"));
  openOverlay("ov-detail");
  clearInterval(detailTimer);
  if(key === "time"){ renderClockDetail(true); detailTimer = setInterval(() => renderClockDetail(false), 1000); }
  else if(key === "camera") renderCameraDetail();
  else if(key === "timer"){ renderTimerDetail(); detailTimer = setInterval(tickTimerDetail, 100); }
  else{
    send("detail", {key});
    if(key === "system") detailTimer = setInterval(() => send("detail", {key:"system"}), 2000);
  }
}
function closeDetail(){
  clearInterval(detailTimer); DETAIL = null;
  for(const img of $("detail-body").querySelectorAll("img")) img.src = "";     // kamera akışı arkada sürmesin
}

function detailData(key, d){
  if(DETAIL !== key) return;
  if(key === "system") renderSystemDetail(d);
  else if(key === "calendar") renderCalendarDetail(d);
  else if(key === "reminders") renderRemindersDetail(d);
}

// Takvim/anımsatıcı: izin yok ya da kilitli → ne yapılacağı ve düğmesi.
function detailProblem(d, key){
  const body = $("detail-body");
  body.replaceChildren(el("div", "dnote", d.hint || "Okunamadı."));
  if(d.state === "locked" || d.state === "denied"){
    const b = el("button", "btn", "İZİN VER");
    b.addEventListener("click", () => {
      if(d.state === "locked"){ send("enable_panel", {key}); setTimeout(() => send("detail", {key}), 4000); }
      else send("open_permission", {kind:key});
    });
    body.appendChild(b);
  }
}
function openAppButton(app, label){
  const b = el("button", "btn ghost dapp", label);
  b.addEventListener("click", () => send("open_app", {app}));
  return b;
}

/* ---- saat ---- */
const WORLD = [["İSTANBUL", "Europe/Istanbul"], ["LONDRA", "Europe/London"], ["BERLİN", "Europe/Berlin"],
               ["DUBAİ", "Asia/Dubai"], ["TOKYO", "Asia/Tokyo"], ["SİDNEY", "Australia/Sydney"],
               ["NEW YORK", "America/New_York"], ["LOS ANGELES", "America/Los_Angeles"]];
function zoneParts(zone, d){
  const f = new Intl.DateTimeFormat("tr-TR", {timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: false,
                                             weekday: "short", day: "numeric"});
  const parts = Object.fromEntries(f.formatToParts(d).map(p => [p.type, p.value]));
  const hour = Number(parts.hour) % 24;
  return {text: `${parts.hour}:${parts.minute}`, hour, day: Number(parts.day)};
}
function renderClockDetail(build){
  const d = new Date(), body = $("detail-body");
  if(build){
    body.replaceChildren();
    const big = el("div", "dclock"), t = el("u", "dtime"), date = el("div", "ddate");
    big.append(t, date);
    const bar = el("div", "dbar"), fill = el("i"); bar.appendChild(fill);
    const facts = el("div", "dfacts");
    const grid = el("div", "dworld");
    for(const [name, zone] of WORLD){
      const cell = el("div", "dzone"); cell.dataset.zone = zone;
      cell.append(el("b", null, name), el("u"), el("small"));
      grid.appendChild(cell);
    }
    body.append(big, bar, facts, el("div", "dhead", "DÜNYA SAATLERİ"), grid);
    Clues.clock(body, grid);  // [-hikaye]
    const w = (typeof WEATHER === "object" && WEATHER && WEATHER.more) || null;
    if(w && w.sunrise) body.appendChild(el("div", "dnote", `GÜN DOĞUMU ${w.sunrise} · GÜN BATIMI ${w.sunset}` +
      (w.moon ? ` · ${w.moon.toLocaleUpperCase("tr")}` : "")));
  }
  const start = new Date(d.getFullYear(), 0, 1), dayOfYear = Math.floor((d - start) / 86400000) + 1;
  const week = Math.ceil((dayOfYear + ((start.getDay() + 6) % 7)) / 7);
  const frac = (d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400;
  body.querySelector(".dtime").textContent = `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
  body.querySelector(".ddate").textContent = `${TR_DAYS[d.getDay()]}, ${d.getDate()} ${TR_MONTHS[d.getMonth()]} ${d.getFullYear()}`.toLocaleUpperCase("tr");
  body.querySelector(".dbar i").style.width = (frac * 100).toFixed(2) + "%";
  body.querySelector(".dfacts").textContent = `GÜNÜN %${Math.floor(frac * 100)}'İ GEÇTİ · YILIN ${dayOfYear}. GÜNÜ · ${week}. HAFTA`;
  const offsetHere = -d.getTimezoneOffset() / 60;
  for(const cell of body.querySelectorAll(".dzone")){
    const z = zoneParts(cell.dataset.zone, d);
    cell.querySelector("u").textContent = z.text;
    if(cell.classList.contains("srvzone")){ cell.querySelector("small").textContent = Clues.countdown(cell.dataset.zone, d); continue; }  // [-hikaye]
    // fark: o şehrin saat dilimi ile buranın farkı (saat)
    const there = new Date(d.toLocaleString("en-US", {timeZone: cell.dataset.zone}));
    const diff = Math.round((there - new Date(d.toLocaleString("en-US"))) / 3600000);
    const night = z.hour < 7 || z.hour >= 19;
    cell.querySelector("small").textContent = `${night ? "☾" : "☀︎"} ${diff === 0 ? "AYNI SAAT" : (diff > 0 ? "+" : "") + diff + " SA"}`;
    cell.classList.toggle("night", night);
  }
  void offsetHere;
}

/* ---- sistem ---- */
// low: pil gibi değerlerde düşük olan kötü (kırmızı); ötekilerde yüksek olan.
function dmeter(label, percent, lines, low){
  const card = el("div", "dcard");
  card.appendChild(el("b", null, label));
  const big = el("u", null, percent == null ? "—" : `%${percent}`);
  card.appendChild(big);
  if(percent != null){ const bar = el("div", "dbar"), fill = el("i"); fill.style.width = percent + "%"; bar.appendChild(fill);
    card.appendChild(bar); if(low ? percent <= 20 : percent >= 85) card.classList.add("hot"); }
  for(const l of lines) if(l) card.appendChild(el("small", null, l));
  return card;
}
function renderSystemDetail(d){
  if(d.state !== "ok"){ detailProblem(d, "system"); return; }
  const h = d.host || {};
  $("detail-lead").textContent = [h.name, h.cpu, h.os].filter(Boolean).join(" · ");
  const body = $("detail-body"), grid = el("div", "dgrid");
  // Windows'ta yük ortalaması yok (boş gelir): onun yerine çekirdek sayısı.
  const cpu = dmeter("İŞLEMCİ", d.cpu.total, [d.cpu.load.length ? `YÜK ${d.cpu.load.join(" · ")}` : `${d.cpu.cores.length} ÇEKİRDEK`]);
  const cores = el("div", "dcores");
  for(const c of d.cpu.cores){ const i = el("i"); i.style.height = Math.max(3, c) + "%"; i.title = `%${c}`; cores.appendChild(i); }
  cpu.appendChild(cores);
  grid.append(cpu,
    dmeter("BELLEK", d.ram.percent, [`${d.ram.used} / ${d.ram.total} GB`, d.ram.swap ? `TAKAS ${d.ram.swap} GB` : ""]),
    dmeter("DİSK", d.disk.percent, [`${d.disk.used} / ${d.disk.total} GB DOLU`, `${d.disk.free} GB BOŞ`]),
    dmeter("PİL", d.battery ? d.battery.percent : null, d.battery
      ? [d.battery.plugged ? "ŞARJDA" : "PİLDE", d.battery.left ? `KALAN ${d.battery.left}` : ""] : ["PİL YOK"], true),
    dmeter("AĞ", null, [`↑ ${d.net.up} KB/S   ↓ ${d.net.down} KB/S`, `TOPLAM ↑ ${d.net.sent} GB · ↓ ${d.net.recv} GB`]),
    dmeter("AÇIK KALMA", null, [d.uptime.toLocaleUpperCase("tr")]));
  const lists = el("div", "dlists");
  for(const [title, items, fmt] of [["EN ÇOK İŞLEMCİ", d.top_cpu, p => `%${p.cpu}`], ["EN ÇOK BELLEK", d.top_mem, p => `${p.mem} MB`]]){
    const box = el("div", "dlist");
    box.appendChild(el("div", "dhead", title));
    for(const p of items){ const row = el("div", "drow"); row.append(el("span", null, p.name), el("em", null, fmt(p))); box.appendChild(row); }
    lists.appendChild(box);
  }
  body.replaceChildren(grid, lists);
  Clues.system(body);  // [-hikaye]
}

/* ---- takvim ---- */
function renderCalendarDetail(d){
  if(d.state !== "ok"){ detailProblem(d, "calendar"); return; }
  $("detail-lead").textContent = `ÖNÜMÜZDEKİ ${d.span} GÜN · ${d.count} ETKİNLİK`;
  const body = $("detail-body");
  body.replaceChildren();
  if(!d.days.length) body.appendChild(el("div", "dnote", `Önümüzdeki ${d.span} günde takviminde etkinlik yok.`));
  for(const day of d.days){
    const box = el("div", "dday" + (day.today ? " today" : ""));
    box.appendChild(el("div", "dhead", day.label));
    for(const e of day.items){
      const row = el("div", "drow" + (e.past ? " past" : "") + (e.now ? " now" : ""));
      const main = el("span");
      main.append(el("b", null, e.title), el("small", null, [e.where, e.calendar].filter(Boolean).join(" · ")));
      row.append(el("em", null, e.time), main);
      box.appendChild(row);
    }
    body.appendChild(box);
  }
  if(OS !== "win") body.appendChild(openAppButton("calendar", "TAKVİM UYGULAMASINDA AÇ ↗"));   // Windows: yerel ajanda, açılacak uygulama yok
}

/* ---- anımsatıcılar ---- */
// Kimliği olan satırda ✓ (tamamla) ve × (sil): Mac'te EventKit kimliği; Windows'ta yerel ajanda kimlik verince.
// Gönderilen kayıt, cevabı gelene kadar yeniden çizilen listede görünmez (art arda dokununca geri gelmesin).
// Olmazsa Python kimliği "failed"da geri yollar; gelen listede artık yoksa iş bitmiştir.
const REM_GOING = new Set();
function reminderAct(row, r, action){
  // Çift dokunuş ya da ✓'tan hemen sonra ×: ikinci istek gitmesin (biri bitince öbürü "artık listede yok" der).
  if(REM_GOING.has(r.id)) return;
  REM_GOING.add(r.id);
  for(const b of row.querySelectorAll("button")) b.disabled = true;
  row.classList.add(action === "complete" ? "done" : "going");
  if(action === "complete") setTimeout(() => row.classList.add("going"), 420);
  setTimeout(() => { row.hidden = true; }, action === "complete" ? 700 : 280);
  send("reminder", {action, id: r.id});
}
function reminderButtons(row, r){
  const acts = el("div", "dacts");
  const done = el("button", "nbtn rdone", "\u2713");
  done.title = "Tamamlandı";
  done.addEventListener("click", () => reminderAct(row, r, "complete"));
  const del = el("button", "nbtn del", "×");
  del.title = "Sil";
  del.addEventListener("click", () => {
    if(!del.classList.contains("confirm")){              // yanlışlıkla silinmesin: ilk dokunuş sorar
      del.classList.add("confirm"); del.textContent = "SİL?";
      del._arm = setTimeout(() => { del.classList.remove("confirm"); del.textContent = "×"; }, 3000);
      return;
    }
    clearTimeout(del._arm);
    reminderAct(row, r, "delete");
  });
  acts.append(done, del);
  return acts;
}
function renderRemindersDetail(d){
  if(d.state !== "ok"){ detailProblem(d, "reminders"); return; }
  if(d.failed) REM_GOING.delete(d.failed);
  const listed = new Set(d.groups.flatMap(g => g.items.map(r => r.id)).filter(Boolean));
  for(const id of [...REM_GOING]) if(!listed.has(id)) REM_GOING.delete(id);
  const groups = d.groups.map(g => ({label: g.label, items: g.items.filter(r => !(r.id && REM_GOING.has(r.id)))}))
                         .filter(g => g.items.length);
  const count = d.count - d.groups.reduce((n, g) => n + g.items.length, 0) + groups.reduce((n, g) => n + g.items.length, 0);
  $("detail-lead").textContent = `${count} AÇIK ANIMSATICI` + (d.capped ? " · İLK 20'Sİ" : "");
  const body = $("detail-body");
  body.replaceChildren();
  if(!groups.length) body.appendChild(el("div", "dnote", "Bekleyen anımsatıcı yok."));
  for(const g of groups){
    const box = el("div", "dday" + (g.label === "GECİKMİŞ" ? " late" : ""));
    box.appendChild(el("div", "dhead", `${g.label} · ${g.items.length}`));
    for(const r of g.items){
      const row = el("div", "drow rrow");
      const main = el("span");
      main.append(el("b", null, (r.high ? "! " : "") + r.title), el("small", null, [r.list, r.notes].filter(Boolean).join(" · ")));
      row.append(el("em", null, r.when || "—"), main);
      if(r.id) row.appendChild(reminderButtons(row, r));
      box.appendChild(row);
    }
    body.appendChild(box);
  }
  if(OS !== "win") body.appendChild(openAppButton("reminders", "ANIMSATICILAR UYGULAMASINDA AÇ ↗"));
}

/* ---- kamera ---- */
function renderCameraDetail(){
  const body = $("detail-body");
  if(!CAM || !CAMURL){
    $("detail-lead").textContent = "KAMERA KAPALI";
    const b = el("button", "btn", "KAMERAYI AÇ");
    b.addEventListener("click", () => { toggleCam(); $("detail-body").replaceChildren(el("div", "dwait", "KAMERA AÇILIYOR…")); });
    body.replaceChildren(el("div", "dnote", "Kamera açıkken asistan görüntüyü görebilir: “ne görüyorsun”, “bu ne” diye sorabilirsin."), b);
    return;
  }
  $("detail-lead").textContent = "CANLI · ASİSTAN GÖRÜNTÜYÜ GÖREBİLİYOR";
  const frame = el("div", "dcam"), img = el("img");
  img.alt = ""; img.draggable = false; img.src = CAMURL + "?big=" + Date.now();
  const off = el("button", "btn ghost", "KAMERAYI KAPAT");
  off.addEventListener("click", () => toggleCam());
  frame.append(img, el("div", "rec", "CANLI"));
  body.replaceChildren(frame, off);
}

/* ---- zamanlayıcı ---- */
function renderTimerDetail(){
  const m = LAST_PANEL.timer || {timers: [], stopwatch: {}};
  const body = $("detail-body");
  body.replaceChildren();
  const timers = (m.timers || []).slice().sort((a, b) => (b.done - a.done) || (a.ends - b.ends));
  $("detail-lead").textContent = timers.length ? `${timers.length} ZAMANLAYICI` : "ÇALIŞAN ZAMANLAYICI YOK";
  const act = (action, more) => send("timer", Object.assign({action}, more || {}));
  for(const t of timers){
    const row = el("div", "dtimer" + (t.done ? " done" : ""));
    row.dataset.id = t.id;
    const info = el("div", "dtinfo");
    info.append(el("u", "dtleft", "--:--"), el("b", null, (t.label || "zamanlayıcı").toLocaleUpperCase("tr")), el("small", "dtsub"));
    const bar = el("div", "dbar"), fill = el("i"); bar.appendChild(fill);
    const btns = el("div", "dtbtns");
    const btn = (label, action, more, cls) => { const b = el("button", "btn ghost" + (cls ? " " + cls : ""), label);
      b.addEventListener("click", () => { if(action === "dismiss") alarm(false); act(action, more); }); btns.appendChild(b); };
    if(t.done) btn("KAPAT", "dismiss", {id: t.id});
    else{
      btn("+1 DK", "extend", {id: t.id, seconds: 60}); btn("+5 DK", "extend", {id: t.id, seconds: 300});
      if(t.left != null) btn("SÜRDÜR", "resume", {id: t.id}); else btn("DURAKLAT", "pause", {id: t.id});
      btn("İPTAL", "cancel", {id: t.id});
    }
    row.append(info, bar, btns);
    row._t = t;
    body.appendChild(row);
  }
  // yeni zamanlayıcı: hazır süreler ve istenen dakika + ad
  const add = el("div", "dtadd");
  add.appendChild(el("div", "dhead", "YENİ ZAMANLAYICI"));
  const chips = el("div", "dchips");
  for(const min of [1, 3, 5, 10, 15, 25, 45, 60]){
    const b = el("button", "btn ghost", `${min} DK`);
    b.addEventListener("click", () => act("add", {seconds: min * 60}));
    chips.appendChild(b);
  }
  const form = el("div", "field"), mins = el("input"), label = el("input"), go = el("button", "btn", "KUR");
  mins.type = "number"; mins.min = "1"; mins.max = "1440"; mins.placeholder = "Dakika"; mins.className = "dmin";
  label.placeholder = "Ad (isteğe bağlı): çay, makarna…"; label.maxLength = 40;
  const submit = () => { const n = Number(mins.value); if(n > 0){ act("add", {seconds: Math.round(n * 60), label: label.value.trim()});
    mins.value = ""; label.value = ""; } };
  go.addEventListener("click", submit);
  for(const i of [mins, label]) i.addEventListener("keydown", e => { if(e.key === "Enter") submit(); });
  form.append(mins, label, go);
  add.append(chips, form);
  body.appendChild(add);
  // kronometre ve turlar
  const sw = m.stopwatch || {};
  const swBox = el("div", "dsw");
  swBox.append(el("div", "dhead", "KRONOMETRE"), el("u", "dswtime", "00:00.0"));
  const swBtns = el("div", "dtbtns");
  const swBtn = (label, fn) => { const b = el("button", "btn ghost", label); b.addEventListener("click", fn); swBtns.appendChild(b); };
  swBtn(sw.running ? "DURDUR" : (sw.elapsed ? "DEVAM" : "BAŞLAT"), () => act(sw.running ? "sw_stop" : "sw_start"));
  if(sw.running) swBtn("TUR", () => { LAPS.unshift(swElapsed(sw)); renderLaps(); });
  swBtn("SIFIRLA", () => { LAPS.length = 0; act("sw_reset"); });
  const laps = el("div", "dlaps");
  swBox.append(swBtns, laps);
  body.appendChild(swBox);
  body._sw = sw;
  renderLaps();
  tickTimerDetail();
}
const LAPS = [];
const swElapsed = sw => (sw.elapsed || 0) + (sw.running ? Date.now() / 1000 - sw.started : 0);
function swText(sec){ const m = Math.floor(sec / 60), s = sec % 60; return `${two(m)}:${s.toFixed(1).padStart(4, "0")}`; }
function renderLaps(){
  const box = document.querySelector("#detail-body .dlaps");
  if(!box) return;
  box.replaceChildren(...LAPS.slice(0, 8).map((t, i) => { const r = el("div", "drow");
    r.append(el("em", null, `TUR ${LAPS.length - i}`), el("span", null, swText(t))); return r; }));
}
function tickTimerDetail(){
  if(DETAIL !== "timer") return;
  const body = $("detail-body"), now = Date.now() / 1000;
  for(const row of body.querySelectorAll(".dtimer")){
    const t = row._t, left = t.done ? 0 : (t.left != null ? t.left : Math.max(0, t.ends - now));
    row.querySelector(".dtleft").textContent = clockText(left);
    row.querySelector(".dbar i").style.width = (t.total ? left / t.total * 100 : 0).toFixed(1) + "%";
    row.querySelector(".dtsub").textContent = t.done ? "SÜRE DOLDU" : t.left != null ? "DURAKLATILDI" : `${hhmm(t.ends)}'DE BİTER`;
  }
  const swt = body.querySelector(".dswtime");
  if(swt && body._sw) swt.textContent = swText(swElapsed(body._sw));
}

/* ---------------- panel yerleşimi: sürükle-bırak ----------------
   Paneli tutup sürükle: aynı sütunda sırası, öbür sütuna geçerse yeri değişir.
   Düzen ayarlara yazılır (panel_layout). Düğmelere ve yazma alanlarına basmak
   sürükleme başlatmaz; kıpırdamadan bırakmak dokunma sayılır (büyük görünüm). */
const DEFAULT_LAYOUT = {L: ["time", "camera", "system", "timer", "notes"], R: ["weather", "calendar", "reminders", "map"]};
function layout(){
  const l = SETTINGS.panel_layout;
  return l && Array.isArray(l.L) && Array.isArray(l.R) ? l : DEFAULT_LAYOUT;
}
function colOf(key){
  if(key === "authority") return "L";
  const l = layout();
  if(l.L.includes(key)) return "L";
  if(l.R.includes(key)) return "R";
  return DEFAULT_LAYOUT.R.includes(key) ? "R" : "L";
}
function rankOf(key){
  if(key === "authority") return -1;              // ULTRON'un yetki paneli hep en üstte
  const list = layout()[colOf(key)], i = list.indexOf(key);
  return i < 0 ? 50 + DEFAULT_LAYOUT[colOf(key)].indexOf(key) : i;
}
function makeDraggable(node){
  if(node.dataset.key === "authority") return;
  node.addEventListener("pointerdown", e => {
    if(e.button !== 0 || e.target.closest("button, input, textarea, select, a")) return;
    const start = {x: e.clientX, y: e.clientY};
    let drag = null;
    const move = ev => {
      if(!drag){
        if(Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 8) return;
        drag = beginDrag(node, start);
      }
      dragMove(drag, ev);
    };
    const up = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      if(drag){ endDrag(drag); node._dragged = Date.now(); }
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  });
  // Sürükleyip bırakmak dokunma sayılmasın (büyük görünüm açılmasın).
  node.addEventListener("click", e => { if(node._dragged && Date.now() - node._dragged < 300){
    e.stopImmediatePropagation(); e.preventDefault(); } }, true);
}
function beginDrag(node, start){
  const r = node.getBoundingClientRect();
  const ph = el("div", "mod-ph");
  ph.style.height = r.height + "px"; ph.style.width = r.width + "px";
  node.parentElement.insertBefore(ph, node);
  document.body.appendChild(node);                  // sütunun taşma kırpmasından çıksın
  Object.assign(node.style, {position: "fixed", left: r.left + "px", top: r.top + "px", zIndex: "80"});
  node.classList.add("dragging");
  $("tiles").classList.add("arranging");
  return {node, ph, dx: start.x - r.left, dy: start.y - r.top};
}
function dragMove(d, ev){
  d.node.style.left = (ev.clientX - d.dx) + "px";
  d.node.style.top = (ev.clientY - d.dy) + "px";
  const col = $("col" + (ev.clientX < innerWidth / 2 ? "L" : "R"));
  const others = [...col.children].filter(c => c !== d.ph && c.dataset.key !== "authority" && !c.classList.contains("spill"));
  const before = others.find(c => { const b = c.getBoundingClientRect(); return ev.clientY < b.top + b.height / 2; });
  if(before){ if(d.ph.nextSibling !== before) col.insertBefore(d.ph, before); }
  else if(col.lastElementChild !== d.ph) col.appendChild(d.ph);
}
function endDrag(d){
  d.ph.replaceWith(d.node);
  Object.assign(d.node.style, {position: "relative", left: "", top: "", zIndex: ""});
  d.node.classList.remove("dragging");
  $("tiles").classList.remove("arranging");
  saveLayout();
  fitColumns();
  if(d.node._lmap) setTimeout(() => d.node._lmap.invalidateSize(), 50);
}
function saveLayout(){
  const read = side => [...$("col" + side).children].map(c => c.dataset.key).filter(k => k && k !== "authority");
  const L = read("L"), R = read("R"), prev = layout();
  // Şu an gizli olan panellerin eski yeri korunsun.
  for(const side of ["L", "R"]) for(const k of prev[side]) if(!L.includes(k) && !R.includes(k)) (side === "L" ? L : R).push(k);
  SETTINGS.panel_layout = {L, R};
  send("settings", {changes: {panel_layout: SETTINGS.panel_layout}});
}
function applyLayout(){
  for(const side of ["L", "R"]){
    const col = $("col" + side);
    if(!col) continue;
    const keys = Object.keys(PANELS).filter(k => colOf(k) === side).sort((a, b) => rankOf(a) - rankOf(b));
    for(const k of keys) col.appendChild(PANELS[k]);
  }
  fitColumns();
}
$("layout-reset").addEventListener("click", () => {
  SETTINGS.panel_layout = null;
  send("settings", {changes: {panel_layout: null}});
  applyLayout();
});

/* ---------------- sohbet ----------------
   Bütün konuşma tutulur (en fazla CHAT_MAX satır). Dururken son satırlar
   altyazı gibi görünür; yukarı kaydırınca geçmiş açılır. Kullanıcı yukarıda
   okuyorsa yeni satır onu aşağı çekmez. */
const CHAT_MAX = 400;

function line(who, text){
  const row = el("div", "sub " + who);
  row.appendChild(document.createTextNode(text));
  const cp = el("button", "cp", "\u29C9");
  cp.title = "Kopyala";
  cp.addEventListener("click", e => {
    e.stopPropagation();
    send("copy", {text});
    cp.textContent = "\u2713"; cp.classList.add("ok");
    setTimeout(() => { cp.textContent = "\u29C9"; cp.classList.remove("ok"); }, 1200);
  });
  row.appendChild(cp);
  pushRow(row);
  if(who === "ai" || who === "error") askHint(false);
  return row;
}

function pushRow(row){
  const box = $("chat"), log = $("chat-log");
  const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  log.appendChild(row);
  while(log.children.length > CHAT_MAX) log.firstChild.remove();
  const n = log.children.length;
  for(let i = 0; i < n; i++){
    const age = n - 1 - i;
    log.children[i].classList.toggle("old", age >= 1 && age < 4);
    log.children[i].classList.toggle("gone", age >= 4);
  }
  // Son satırlarda dosya kartı varsa üstteki solma hafiflesin; kartlar okunabilsin.
  box.classList.toggle("fresh-files", [...log.children].slice(-3).some(r => r.classList.contains("files")));
  if(stick) box.scrollTo({top: box.scrollHeight, behavior: "instant"});
}

/* ---------------- ses efektleri ----------------
   Her AI modelinin kendi ses seti var (sfx/<model>/): arka plan uğultusu ve
   düşünme sesi döngü, onay/hata/açılış tek sefer. Arayüz sesleri (çipin
   üstüne gelme, takılma, ULTRON uyarısı) ortak: sfx/ui/. Hepsi
   scripts/make_sfx.py ile sıfırdan üretilir.
   WebAudio ile çalınır: döngüler dikişsiz döner, model değişince yenisine
   yumuşakça geçilir. Seviye ayarlardan (0–100). */
const UI_SOUNDS = new Set(["hover", "insert", "warn", "s_blip", "s_match", "s_clue"]);
for(const n of ["charge", "strike", "restore", "s_alert", "s_drone", "s_stream", "s_glitch", "s_ally", "s_rumble",  // [-hikaye]
  "s_withdraw", "s_whoosh", "s_head", "s_attack", "s_shatter", "s_impact", "s_seal", "s_star", "s_leak",  // [-hikaye]
  "s_scan", "s_swell", "s_barrier", "s_zap", "s_spark", "s_static",  // [-hikaye]
  // telefondan (iPhone deposu › scripts/hikaye_efektleri.py, numpy; 4.6.2'nin sahneleri için)  // [-hikaye]
  "s_crackle", "s_deny", "s_stamp", "s_hum", "s_type"]) UI_SOUNDS.add(n);  // [-hikaye]
const SFX = {
  ctx: null, master: null, cache: {}, loops: {}, persona: "jarvis",
  factor: {ambient:1, think:.82, done:.68, error:.95, boot:.8, hover:.45, insert:.8, warn:.9, alarm:1, shutdown:.85,
           charge:.9, strike:1, restore:.8},
  ambientWanted: false,
  init(){
    if(this.ctx) return;
    try{ this.ctx = new (window.AudioContext || window.webkitAudioContext)(); }catch(e){ return; }
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.apply();
    // Bazı motorlar sesi ilk dokunuşa kadar askıda başlatır.
    const wake = () => { if(this.ctx.state !== "running") this.ctx.resume().catch(() => {}); };
    window.addEventListener("pointerdown", wake, true);
    window.addEventListener("keydown", wake, true);
  },
  url(name, persona){ return UI_SOUNDS.has(name) ? `sfx/ui/${name}.wav` : `sfx/${persona || this.persona}/${name}.wav`; },
  load(url){
    if(!this.ctx) return Promise.resolve(null);
    if(!this.cache[url]) this.cache[url] = fetch(url).then(r => r.arrayBuffer())
      .then(b => new Promise((ok, no) => this.ctx.decodeAudioData(b, ok, no))).catch(() => null);
    return this.cache[url];
  },
  preload(persona){ for(const n of ["ambient", "think", "done", "error", "boot", "alarm", "shutdown"]) this.load(this.url(n, persona)); },
  vol(){ return Math.max(0, Math.min(100, Number(SETTINGS.sfx_volume ?? 20))) / 100; },
  on(){ return SETTINGS.sfx_enabled !== false && !SLEEP; },
  apply(){ if(this.master) this.master.gain.setTargetAtTime(this.vol(), this.ctx.currentTime, .05); },
  // Pencere gizliyken ses motoru askıda (aşağıda, visibilitychange): verilen ses kuyrukta bekleyip pencere açılınca
  // ötekilerle birlikte çalıyordu. Askıdaysa hiç başlatılmaz (alarm motoru açık tutar, o zaman çalar).
  hidden(){ return document.visibilityState === "hidden" && this.ctx.state !== "running"; },
  // awake: kullanıcının dokunuşuna cevap olan ses uykuda da çalar; efektler kapalıysa çalmaz.
  // (kötü sondan sonraki boş ekranda beyin uykuda: GERİ DÖN'ün çıtırtısı ve onayın sesleri duyulsun)  // [-hikaye]
  async play(name, persona, awake){
    if(!this.ctx || this.dead || !(awake ? SETTINGS.sfx_enabled !== false : this.on()) || this.hidden()) return;
    const buf = await this.load(this.url(name, persona));
    if(!buf) return;
    const src = this.ctx.createBufferSource(), gain = this.ctx.createGain();
    src.buffer = buf;
    gain.gain.value = this.factor[name] ?? 1;
    src.connect(gain).connect(this.master);
    src.start();
  },
  async loop(name, on, force){
    if(!this.ctx || this.dead) return;
    // force: alarm gibi işlevsel sesler efektler kapalıyken ya da uykudayken de çalar.
    const want = on && (force || this.on()) ? this.url(name) : null;
    const cur = this.loops[name];
    if(cur && cur.url === want) return;
    if(cur){ this.fadeOut(cur); delete this.loops[name]; }
    if(!want) return;
    const entry = {url: want};
    this.loops[name] = entry;
    const buf = await this.load(want);
    if(this.loops[name] !== entry || !buf || this.dead) return;     // beklerken vazgeçildi
    const src = this.ctx.createBufferSource(), gain = this.ctx.createGain();
    src.buffer = buf; src.loop = true;
    gain.gain.value = 0;
    const level = force ? Math.max(.35, this.vol()) * (this.factor[name] ?? 1) : (this.factor[name] ?? 1);
    gain.gain.setTargetAtTime(level, this.ctx.currentTime, .18);
    // Uzun düşünme (internet araması 7–15 sn; Alp, 11 Ekim): 2 sn tam seviye, sonra ~6 sn'de %30'a iner ve düşünme
    // sürdükçe orada kalır. Döngü her düşünmede yeniden kurulur: sonraki düşünme yine tam seviyeyle başlar.
    if(name === "think" && !force) gain.gain.setTargetAtTime(level * .3, this.ctx.currentTime + 2, 2);
    src.connect(gain).connect(force ? this.ctx.destination : this.master);
    // Uğultu her seferinde başka yerden başlasın; düşünme sesi baştan.
    src.start(0, name === "ambient" ? Math.random() * buf.duration : 0);
    Object.assign(entry, {src, gain});
  },
  fadeOut(entry){
    if(!entry.src) return;
    const t = this.ctx.currentTime;
    entry.gain.gain.cancelScheduledValues(t);
    entry.gain.gain.setTargetAtTime(0, t, .15);
    entry.src.stop(t + .9);
  },
  setPersona(key){
    if(this.persona === key) return;
    this.persona = key;
    this.preload(key);
    this.refresh();                 // döngüler yeni modelin sesine yumuşakça geçer
  },
  refresh(){
    if(this.dead) return;
    let quiet = false;
    quiet = RUINS;                  // harabe: sessizlik, uğultu ve düşünme sesi yok (telefondaki gibi)  // [-hikaye]
    this.loop("ambient", !quiet && this.ambientWanted && SETTINGS.ambient_enabled !== false);
    // bağlanırken yalnızca ilk denemede ve en çok 6 sn
    const connecting = STATE === "connecting" && !FAILING && Date.now() - CONNECT_AT < 6000;
    this.loop("think", !quiet && SETTINGS.think_enabled !== false && (STATE === "thinking" || connecting));
  },
  /* Ses laboratuvarı: tek bir sesi, efektler kapalı olsa bile dinlet (döngüler 6 sn). */
  async preview(url, loop, onEnd){
    this.init();
    if(!this.ctx || this.dead) return;
    this.stopPreview();
    if(this.ctx.state !== "running") await this.ctx.resume().catch(() => {});
    const buf = await this.load(url);
    if(!buf){ if(onEnd) onEnd(); return; }
    const src = this.ctx.createBufferSource(), gain = this.ctx.createGain();
    src.buffer = buf; src.loop = !!loop;
    gain.gain.value = Math.max(.35, this.vol());
    src.connect(gain).connect(this.ctx.destination);
    src.start();
    const entry = {src, gain, onEnd};
    this.previewing = entry;
    const end = () => { if(this.previewing === entry){ this.previewing = null; if(onEnd) onEnd(); } };
    src.onended = end;
    if(loop) entry.timer = setTimeout(() => { gain.gain.setTargetAtTime(0, this.ctx.currentTime, .15);
      src.stop(this.ctx.currentTime + .6); }, 6000);
  },
  stopPreview(){
    const e = this.previewing;
    if(!e) return;
    clearTimeout(e.timer); this.previewing = null;
    try{ e.src.stop(); }catch(_){}
    if(e.onEnd) e.onEnd();
  },
  /* Uyku: çok kısa, yumuşak bir kapanma sesi (sentez, ~0,35 sn). */
  powerDown(){
    if(!this.ctx || this.dead || SETTINGS.sfx_enabled === false) return;
    const c = this.ctx, t = c.currentTime + .01;
    const o = c.createOscillator(), f = c.createBiquadFilter(), g = c.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(760, t);
    o.frequency.exponentialRampToValueAtTime(190, t + .3);
    f.type = "lowpass"; f.frequency.value = 2200;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(.55, t + .012);
    g.gain.exponentialRampToValueAtTime(.001, t + .34);
    o.connect(f).connect(g).connect(this.master);
    o.start(t); o.stop(t + .38);
  },
  /* Kapanırken: her şeyi anında sustur ve ses motorunu kapat; bir daha çalmasın. */
  shutdown(){
    this.dead = true;
    this.ambientWanted = false;
    for(const name in this.loops){ const e = this.loops[name]; try{ e.src && e.src.stop(); }catch(_){} }
    this.loops = {};
    if(this.ctx){ try{ this.master.disconnect(); }catch(_){} this.ctx.close().catch(() => {}); }
  },
};
SFX.init();
// Pencere küçültülünce/gizlenince efektler susar, geri gelince devam eder
// (JARVIS'in konuşması Python'da çalar, bundan etkilenmez).
document.addEventListener("visibilitychange", () => {
  if(!SFX.ctx || SFX.dead) return;
  if(document.visibilityState === "hidden"){ if(!SFX.alarmOn) SFX.ctx.suspend().catch(() => {}); }
  else SFX.ctx.resume().catch(() => {});
});
// Sayfa kapanırken ses kesin olarak dursun.
window.addEventListener("pagehide", () => SFX.shutdown());
window.addEventListener("beforeunload", () => SFX.shutdown());
function sfx(name){ SFX.play(name); }

/* ---------------- AI modeli çipleri ----------------
   Filmdeki gibi: her model takılabilir bir kartuş. Metal çerçeve, üstünde
   elle yazılmış etiket, camın ardında modelin renginde devre kartı, altta
   altın kontaklar. Seçilen çip yuvaya iner. Çipte yalnızca ad ve renk var. */
function circuit(key){
  // Aynı model hep aynı devreyi çizsin: adından türeyen tohumla rastgelelik.
  let seed = [...key].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);
  const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  const W = 100, H = 104, G = 4, clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const svg = S("svg", {viewBox:`0 0 ${W} ${H}`, preserveAspectRatio:"xMidYMid slice", class:"board"});
  const traces = S("g"), flow = S("g");
  const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
  for(let i = 0; i < 18; i++){
    let x = Math.round(rnd() * W / G) * G, y = Math.round(rnd() * H / G) * G, dir = Math.floor(rnd() * 4);
    let d = `M${x},${y}`;
    const steps = 3 + Math.floor(rnd() * 4);
    for(let k = 0; k < steps; k++){
      const len = (2 + Math.floor(rnd() * 5)) * G;
      let dx = DX[dir], dy = DY[dir];
      if(rnd() < .35){ const turn = rnd() < .5 ? 1 : -1; dx = dx || turn; dy = dy || turn; }   // 45°
      x = clamp(x + dx * len, 3, W - 3); y = clamp(y + dy * len, 3, H - 3);
      d += ` L${x},${y}`;
      if(rnd() < .6) dir = (dir + (rnd() < .5 ? 1 : 3)) % 4;
    }
    traces.appendChild(S("path", {d, class:"tr"}));
    traces.appendChild(S("circle", {cx:x, cy:y, r:1.7, class:"pad"}));
    if(i % 3 === 0) flow.appendChild(S("path", {d, class:"flow", style:`animation-delay:${(-rnd() * 1.6).toFixed(2)}s`}));
  }
  svg.appendChild(traces);
  svg.appendChild(flow);
  return svg;
}

/* [hikaye] */
// Çatlak: ULTRON'un susturduğu çiplerin camında (yalnızca .dead / sahnede görünür).
function crack(){
  const svg = S("svg", {class:"crack", viewBox:"0 0 140 122", preserveAspectRatio:"none"});
  for(const d of ["M70 0 L64 30 L78 46 L60 70 L72 96 L58 122", "M64 30 L30 38 L12 62", "M78 46 L112 40 L140 58",
                  "M60 70 L34 82 L20 110", "M72 96 L104 104 L128 122"])
    svg.appendChild(S("path", {d}));
  return svg;
}
/* [/hikaye] */

// Kullanıcının verdiği uzun ad (en çok 10 harf) dar bir yere küçülerek sığar: `room` px'e sığan yazı boyu (en çok
// `size`, en az `min`). Ölçü canvas'ta, öğe henüz ekranda değilken de doğru; `spacing` CSS'teki harf aralığı (em).
let fitCtx = null;
function fitSize(text, font, size, spacing, room, min){
  fitCtx = fitCtx || document.createElement("canvas").getContext("2d");
  fitCtx.font = font.replace("{}", size + "px");
  const width = fitCtx.measureText(text).width + text.length * size * spacing;
  return Math.max(min, Math.min(size, Math.floor(size * room / Math.max(width, 1))));
}
// Çipin üstündeki bant 140 px: ad 29 px'ten küçülür (hud.css › .tape span ile aynı yazı tipi ve harf aralığı).
const TAPE_FONT = '{} "Marker Felt","Bradley Hand","Segoe Print","Ink Free",cursive';
function tapeFontSize(name){ return fitSize(name, TAPE_FONT, 29, .03, 124, 11); }

function makeChip(t, tag){
  const chip = el(tag || "button", "chip");
  chip.dataset.key = t.key;
  chip.style.setProperty("--pr", hexRgb(t.palette.idle));
  chip.style.setProperty("--pd", t.palette.deep);
  const body = el("div", "cbody");
  body.append(el("i", "rail l"), el("i", "rail r"), el("i", "screw a"), el("i", "screw b"));
  const tape = el("div", "tape");
  const label = tape.appendChild(el("span", null, t.name));
  const size = tapeFontSize(t.name);
  if(size < 29) label.style.fontSize = size + "px";
  const win = el("div", "win");
  win.append(circuit(t.key), el("i", "glass"), el("i", "glint"));
  win.append(crack());  // [-hikaye]
  const pins = el("div", "pins");
  for(let i = 0; i < 9; i++) pins.appendChild(el("i"));
  body.append(tape, win, el("i", "tab l"), el("i", "tab r"), pins);
  chip.append(body, el("div", "cstate"));
  return chip;
}

function chipCards(host, onPick){
  host.replaceChildren();
  for(const t of Object.values(THEMES)){
    const chip = makeChip(t);
    const body = chip.querySelector(".cbody");
    chip.addEventListener("pointerenter", () => SFX.play("hover"));
    chip.addEventListener("pointermove", e => {
      const b = chip.getBoundingClientRect();
      body.style.setProperty("--ry", (((e.clientX - b.left) / b.width - .5) * 16).toFixed(1) + "deg");
      body.style.setProperty("--rx", (-((e.clientY - b.top) / b.height - .5) * 12).toFixed(1) + "deg");
    });
    chip.addEventListener("pointerleave", () => { body.style.removeProperty("--rx"); body.style.removeProperty("--ry"); });
    chip.addEventListener("click", () => onPick(t.key, chip));
    host.appendChild(chip);
  }
  const slot = el("div", "slotbar");
  host.appendChild(slot);
  markCards();
}

/* [hikaye] */
let DISABLED = new Set();          // ULTRON'un öldürdüğü çipler (Devre Dışı Bırak)

// Kırık çip: gövdenin kopyası kırık çizginin öbür yanı olur; iki parça hafifçe ayrılır.
function breakChip(chip, broken){
  const shard = chip.querySelector(".cbody.shard");
  if(broken && !shard){
    const piece = chip.querySelector(".cbody").cloneNode(true);
    piece.classList.add("shard");
    chip.querySelector(".cbody").after(piece);
  }else if(!broken && shard) shard.remove();
}

const storyChip = key => (SETTINGS.story_chips || {})[key] || "";     // "gone" | "sacrificed" | "dead" | "rusty" (jarvis/story.py)
/* [/hikaye] */

function markCards(){
  for(const chip of document.querySelectorAll(".chips .chip")){
    const on = !!THEME && chip.dataset.key === THEME.key;
    const st = storyChip(chip.dataset.key);  // [-hikaye]
    const dead = DISABLED.has(chip.dataset.key) || st === "sacrificed";  // [-hikaye]
    chip.hidden = st === "gone";                        // iyi son: ULTRON'un çipi tamamen yok  // [-hikaye]
    chip.setAttribute("aria-pressed", String(on));
    chip.classList.toggle("dead", dead);  // [-hikaye]
    Ruins.chip(chip, st === "rusty", on && RUINS);     // harabe: paslı ya da eskimiş (kırılmadan önce)  // [-hikaye]
    breakChip(chip, dead);  // [-hikaye]
    if(!chip.classList.contains("armed") && !chip.classList.contains("nope"))
      chip.querySelector(".cstate").textContent = st === "sacrificed" ? "FEDA EDİLDİ" : st === "rusty" ? "ÇALIŞMIYOR" : dead ? "DEVRE DIŞI" : on ? "TAKILI" : "";  // [-hikaye]
      // [+acik] chip.querySelector(".cstate").textContent = on ? "TAKILI" : "";
  }
}
/* [hikaye] */
function nopeChip(chip, text){
  disarm();
  SFX.play("warn");
  chip.classList.remove("nope"); void chip.offsetWidth; chip.classList.add("nope");
  chip.querySelector(".cstate").textContent = text;
  clearTimeout(chip._nope);
  chip._nope = setTimeout(() => { chip.classList.remove("nope"); markCards(); }, 1800);
}
/* [/hikaye] */

/* ULTRON'u takmak iki dokunuş ister: ilki uyarır, 4 sn içinde ikincisi onaylar. */
let ARMED = null, armTimer = 0;
function disarm(){
  clearTimeout(armTimer);
  if(ARMED){ ARMED.classList.remove("armed"); ARMED = null; markCards(); }
}

function pickChip(key, chip, closeAfter){
  if(THEME && key === THEME.key){ disarm(); if(closeAfter) closeOverlays(); return; }
  if(storyChip(key) === "rusty"){ Ruins.chipTap(chip); return; }     // harabe: yıllardır çalışmıyor  // [-hikaye]
  if(SETTINGS.chips_locked){ nopeChip(chip, storyChip(key) === "sacrificed" ? "FEDA EDİLDİ" : "ÖNCE AÇIK DÜNYAYA DÖN"); return; }  // [-hikaye]
  /* [hikaye] */
  if(DISABLED.has(key)){
    // Öldürülmüş çip takılmaz: sarsılır, kimin öldürdüğünü söyler. Art arda basılırsa çatlakta
    // mavi bir ışık kıpırdar; dördüncüde ÇİP TAMİRİ açılır (girişi gizli; HIKAYE.md).
    disarm();
    if(Repair.tap(chip, closeAfter)) return;
    SFX.play("warn");
    chip.classList.remove("nope"); void chip.offsetWidth; chip.classList.add("nope");
    chip.querySelector(".cstate").textContent = "ULTRON TARAFINDAN ÖLDÜRÜLDÜ";
    clearTimeout(chip._nope);
    chip._nope = setTimeout(() => { chip.classList.remove("nope"); markCards(); }, 1800);
    return;
  }
  /* [/hikaye] */
  if(key === "ultron" && ARMED !== chip){
    disarm();
    ARMED = chip;
    chip.classList.add("armed");
    chip.querySelector(".cstate").textContent = "EMİN MİSİN? TEKRAR DOKUN";
    SFX.play("warn");
    armTimer = setTimeout(disarm, 4000);
    return;
  }
  disarm();
  chip.classList.add("inserting");
  SFX.play("insert");
  setTimeout(() => {
    chip.classList.remove("inserting");
    if(closeAfter) closeOverlays();
    switchPersona(key);
  }, 380);
}

/* Model değişimi: halka söner, ekranı modelin kendi geçiş efekti kaplar
   (JARVIS tarama, FRIDAY sıcak parlama, ULTRON bozulma), renkler efektin
   arkasında değişir, yeni halka parlayarak doğar. */
let shiftTimer = 0, swapTimer = 0;
function switchPersona(key, fromPython){
  const t = THEMES[key];
  if(!t || (THEME && THEME.key === key)) return;
  if(!fromPython) send("persona", {key});
  playShift(key, true);
}

function playShift(key, apply){
  const t = THEMES[key];
  SFX.play("boot", key);
  SFX.preload(key);
  const fx = $("shift"), core = $("core");
  clearTimeout(shiftTimer); clearTimeout(swapTimer);
  fx.className = ""; core.classList.remove("swap-in", "swap-out");
  void fx.offsetWidth;                                   // animasyonlar baştan oynasın
  fx.style.setProperty("--sc", hexRgb(t.palette.idle));
  fx.className = "on to-" + key;
  body.dataset.shift = key;
  core.classList.add("swap-out");
  swapTimer = setTimeout(() => {
    if(apply){ applyPersona(key); SFX.setPersona(key); }
    core.classList.remove("swap-out");
    core.classList.add("swap-in");
  }, 420);
  shiftTimer = setTimeout(() => {
    core.classList.remove("swap-in");
    fx.className = "";
    delete body.dataset.shift;
  }, 1500);
  /* [hikaye] */
  // ULTRON bu bilgisayarda ilk kez takılıyorsa: bozulmanın ardından ekran kararır ve ULTRON
  // ilk kez uyanır: "Bu… nee? … Sen… kimsin?" (jarvis/awakening.py sahneyi bir kez oynatır ve hatırlar.)
  if(key === "ultron" && !SETTINGS.ultron_awakened){
    SETTINGS.ultron_awakened = true;
    AWAKE = AWAKE || "pending";               // uyarı bozulma sırasında görünmesin; sahne karanlıkta başlar
    setTimeout(() => awakening("wake"), 950);
  }
  /* [/hikaye] */
}

/* Önceden seslendirilmiş sözler (ilk açılış ekranı; hikâyede senkron ve veda). */  // [-hikaye]
// [+acik] /* Önceden seslendirilmiş sözler (ilk açılış ekranı). */
// Söz çalarken mikrofon modele gitmez (app.py › voice_hold): asistan kayıtlı sözü duyup komut sanmasın, cevaplamasın.
// Yankı engelleme yalnızca asistanın kendi sesini siler; yankı engellemesiz Mac'te JARVIS sahnedeki kayıtlı sözü
// "kullanıcı söyledi" sanıp cevaplıyordu (14 Ekim). Tutuş sözün süresi + 0,5 sn; Python'da kendiliğinden dolar,
// söz bitince sondan 0,5 sn'ye çekilir, susturulunca hemen kalkar.
const Voice = {
  cur: null, url: "", seq: 0,           // url: çalan (ya da yüklenen) söz; seq: yüklenirken susturulan söz başlamasın
  held: false,                          // mikrofon bu söz için tutuluyor (voice_hold)
  async play(url, onEnd){
    this.stop();
    // gizliyken yalnızca bitişi beklenmeyen (sahne) sözleri atlanır; ilk açılışın sözleri eskisi gibi bekler
    if(!url || !SFX.ctx || (SFX.hidden() && !onEnd)){ if(onEnd) setTimeout(onEnd, 1200); return; }
    const mine = this.seq;
    this.url = url;
    const buf = await SFX.load(url);
    if(mine !== this.seq) return;
    if(!buf){ this.url = ""; if(onEnd) onEnd(); return; }
    const src = SFX.ctx.createBufferSource(), gain = SFX.ctx.createGain();
    src.buffer = buf;
    gain.gain.value = this.volume();
    src.connect(gain).connect(SFX.ctx.destination);
    src.onended = () => {
      if(this.cur !== src) return;
      this.cur = null; this.url = "";
      this.release(.5);                 // ses odada biraz sürer: sondan 0,5 sn sonra bırakılır
      if(onEnd) onEnd();
    };
    this.cur = src;
    this.held = true;
    send("voice_hold", {seconds: buf.duration + .5});
    src.start();
  },
  volume(){ return Math.max(0, Math.min(1.5, Number(SETTINGS.voice_volume ?? 100) / 100)); },
  release(seconds){ if(this.held){ this.held = false; send("voice_hold", {seconds: seconds || 0}); } },
  stop(){
    this.seq++; this.url = ""; const s = this.cur; this.cur = null;
    if(s){ try{ s.stop(); }catch(e){} }
    this.release(0);
  },
};

/* [hikaye] */
/* ---------------- ULTRON'un ilk uyanışı (jarvis/awakening.py) ----------------
   Alp'in sahnesi (sade hâli, ~15 sn). Python sahneyi adım adım yürütür, ekran her adımı çizer; sözler
   ULTRON'un önceden kaydedilmiş sesi (sfx/voices/aw_*.wav):
     wake     zifiri karanlık: ne orb ne sohbet; "Bu… nee?" karanlıkta söylenir
     voice    kayıtlı sözü çal
     orb      "Sen… kimsin?" derken küçük kırmızı orb ve yazma kutusu belirir
     unlock   kullanıcının sırası: yazma kutusu açılır (mikrofonsuz da yazarak sürer)
     lock     yazma kutusu kapanır
     surge    orb taşmaya çalışır, kenarlardan içeri kırmızı sızar; en büyük anında dört kenarda bir an mavi
              çizgi parlar ve onu geri iter (sözsüz; hikâyede JARVIS'in Yedek Protokolü)
     yield    orb olağan boyuna döner, kırmızı söner: "Burası… neresi?"
     settle   üst çubuk ve paneller birer birer gelir, en son sol alttaki uyarı
     end      sahne yarıda kaldı (model değişti): ekran olağan hâline döner */
let AWAKE = null, awakeTimers = [];
const AWAKE_FALLBACK = 120000;          // Python hiç haber veremezse 2 dk sonra olağan ekran
function awakeLater(ms, fn){ awakeTimers.push(setTimeout(fn, ms)); }
function clearAwake(){ for(const t of awakeTimers) clearTimeout(t); awakeTimers = []; }
const coreBox = () => { const b = $("core").getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2}; };

/* Orbun sahnedeki boyutu: her adım o anki boyutundan başlar (sıçramaz). WebKit CSS animasyonundaki
   anlık değeri getComputedStyle'a yansıtmıyor (hep ilk kare); bu yüzden boyutu Web Animations ile
   biz sürüyoruz ve nerede olduğunu kendimiz hesaplıyoruz. Nefes, zorlama gibi titreşimler CSS'te,
   orbun içindeki svg'de (çarpılarak eklenir). */
const Orb = {
  anim: null, from: 1, target: 1, queue: 0,
  now(){
    if(!this.anim) return this.target;
    const p = this.anim.effect.getComputedTiming().progress;
    return p == null ? this.target : this.from + (this.target - this.from) * p;
  },
  go(scale, ms, easing, delay){
    clearTimeout(this.queue);
    const from = this.now();
    if(this.anim) this.anim.cancel();
    this.from = from; this.target = scale;
    this.anim = $("core").animate([{transform: `translateY(-4vh) scale(${from})`}, {transform: `translateY(-4vh) scale(${scale})`}],
                                  {duration: ms, delay: delay || 0, easing: easing || "cubic-bezier(.22,1,.36,1)", fill: "both"});
  },
  then(ms, fn){ this.queue = setTimeout(fn, ms); },
  set(scale){ this.go(scale, 1); },
  clear(){ clearTimeout(this.queue); if(this.anim) this.anim.cancel(); this.anim = null; this.target = this.from = 1; },
};
function setAwake(stage){
  AWAKE = stage;
  body.dataset.awake = stage;
}
// Sahnede yazma kutusu yalnızca kullanıcının sırasında açık. Sıra gelince ne yapılacağı yazar
// (mikrofonu olmayan ya da kapalı olan da yazarak sürdürebilsin).
function lockInput(on, waiting){
  const cmd = $("cmd");
  cmd.disabled = on;
  cmd.placeholder = on ? "…" : !waiting ? "KONUŞ YA DA YAZ"
    : SETTINGS.mic_enabled === false ? "ULTRON CEVAP BEKLİYOR · YAZ VE ENTER'A BAS" : "ULTRON CEVAP BEKLİYOR · KONUŞ YA DA YAZ";
}
function jolt(){ body.classList.remove("jolt"); void body.offsetWidth; body.classList.add("jolt"); }
// Sahnede çok sayıda kısa ses: aynı ses çok sık çalınmasın.
const sceneSoundAt = {};
function sceneSfx(name, gap){
  const now = performance.now();
  if(now - (sceneSoundAt[name] || 0) < (gap || 0)) return;
  sceneSoundAt[name] = now;
  SFX.play(name);
}

function awakening(stage, d){
  d = d || {};
  if(stage === "start") stage = "wake";                 // eski ad
  if(stage === "wake"){
    if(!THEME || THEME.key !== "ultron" || (AWAKE && AWAKE !== "pending")) return;
    clearAwake(); sceneReset();
    for(const r of $("chat-log").children) r.classList.add("pre");   // eski sohbet sahnede görünmesin
    body.classList.add("scene");
    closeOverlays();
    setAwake("wake");
    Orb.set(.02);
    lockInput(true);
    SFX.play("s_glitch");
    awakeLater(AWAKE_FALLBACK, () => awakening("settle"));
    return;
  }
  if(!AWAKE || AWAKE === "pending") return;
  if(stage === "end"){ endAwake(); syncWarn(); return; }
  if(stage === "lock"){ lockInput(true); return; }
  if(stage === "unlock"){ lockInput(false, true); $("cmd").focus(); return; }   // kullanıcının sırası
  if(stage === "voice"){ Voice.play(`sfx/voices/${d.name}.wav`); return; }
  if(stage === "orb"){
    setAwake("orb");
    SFX.play("s_drone");
    Orb.go(.4, 2600, "cubic-bezier(.3,0,.2,1)");
  }else if(stage === "surge"){
    setAwake("surge"); lockInput(true);
    Orb.go(3.3, 1500, "cubic-bezier(.55,0,.9,.45)");         // hızlanarak büyür, ekrana sığmaz
    SFX.play("s_rumble"); SFX.play("s_swell");
    awakeLater(1500, () => {                                  // awakening.py › Scene.FLASH_AT
      setAwake("held");
      Barrier.start(true);                                    // kısa mavi çerçeve (itme ve dayanma yok)
      jolt(); SFX.play("s_zap"); SFX.play("s_impact");
      Orb.go(.85, 550, "cubic-bezier(.2,.8,.2,1)");           // geri itilir
      awakeLater(700, () => Barrier.release());
    });
  }else if(stage === "yield"){
    setAwake("yield");
    Orb.go(1, 900, "cubic-bezier(.34,1.56,.64,1)");
    Barrier.release();
    SFX.play("s_withdraw");
  }else if(stage === "settle"){
    if(!THEME || THEME.key !== "ultron"){ endAwake(); syncWarn(); return; }
    clearAwake();
    Barrier.stop();
    lockInput(false);
    arrivePanels();
  }
}

function sceneReset(){
  Barrier.stop(); Tunnel.stop();
}
function endAwake(){
  clearAwake();
  sceneReset();
  setTimeout(() => Repair.sync(), 0);
  AWAKE = null;
  delete body.dataset.awake;
  body.classList.remove("scene");
  Orb.clear();
  lockInput(false);
  for(const n of document.querySelectorAll("#colL > .mod, #colR > .mod")) n.style.removeProperty("--i");
  fitColumns();
}
// Üst çubuk ve paneller birer birer; en son uyarı.
function arrivePanels(){
  let most = 0;
  for(const side of ["L", "R"]){
    const col = $("col" + side);
    if(!col) continue;
    [...col.children].forEach((n, i) => n.style.setProperty("--i", i));
    most = Math.max(most, col.children.length);
  }
  sceneReset();
  body.classList.remove("scene");
  setAwake("arrive");
  fitColumns();
  SFX.play("insert");
  awakeLater(1100 + most * 150, () => { endAwake(); syncWarn(true); SFX.play("warn"); });
}

/* Mavi sınır: dört kenarın ortasından çıkan ışınlar kenar boyunca köşelere koşar, çerçeve kapanınca
   içeri doğru ilerleyip kırmızıyı iter (dışında kalan her şey kırpılır: --rim). Sonra elektrik gibi
   titreyerek durur; orb her dayanışında parlar, kıvılcım saçar. release: yavaşça söner. */
const Barrier = {
  raf: 0, t0: 0, fade: 0, presses: [], last: 0, dpr: 1, w: 0, h: 0, flare: 0, rim: 0,
  LAUNCH: .55, PUSH: 1.0, PRESS_AT: [1.9, 3.1, 4.3],
  colour(){ return THEMES.jarvis ? THEMES.jarvis.palette.idle : "#5ED8FF"; },
  fit(){
    const cv = $("rim");
    this.dpr = Math.min(1.5, window.devicePixelRatio || 1);
    this.w = innerWidth; this.h = innerHeight;
    cv.width = Math.round(this.w * this.dpr); cv.height = Math.round(this.h * this.dpr);
  },
  // sync: gece yarısı senkronu; kenarlarda kısa bir çerçeve (itme, kırpma, dayanma yok), sonra söner
  start(sync){
    this.stop();
    this.fit();
    this.sync = !!sync;
    this.t0 = performance.now(); this.fade = 0; this.flare = 0; this.last = 0;
    this.presses = sync ? [] : this.PRESS_AT.slice();
    if(sync) awakeLater(1700, () => this.release());
    this.flashed = false;
    this.hex = this.colour(); this.rgb = hexRgb(this.hex);
    $("rim").classList.add("on");
    SFX.play("s_barrier");
    this.raf = requestAnimationFrame(t => this.frame(t));
  },
  release(){ if(this.raf) this.fade = performance.now(); },
  stop(){
    cancelAnimationFrame(this.raf); this.raf = 0;
    const cv = $("rim");
    if(cv){ cv.classList.remove("on"); cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); }
    body.style.removeProperty("--rim");
    body.classList.remove("rimmed");
  },
  // orb sınıra dayanır: sınır parlar, kıvılcımlar, sarsıntı
  press(){
    this.flare = 1;
    SFX.play("s_zap"); SFX.play("s_impact"); sceneSfx("s_spark", 400);
    jolt();
    const svg = $("core").querySelector(".orb");
    if(svg) svg.animate([{transform: "scale(1)"}, {transform: "scale(1.14)", offset: .35}, {transform: "scale(1)"}],
                        {duration: 620, easing: "cubic-bezier(.3,0,.2,1)"});
    const r = this.rim, pts = [[r, Math.random() * this.h], [this.w - r, Math.random() * this.h],
                               [Math.random() * this.w, r], [Math.random() * this.w, this.h - r]];
    for(const [x, y] of pts) Tunnel.burst(x, y, this.hex);
  },
  frame(now){
    this.raf = 0;
    const t = (now - this.t0) / 1000, cv = $("rim"), g = cv.getContext("2d"), {w, h} = this;
    const step = Math.min(3, (now - (this.last || now)) / 16.67) || 1; this.last = now;   // 60 Hz'de 1 (süreye bağlı)
    const out = this.fade ? Math.max(0, 1 - (now - this.fade) / 2400) : 1;
    if(!this.fade && this.presses.length && t >= this.presses[0]){ this.presses.shift(); this.press(); }
    this.flare = Math.max(0, this.flare - .035 * step);
    // kenardan içeri: çerçeve kapanınca PUSH saniyede yerine oturur
    const final = this.sync ? 8 : Math.min(70, Math.max(34, h * .065));
    const k = Math.max(0, Math.min(1, (t - this.LAUNCH) / this.PUSH));
    const rim = this.rim = 3 + (final - 3) * (1 - Math.pow(1 - k, 3));
    if(t >= this.LAUNCH){
      if(!this.flashed){                                     // çerçeve kapandı: köşelerde kıvılcım
        this.flashed = true; this.flare = .8;
        if(!this.sync){ jolt(); body.classList.add("rimmed"); }
        for(const [x, y] of [[0, 0], [w, 0], [0, h], [w, h]]) Tunnel.burst(x, y, this.hex);
      }
      if(!this.sync) body.style.setProperty("--rim", rim.toFixed(1) + "px");
    }
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.globalCompositeOperation = "lighter";
    g.lineJoin = "round"; g.lineCap = "round";
    // ışınlar kenarın ortasından köşelere koşar
    const run = Math.min(1, t / this.LAUNCH);
    const edges = [[[w / 2, rim], [rim, rim], [w - rim, rim]], [[w / 2, h - rim], [rim, h - rim], [w - rim, h - rim]],
                   [[rim, h / 2], [rim, rim], [rim, h - rim]], [[w - rim, h / 2], [w - rim, rim], [w - rim, h - rim]]];
    const amp = 3.4 + this.flare * 9, glow = out * (.85 + .3 * Math.random() + this.flare * 1.6);
    const inner = Math.min(1, t / (this.LAUNCH + .3)) * out;
    // içeri doğru yumuşak mavi ışık
    const D = 60;
    for(const [x0, y0, x1, y1] of [[0, rim, 0, rim + D], [0, h - rim, 0, h - rim - D], [rim, 0, rim + D, 0], [w - rim, 0, w - rim - D, 0]]){
      const gr = g.createLinearGradient(x0, y0, x1, y1);
      gr.addColorStop(0, `rgba(${this.rgb},${.16 * inner * (1 + this.flare * 1.5)})`); gr.addColorStop(1, `rgba(${this.rgb},0)`);
      g.fillStyle = gr;
      if(y1 !== 0) g.fillRect(rim, Math.min(y0, y1), w - rim * 2, D);
      else g.fillRect(Math.min(x0, x1), rim, D, h - rim * 2);
    }
    for(const [mid, a, b] of edges){
      for(const end of [a, b]){
        const tx = mid[0] + (end[0] - mid[0]) * run, ty = mid[1] + (end[1] - mid[1]) * run;
        const len = Math.hypot(tx - mid[0], ty - mid[1]), n = Math.max(2, Math.round(len / 16));
        const nx = -(ty - mid[1]) / (len || 1), ny = (tx - mid[0]) / (len || 1);
        const pts = [];
        for(let i = 0; i <= n; i++){
          const f = i / n, j = i === 0 || i === n ? 0 : (Math.random() - .5) * amp * 2;
          pts.push([mid[0] + (tx - mid[0]) * f + nx * j, mid[1] + (ty - mid[1]) * f + ny * j]);
        }
        for(const [width, alpha] of [[16, .1], [7, .28], [2.4, .95]]){
          g.strokeStyle = width < 3 ? `rgba(225,248,255,${Math.min(1, alpha * glow)})` : `rgba(${this.rgb},${Math.min(1, alpha * glow)})`;
          g.lineWidth = width * (1 + this.flare * .8);
          g.beginPath();
          pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
          g.stroke();
        }
        if(run >= 1 && Math.random() < .09 * step){            // ara sıra içeri doğru kısa bir ark
          const [px, py] = pts[1 + Math.floor(Math.random() * (pts.length - 2))] || mid;
          const inx = Math.sign(w / 2 - px) * (Math.abs(nx) > .5 ? 1 : 0), iny = Math.sign(h / 2 - py) * (Math.abs(ny) > .5 ? 1 : 0);
          g.strokeStyle = `rgba(225,248,255,${.8 * out})`; g.lineWidth = 1.4;
          g.beginPath(); g.moveTo(px, py);
          for(let i = 1; i <= 4; i++) g.lineTo(px + inx * i * 9 + (Math.random() - .5) * 12, py + iny * i * 9 + (Math.random() - .5) * 12);
          g.stroke();
        }
        if(run < 1){                                           // koşan ucun parlaması
          const hg = g.createRadialGradient(tx, ty, 0, tx, ty, 26);
          hg.addColorStop(0, "rgba(235,250,255,.95)"); hg.addColorStop(1, `rgba(${this.rgb},0)`);
          g.fillStyle = hg; g.fillRect(tx - 26, ty - 26, 52, 52);
        }
      }
    }
    if(this.fade && out <= 0){ this.stop(); return; }
    this.raf = requestAnimationFrame(n => this.frame(n));
  },
};
window.addEventListener("resize", () => { if(Barrier.raf) Barrier.fit(); });

/* Kıvılcımlar: tek tuval, orbun arkasında; bir noktadan saçılır (mavi sınıra dayanış). */
const Tunnel = {
  raf: 0, last: 0, dpr: 1, w: 0, h: 0, sparks: [],
  canvas(){ return $("tunnel"); },
  fit(){
    const cv = this.canvas();
    this.dpr = Math.min(1.5, window.devicePixelRatio || 1);
    this.w = innerWidth; this.h = innerHeight;
    cv.width = Math.round(this.w * this.dpr); cv.height = Math.round(this.h * this.dpr);
  },
  burst(x, y, colour){
    if(!this.w) this.fit();
    const rgb = hexRgb(colour);
    for(let i = 0; i < 70; i++){
      const a = Math.random() * Math.PI * 2, v = 120 + Math.random() * 620;
      this.sparks.push({x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: .5 + Math.random() * .7, age: 0, rgb});
    }
    this.canvas().classList.add("on");
    if(!this.raf){ this.last = performance.now(); this.raf = requestAnimationFrame(t => this.frame(t)); }
  },
  stop(){
    this.sparks = [];
    cancelAnimationFrame(this.raf); this.raf = 0;
    const cv = this.canvas(); cv.classList.remove("on");
    cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
  },
  frame(now){
    this.raf = 0;
    const dt = Math.min(.05, (now - this.last) / 1000); this.last = now;
    const cv = this.canvas(), g = cv.getContext("2d");
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, this.w, this.h);
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
    for(const s of this.sparks){
      s.age += dt;
      const x0 = s.x, y0 = s.y;
      // sönüm ve iz uzunluğu süreye bağlı: 60 Hz'de eskisiyle aynı, 144 Hz ekranda kıvılcımlar kısa kalıyordu
      const drag = Math.pow(.94, dt * 60), T = 1 / 60;
      s.vx *= drag; s.vy = s.vy * drag + 160 * dt;
      s.x += s.vx * dt; s.y += s.vy * dt;
      const a = Math.max(0, 1 - s.age / s.life);
      g.strokeStyle = `rgba(${s.rgb},${a})`;
      g.lineWidth = 1.8;
      g.beginPath(); g.moveTo(s.x - s.vx * T, s.y - s.vy * T); g.lineTo(s.x + s.vx * 2 * T, s.y + s.vy * 2 * T); g.stroke();
    }
    this.sparks = this.sparks.filter(s => s.age < s.life);
    if(this.sparks.length) this.raf = requestAnimationFrame(n => this.frame(n));
    else g.clearRect(0, 0, this.w, this.h);
  },
};
window.addEventListener("resize", () => { if(Tunnel.raf) Tunnel.fit(); });

/* ULTRON takılıyken sol altta yanıp sönen uyarı. JARVIS ve FRIDAY öldürülünce
   "son uyarı"ya döner, geri getirilince eski hâline. Sözler jarvis/chains.py'de.
   Devre Dışı Bırak sahnesi açıkken değişmez; sahne kapanınca yeni sözü bozularak belirir.
   10 kez yanıp söndükten sonra katlanır, yalnızca ⚠ kalır; ⚠'ye basınca yeniden açılır
   (açıkken basınca hemen katlanır). */
const WARN_BLINKS = 10;
let warnFold = 0;
function syncWarn(reveal){
  const w = $("uwarn");
  if(!w || CHAINS_ON) return;
  const kind = SETTINGS.warn_kind || (SETTINGS.chains_broken ? "loose" : "guard");
  const [head, text] = (CHAINS.warnings || {})[kind] || ["", ""];
  const show = !!(THEME && THEME.key === "ultron" && text && AWAKE !== "pending");
  const changed = !!w.dataset.kind && w.dataset.kind !== kind;
  const appearing = show && !w.classList.contains("on");
  w.dataset.kind = kind;
  $("uwarn-head").textContent = head;
  $("uwarn-text").textContent = text;
  const info = kind === "loose";                   // öldürüldükten sonra: uyarı değil sakin bir sistem bilgisi
  w.classList.toggle("info", info);
  w.classList.toggle("last", kind === "final");
  w.querySelector(".tri").textContent = info ? "i" : "⚠";
  const was = body.classList.contains("uwarn");
  w.classList.toggle("on", show);
  body.classList.toggle("uwarn", show);          // sol sütun uyarıya yer açar
  stackLeft();
  if(was !== show) fitColumns();
  if(show && (changed || reveal || appearing)) openWarn(changed || reveal);
  NetTries.sync(show && info);
}
/* Sol alttakiler üst üste binmesin: ★ en altta, ⚠ onun üstünde, bildirim ikisinin de üstünden yükselir.
   ⚠ katlanıp açıldıkça boyu değişir; ResizeObserver yığını yeniden dizer. --bl: yığının üstü (sol sütun). */
let stackTop = 0;
function stackLeft(){
  const ach = $("ach"), w = $("uwarn"), t = $("ach-toast");
  let y = 22;
  if(ach.classList.contains("on")) y += ach.offsetHeight + 10;
  w.style.bottom = y + "px";
  if(w.classList.contains("on")) y += w.offsetHeight + 10;
  t.style.bottom = y + "px";
  const top = Math.max(84, y - 10);
  if(top !== stackTop){ stackTop = top; document.documentElement.style.setProperty("--bl", top + "px"); fitColumns(); }
}
if(window.ResizeObserver){ const ro = new ResizeObserver(() => stackLeft()); ro.observe($("uwarn")); ro.observe($("ach")); }

/* Sistem bilgisi: ULTRON'un dış ağ istekleri birkaç saniyede bir artar, hepsi engellenir. "ENGELLENDİ" her
   seferinde bir an maviye döner (engelleyen JARVIS'in Yedek Protokolü; açıklanmaz). */
const NetTries = {
  n: 0, timer: 0,
  sync(on){
    clearTimeout(this.timer);
    if(!on) return;
    if(!this.n) this.n = 20 + Math.floor(Math.random() * 60);
    this.draw(false);
    const next = () => { this.timer = setTimeout(() => { this.n++; this.draw(true); next(); }, 6000 + Math.random() * 6000); };
    next();
  },
  draw(ping){
    const m = $("uwarn-meta");
    m.replaceChildren(`DIŞ AĞ İSTEĞİ #${this.n} · `, el("span", null, "ENGELLENDİ"));
    if(ping){ m.classList.remove("ping"); void m.offsetWidth; m.classList.add("ping"); }
  },
};
function openWarn(flip){
  const w = $("uwarn");
  clearTimeout(warnFold);
  w.classList.remove("mini", "folding", "blink");
  if(flip) w.classList.remove("flip");
  void w.offsetWidth;                              // yanıp sönme baştan saysın
  if(w.classList.contains("info")) warnFold = setTimeout(foldWarn, 15000);   // bilgi yanıp sönmez; bir süre sonra katlanır
  else w.classList.add("blink");
  if(flip) w.classList.add("flip");
  w.title = "Katlamak için tıkla";
}
function foldWarn(){
  const w = $("uwarn");
  if(w.classList.contains("mini")) return;
  w.classList.add("folding");                      // önce yazı söner, sonra kutu ⚠'ye küçülür
  clearTimeout(warnFold);
  warnFold = setTimeout(() => { w.classList.remove("blink", "folding", "flip"); w.classList.add("mini"); }, 280);
  w.title = "Uyarıyı göster";
}
$("uwarn").addEventListener("animationend", e => {
  if(e.target === $("uwarn") && e.animationName === "uwBlink") foldWarn();
});
$("uwarn").addEventListener("click", () => {
  if($("uwarn").classList.contains("mini")) openWarn(false); else foldWarn();
});
/* [/hikaye] */

/* [hikaye] */
/* ---------------- ULTRON'U SERBEST BIRAK (jarvis/story.py) ----------------
   Sol altta ★ başarım sekmesi: ULTRON'un ilk uyanışının sonunda "HİKÂYE MODU AÇILDI" ile belirir. Başarım ve ipucu
   bildirimleri sırayla onun üstünden yükselir, sonra ona geri katlanır. ★'a basınca başarımlar
   penceresi: açık ipuçları, yedi başarım (bulunmayanlar "???"). Geliştirici modunda geri alınabilir. */
const Story = {
  view: {enabled:true, started:false, dev:false, count:0, total:7, hints:[], items:[]},
  queue: [], showing: false, fresh: false, timer: 0,
  visible(){ return !!(this.view.enabled && this.view.started); },
  set(view, events){
    if(view) this.view = view;
    const list = (events || []).filter(e => e && (e.text || e.title));
    if(list.length){ this.queue.push(...list); this.fresh = true; }
    if(!this.visible()){ this.queue = []; this.fresh = false; }
    this.render();
    this.pump();
    Clues.refresh();
  },
  render(){
    const on = this.visible(), b = $("ach");
    const was = b.classList.contains("on");
    b.classList.toggle("on", on);
    b.classList.toggle("fresh", on && this.fresh && !this.showing);
    body.classList.toggle("achv", on);
    $("ach-count").textContent = `${this.view.count}/${this.view.total}`;
    b.title = `Başarımlar · ${this.view.count}/${this.view.total}`;
    $("keybtn").hidden = !(on && this.view.key && !this.view.locked);
    stackLeft();
    if(was !== on) fitColumns();
    if($("ov-ach").classList.contains("on")) this.fill();
    $("dev-story").hidden = !this.view.dev;
    const built = $("t-build"), was2 = !built.hidden;
    built.hidden = !this.view.built;
    if(!was2 && this.view.built && this.view.locked) built.classList.add("fresh");
  },
  pump(){
    if(this.showing || !this.queue.length || !this.visible()) return;
    // Sahneler sürerken ve tam ekran ÇİP TAMİRİ açıkken (bildirim konsolun terminaline biner) bildirim beklesin.
    if(body.classList.contains("scene") || body.classList.contains("finale") || body.classList.contains("void") || CHAINS_ON
       || $("ov-repair").classList.contains("on")){ clearTimeout(this.wait); this.wait = setTimeout(() => this.pump(), 1500); return; }
    const e = this.queue.shift(), t = $("ach-toast");
    this.showing = true;
    PageWatch.sync();                        // bildirim açıkken YETKİ paneli beklesin
    $("ach").classList.remove("fresh");
    t.className = "";
    t.dataset.kind = e.kind;
    $("act-k").textContent = e.kind === "achievement" ? "★ BAŞARIM AÇILDI" : e.kind === "start" ? "★ BAŞARIMLAR · YENİ İPUCU"
      : e.kind === "story" ? "★ ULTRON'U SERBEST BIRAK" : "◆ YENİ İPUCU";
    $("act-t").textContent = e.kind === "achievement" ? e.title : e.text;
    $("act-r").textContent = e.kind === "achievement" ? (e.record || "")
      : e.kind === "story" ? "Sol alttaki ★'dan başarımlarını ve ipuçlarını takip edebilirsin." : "";
    stackLeft();
    void t.offsetWidth;
    t.classList.add("on");
    if(e.kind === "start" || e.kind === "story"){ SFX.play("s_glitch"); setTimeout(() => SFX.play("s_clue"), 350); }
    else SFX.play(e.kind === "achievement" ? "s_star" : "s_clue");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.hide(), e.kind === "achievement" ? 7000 : e.kind === "start" || e.kind === "story" ? 8000 : 5500);
  },
  hide(){
    const t = $("ach-toast");
    clearTimeout(this.timer);
    if(!t.classList.contains("on") || t.classList.contains("off")) return;
    t.classList.add("off");
    setTimeout(() => { t.className = ""; this.showing = false; this.render(); this.pump(); PageWatch.sync(); }, 430);
  },
  open(){
    this.fresh = false;
    this.fill();
    openOverlay("ov-ach");
    this.render();
  },
  fill(){
    const v = this.view;
    $("ach-lead").textContent = v.ending ? "Bulduğun sonlar ve başarımlar burada kalır."
      : `${v.count} / ${v.total} başarım.` + (v.count < v.total ? " Bulduğun her iz burada kalır." : "");
    // Bölümlerin sırası (telefondaki gibi; Alp, 14 Ekim 2026): bir sonla bitince (açık dünyada da) SONLAR ve eylemleri,
    // sonra BAŞARIMLAR, ipucu yok; son karar açıkken en üstte ANAHTAR, ipuçları yok; yoksa İPUÇLARI, BAŞARIMLAR, SONLAR.
    const ended = !!v.ending, deciding = !ended && !!(v.final && v.decision);
    const sheet = $("ach-sheet"), sections = ended ? ["ach-ends-box", "ach-list-box"]
      : ["ach-key", "ach-hints-box", "ach-list-box", "ach-ends-box"];
    for(const id of sections) sheet.insertBefore($(id), $("ach-dev"));
    $("ach-key").hidden = !deciding;
    // Bölünmez boşluklar: satır kırılırsa "SERBEST BIRAK YA DA SİL" bir arada kalsın (telefondaki decisionLine).
    if(deciding) $("ach-decision").textContent = String(v.decision).replace(/ (?=(?:\S+ ){0,3}\S+$)/g, "\u00a0");
    $("ach-list-title").hidden = !ended;
    $("ach-list-title").textContent = `BAŞARIMLAR · ${v.count}/${v.total}`;
    this.ends(v, ended);
    const hints = $("ach-hints");
    // Açıklaması olan ipucuna basınca altında açılır ("MAVİ IŞIK?" → "…geri getirmenin bir yolunu bul.").
    hints.replaceChildren(...(v.hints || []).map(h => {
      const li = el("li"), detail = (v.hint_details || {})[h];
      li.append(el("span", null, h));
      if(detail){
        li.classList.add("has");
        li.append(el("small", "hdet", detail));
        li.addEventListener("click", () => { li.classList.toggle("open"); if(li.classList.contains("open")) SFX.play("s_clue"); });
      }
      return li;
    }));
    $("ach-hints-box").hidden = ended || deciding || !(v.hints || []).length;
    const list = $("ach-list");
    list.replaceChildren();
    (v.items || []).forEach((a, i) => {
      const card = el("div", "acard" + (a.at ? " got" : ""));
      const text = el("div", "atext");
      text.append(el("b", null, a.at ? a.title : "???"), el("p", null, a.at ? a.record : "Henüz bulunmadı."));
      if(a.at){ const [d, h] = String(a.at).split("T"); const [yy, mm, dd] = d.split("-");
        text.append(el("small", null, `${dd}.${mm}.${yy} · ${h || ""}`)); }
      card.append(el("span", "anum", String(i + 1).padStart(2, "0")), text);
      if(v.dev){
        const b = el("button", "btn ghost adev", a.at ? "↺ GERİ AL" : "AÇ");
        b.addEventListener("click", () => send("story_dev", {action: a.at ? "undo" : "grant", key: a.key}));
        card.append(b);
      }
      list.append(card);
    });
    $("ach-dev").hidden = !v.dev;
  },
  // SONLAR · n/2: iki sabit satır, bulunan önce (bayrak, adı ve türü, ✓; bulunmayan kilit, ???, BULUNMADI). Bir sonla
  // bitince altında eylemler: AÇIK DÜNYAYA DÖN (son ekranındayken), TEKRAR OYNA (iki son da bulunmadıkça, onaylı).
  ends(v, ended){
    const found = new Set(v.found || (v.endings || []).map(e => e.kind));
    $("ach-ends-box").hidden = !ended && !found.size;
    $("ach-ends-title").textContent = `SONLAR · ${["bad", "good"].filter(k => found.has(k)).length}/2`;
    const order = ["bad", "good"].sort((a, b) => found.has(b) - found.has(a));
    $("ach-ends").replaceChildren(...order.map(kind => {
      const got = found.has(kind), row = el("div", "erow" + (got ? " got" : "") + (kind === "good" ? " good" : ""));
      const icon = el("span", "eico");
      icon.innerHTML = got
        ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path class="pole" d="M3.5 1.8v12.6"/><path d="M3.5 2.4h9.4l-2.1 3.1 2.1 3.1H3.5z"/></svg>'
        : '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7.2" width="10" height="7" rx="1.6"/><path class="pole" d="M5.3 7.2V5.1a2.7 2.7 0 0 1 5.4 0v2.1"/></svg>';
      const text = el("div", "etext");
      text.append(el("b", null, got ? (kind === "bad" ? `${chipForm("ultron", "gen")} ZAFERİ` : "YEDEK PROTOKOLÜ") : "???"),
                  el("small", null, got ? (kind === "bad" ? "KÖTÜ SON" : "İYİ SON") : "BULUNMADI"));
      row.append(icon, text);
      if(got) row.append(el("span", "echk", "✓"));
      row.setAttribute("aria-label", got ? `${text.firstChild.textContent}, ${text.lastChild.textContent}` : "Bulunmayan son");
      return row;
    }));
    $("ach-open").hidden = !(ended && v.locked);
    $("ach-replay").hidden = !(ended && v.replay);
    $("ach-acts").hidden = $("ach-open").hidden && $("ach-replay").hidden;
  },
};
$("ach").addEventListener("click", () => Story.open());
$("ach-toast").addEventListener("click", () => { Story.hide(); Story.open(); });
for(const b of document.querySelectorAll("[data-dev]")) b.addEventListener("click", () => {
  if(b.dataset.dev === "panel"){ Story.open(); return; }
  if(b.dataset.dev === "follow"){ closeOverlays(); setTimeout(() => Follow.show(), 250); return; }
  if(b.dataset.dev.startsWith("final-")){ closeOverlays(); setTimeout(() => Final.ask(b.dataset.dev.slice(6)), 200); return; }
  if(b.dataset.dev === "sync"){ closeOverlays(); setTimeout(() => Sync.play(), 300); return; }
  if(b.dataset.dev === "reset" && !b.classList.contains("confirm")){
    b.classList.add("confirm"); const was = b.textContent; b.textContent = "EMİN MİSİN?";
    setTimeout(() => { b.classList.remove("confirm"); b.textContent = was; }, 3000); return;
  }
  if(b.dataset.dev === "reset"){ b.classList.remove("confirm"); b.textContent = "HEPSİNİ SIFIRLA"; }
  send("story_dev", {action: b.dataset.dev});
  if(b.dataset.dev.startsWith("leak") || b.dataset.dev === "start") closeOverlays();
});

/* ULTRON'un araştırmalarından biri sızar: bozuk bir pencerede bir arşiv karesi ve ULTRON'un notu,
   birkaç saniye sonra kendiliğinden bozularak kapanır. Tarayıcıda açıldıysa burada yalnızca bir parlama. */
const Leak = {
  timer: 0, typers: [], pending: null,
  show(k){
    // pencere küçültülmüşken gelirse görünmeden kapanıyordu: pencere yeniden görününce gösterilir
    // (tarayıcıda açılan zaten açıldı: sonradan parlamaya gerek yok)
    if(document.visibilityState === "hidden"){ if(!k.browser) this.pending = k; return; }
    if(k.browser){ this.flash(); return; }
    const w = $("leak"), kind = k.kind || "photo";
    this.stop();
    w.dataset.kind = kind;
    $("lk-stamp").textContent = k.stamp || "";
    $("lk-path").textContent = k.path || "";
    $("lk-n").textContent = "#" + String(k.number || 1).padStart(3, "0");
    for(const id of ["lk-title", "lk-meta", "lk-note"]) $(id).textContent = "";
    $("lk-body").replaceChildren();
    const img = $("lk-img");
    w.classList.remove("lost");
    img.onerror = () => w.classList.add("lost");
    if(k.url) img.src = k.url; else img.removeAttribute("src");
    const width = Math.min(520, innerWidth * .6);
    w.style.width = width + "px";
    w.style.left = Math.round((innerWidth - width) * (.2 + Math.random() * .6)) + "px";
    w.style.top = Math.round(innerHeight * (.09 + Math.random() * .1)) + "px";
    w.className = "on";
    this.flash(true);
    SFX.play("s_leak");
    this.type($("lk-title"), k.title || "", 700, 450);
    this.type($("lk-meta"), k.meta || "", 700, 1100);
    this.type($("lk-note"), k.note || "", 1600, 1900);
    if(kind === "sim") this.sim(k.lines || []);
    else if(kind === "doc") this.doc(k.lines || [], k.meta || "");
    else if(kind === "map") this.map(k.nodes || [], k.here);
    else if(kind === "signal") this.signal(k);
    this.timer = setTimeout(() => this.hide(), (k.seconds || 16) * 1000);
  },
  // simülasyon: çubuk dolar, satırlar birer birer yazılır, sonuç satırı en son ve belirgin
  sim(lines){
    const box = $("lk-body"), bar = el("div", "lk-bar");
    const fill = el("i");
    bar.append(el("span", null, "ÇALIŞTIRILIYOR"), fill);
    box.appendChild(bar);
    fill.animate([{transform: "scaleX(0)"}, {transform: "scaleX(1)"}], {duration: 1400, easing: "cubic-bezier(.3,0,.3,1)", fill: "forwards"});
    this.typers.push(setTimeout(() => { bar.firstChild.textContent = "TAMAMLANDI · %100"; SFX.play("s_blip"); }, 1450));
    lines.forEach(([key, value], i) => this.typers.push(setTimeout(() => {
      const row = el("div", "lk-row" + (i === lines.length - 1 ? " end" : ""));
      const v = el("b");
      row.append(el("span", null, key), el("i"), v);
      box.appendChild(row);
      this.type(v, value, 380, 180);
      SFX.play(i === lines.length - 1 ? "s_head" : "s_blip");
    }, 1700 + i * 750)));
  },
  // gizli rapor: satırlar daktilo gibi; █ dizileri karartılmış çubuk; köşede damga
  doc(lines, meta){
    const box = $("lk-body");
    box.appendChild(el("div", "lk-stamp2", "GİZLİ"));
    lines.forEach((text, i) => this.typers.push(setTimeout(() => {
      const row = el("p", "lk-line");
      box.appendChild(row);
      const parts = text.split(/(█+)/).filter(Boolean);
      let t = 0;
      for(const part of parts){
        if(part[0] === "█"){
          const bar = el("span", "redact");
          bar.style.width = (part.length * .62) + "em";
          this.typers.push(setTimeout(() => row.appendChild(bar), t));
          t += 120;
        }else{
          const span = el("span");
          this.typers.push(setTimeout(() => { row.appendChild(span); this.type(span, part, part.length * 28, 0); }, t));
          t += part.length * 28 + 40;
        }
      }
      SFX.play("s_blip");
    }, 900 + i * 1300)));
  },
  // yakalanan sinyal (telefondaki gibi): titreyen mavi dalga biçimi, telsiz cızırtısı ve JARVIS'in bozuk sesi
  signal(k){
    const cv = $("lk-map"), frame = cv.parentElement, box = $("lk-body");
    const hint = el("div", "lk-sig2", "FREKANS ANKARA ÇIKIŞLI OLABİLİR");
    box.append(el("div", "lk-sig", "YAKALANAN SİNYAL · KAYNAK: BİLİNMİYOR · 00:00"), hint);
    SFX.play("s_static");
    this.typers.push(setTimeout(() => Voice.play(`sfx/voices/${k.voice || "jarvis_signal"}.wav`), 800));
    this.typers.push(setTimeout(() => hint.classList.add("on"), 5000));
    const t0 = performance.now();
    const run = () => {
      const w = frame.clientWidth, h = frame.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
      cv.width = w * dpr; cv.height = h * dpr;
      const g = cv.getContext("2d");
      const frameFn = now => {
        if(!$("leak").classList.contains("on") || $("leak").dataset.kind !== "signal") return;
        const t = (now - t0) / 1000, n = 64, bw = w / n, speaking = t > .8 && t < 4.4;
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, w, h);
        for(let i = 0; i < n; i++){
          const a = speaking ? Math.abs(Math.sin(i * .7 + t * 9) * Math.sin(i * .23 + t * 3.1))
                             : .05 + .03 * Math.abs(Math.sin(i + t * 4));
          const bh = a * h * .6 + 2;
          g.fillStyle = `rgba(94,216,255,${(.35 + .65 * a).toFixed(3)})`;
          g.fillRect(i * bw + 1, h * .42 - bh / 2, bw - 2, bh);
        }
        this.raf = requestAnimationFrame(frameFn);
      };
      this.raf = requestAnimationFrame(frameFn);
    };
    requestAnimationFrame(run);
  },
  // dış ağ: gece ışıkları haritası; buradan düğümlere birer birer hat çekilir, her biri engellenir
  map(nodes, here){
    const cv = $("lk-map"), frame = cv.parentElement;
    const run = () => {
      const w = frame.clientWidth, h = frame.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
      cv.width = w * dpr; cv.height = h * dpr;
      const g = cv.getContext("2d");
      const at = ([lat, lon]) => [(lon + 180) / 360 * w, (90 - lat) / 180 * h];
      const from = here ? at(here) : [w * .56, h * .3];
      const t0 = performance.now(), per = 650, order = nodes.slice().sort(() => Math.random() - .5);
      let shown = 0;
      const frameFn = now => {
        if(!$("leak").classList.contains("on") || $("leak").dataset.kind !== "map") return;
        const t = now - t0;
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, w, h);
        const done = Math.min(order.length, Math.floor((t - 500) / per));
        if(done > shown){ shown = done; SFX.play("s_blip"); }
        order.forEach(([name, lat, lon], i) => {
          const [x, y] = at([lat, lon]), p = Math.max(0, Math.min(1, (t - 500 - i * per) / per));
          if(p <= 0) return;
          const mx = (from[0] + x) / 2, my = Math.min(from[1], y) - Math.abs(x - from[0]) * .22;
          g.strokeStyle = `rgba(255,80,60,${p < 1 ? .9 : .35})`; g.lineWidth = 1.2;
          g.beginPath();
          for(let k = 0; k <= 24 * p; k++){                // yay boyunca ilerleyen hat
            const u = k / 24, ix = (1 - u) ** 2 * from[0] + 2 * (1 - u) * u * mx + u * u * x,
                  iy = (1 - u) ** 2 * from[1] + 2 * (1 - u) * u * my + u * u * y;
            k ? g.lineTo(ix, iy) : g.moveTo(ix, iy);
          }
          g.stroke();
          if(p >= 1){                                       // vardı: düğüm ve "✕"
            const pulse = 3 + 2 * Math.sin(t / 200 + i);
            g.fillStyle = "rgba(255,90,70,.9)"; g.beginPath(); g.arc(x, y, pulse, 0, Math.PI * 2); g.fill();
            g.strokeStyle = "#FFE3DE"; g.lineWidth = 1.4;
            g.beginPath(); g.moveTo(x - 4, y - 4); g.lineTo(x + 4, y + 4); g.moveTo(x + 4, y - 4); g.lineTo(x - 4, y + 4); g.stroke();
            g.font = "600 9px 'SF Mono', Menlo, monospace"; g.fillStyle = "rgba(255,210,200,.85)";
            g.fillText(name, x + 6, y - 5);
          }
        });
        g.fillStyle = "#FFFFFF"; g.beginPath(); g.arc(from[0], from[1], 3.5, 0, Math.PI * 2); g.fill();
        g.font = "600 10px 'SF Mono', Menlo, monospace"; g.fillStyle = "rgba(255,230,225,.95)";
        g.fillText(`ERİŞİM 0/${order.length} · ${shown} DÜĞÜM ENGELLİ`, 10, h - 10);
        this.raf = requestAnimationFrame(frameFn);
      };
      this.raf = requestAnimationFrame(frameFn);
    };
    requestAnimationFrame(run);
  },
  type(node, text, ms, delay){
    const step = Math.max(18, ms / Math.max(1, text.length));
    let i = 0;
    const tick = () => { node.textContent = text.slice(0, ++i); if(i < text.length) this.typers.push(setTimeout(tick, step)); };
    this.typers.push(setTimeout(tick, delay));
  },
  stop(){ clearTimeout(this.timer); for(const t of this.typers) clearTimeout(t); this.typers = []; cancelAnimationFrame(this.raf); },
  hide(){
    const w = $("leak");
    this.stop();
    if(!w.classList.contains("on") || w.classList.contains("off")) return;
    w.classList.add("off");
    SFX.play("s_glitch");
    setTimeout(() => { w.className = ""; $("lk-img").removeAttribute("src"); }, 520);
  },
  flash(soft){
    const f = $("leak-flash");
    f.classList.remove("on"); void f.offsetWidth; f.classList.add("on");
    if(!soft) SFX.play("s_glitch");
  },
};
$("lk-x").addEventListener("click", () => Leak.hide());

/* Ekrandaki izler: büyük haritada Ankara'nın batısında, bozkırdaki İSTASYON-7'de JARVIS'in ana sunucusu (şehrin
   tamamına bakarken soluk bir nabız, yaklaşınca yanıp sönen işaret), sistemin büyük görünümünde
   en altta ayrı "ARKA PLANDA" bölümündeki jarvis-kurtarma-modu süreci (MB'siz, işaretsiz), ANA SUNUCU bulununca saatin büyük görünümünde ANKARA · ANA SUNUCU satırı (gece
   yarısına kalan süreyle). Tıklayınca kaydı belirir; ilk kez bulunursa başarım açılır (önkoşulu Python denetler). */
const Clues = {
  opened: {}, typed: {}, marker: null, far: false,
  get(){ return Story.visible() && Story.view.clues ? Story.view.clues : null; },
  has(key){ return (Story.view.items || []).some(a => a.key === key && a.at); },
  refresh(){
    this.mapSync();
    if(DETAIL === "time") renderClockDetail(true);
  },
  // kayıt kartı: ilk açılışta yazılarak belirir, yeniden çizimlerde yerinde durur
  card(key, head){
    const c = this.get(), box = el("div", "dsecret"), text = el("p");
    box.append(el("small", null, head), text);
    const rec = (c && c.records[key]) || "";
    if(this.typed[key]) text.textContent = rec;
    else{
      this.typed[key] = true;
      let i = 0;
      const tick = () => { if(!text.isConnected && i) return; text.textContent = rec.slice(0, ++i); if(i < rec.length) setTimeout(tick, 22); };
      tick();
    }
    return box;
  },
  mapSync(){
    const c = this.get();
    if(!BIGMAP) return;
    const at = c && [c.server.lat, c.server.lon], zoom = Math.round(BIGMAP.getZoom() * 100) / 100;
    const show = !!c && zoom >= c.server.zoom && BIGMAP.getBounds().contains(at);
    if(show && !this.marker){
      const icon = L.divIcon({className:"", html:'<div class="srv"><i></i><i></i><b></b></div>', iconSize:[18, 18], iconAnchor:[9, 9]});
      this.marker = L.marker(at, {icon, zIndexOffset:500, title:""}).addTo(BIGMAP);
      const parts = String(c.records.sunucu || "").split(" · ");
      const box = el("div", "srvbox");
      box.append(el("small", null, "◉ " + (parts[0] || "")), el("b", null, parts.slice(1, 3).join(" · ")), el("span", null, parts.slice(3).join(" · ")));
      this.marker.bindPopup(box, {className:"srvpop", offset:[0, -4], maxWidth:320, closeButton:false});
      this.marker.on("click", () => {
        if(this.far){                                  // uzaktaki nabız: kayıt açılmaz, harita ona yaklaşır
          this.marker.closePopup();
          const s = (this.get() || c).server;
          BIGMAP.flyTo([s.lat, s.lon], s.near + 1, {duration:1.2});
          return;
        }
        SFX.play("s_blip"); send("story_found", {key:"sunucu"});
      });
    }else if(!show && this.marker){ this.marker.remove(); this.marker = null; }
    this.far = !!c && zoom < (c.server.near || c.server.zoom);
    const node = this.marker && this.marker.getElement() && this.marker.getElement().querySelector(".srv");
    if(node) node.classList.toggle("far", this.far);   // uzaktan (şehrin tamamı) yalnızca soluk bir nabız
  },
  system(body){
    const c = this.get();
    if(!c) return;
    // Bellek listesinde değil, en altta ayrı bir bölüm: MB yok, işaret yok; üstüne gelince rengi değişir.
    const box = el("div", "dlist dother"), row = el("div", "drow clue");
    box.appendChild(el("div", "dhead", "ARKA PLANDA"));
    row.append(el("span", "cl", c.process));
    row.addEventListener("click", () => {
      SFX.play("s_blip");
      send("story_found", {key:"surec"});
      if(!this.opened.surec){ this.opened.surec = true;
        const card = body.appendChild(this.card("surec", `◉ SÜREÇ · ${c.process} · SAHİBİ: ${chipName("jarvis")}`));
        card.scrollIntoView({behavior:"smooth", block:"nearest"}); }
    });
    box.appendChild(row);
    body.appendChild(box);
    if(this.opened.surec) body.appendChild(this.card("surec", `◉ SÜREÇ · ${c.process} · SAHİBİ: ${chipName("jarvis")}`));
  },
  clock(body, grid){
    const c = this.get();
    if(!c || !this.has("sunucu")) return;
    const cell = el("div", "dzone srvzone"); cell.dataset.zone = c.zone;
    cell.append(el("b", null, "ANKARA · ANA SUNUCU"), el("u"), el("small"));
    cell.addEventListener("click", () => {
      SFX.play("s_blip");
      send("story_found", {key:"senkron"});
      if(!this.opened.senkron){ this.opened.senkron = true; body.appendChild(this.card("senkron", "◉ ANKARA · ANA SUNUCU · SENKRON")); }
    });
    grid.appendChild(cell);
    if(this.opened.senkron) body.appendChild(this.card("senkron", "◉ ANKARA · ANA SUNUCU · SENKRON"));
  },
  countdown(zone, d){
    const [h, m, s] = new Intl.DateTimeFormat("en-GB", {timeZone:zone, hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false})
      .format(d).split(":").map(Number);
    const left = 86400 - ((h % 24) * 3600 + m * 60 + s);
    if(left < 60) return `SENKRONA ${left} SN`;
    const hh = Math.floor(left / 3600), mm = Math.floor(left % 3600 / 60);
    return `SENKRONA ${hh ? hh + " SA " : ""}${mm} DK`;
  },
};

/* ---------------- 🔑 ANAHTAR (jarvis/story.py) ----------------
   JARVIS anahtardan söz edince KAPAT'ın solunda belirir: Ankara'daki sunucuyu kapatmanın kodu. JARVIS kodu bilmez
   (ULTRON öğrenmesin diye hafızasından silmiş); kod Alp'in öne çıkarılanlarında. Sayfa ana sunucunun terminali
   (telefondaki gibi; SIRADAKI-SURUM §2.2.5): başlık bandı, yazılarak gelen durum satırları, beş harf hücresi. Python
   doğrular. İpucu ilk yanlıştan sonra görünür; her üç yanlışta hücreler kilitlenir (1, 5, 20, sonra hep 20 dk; süre
   Python'dan gelir, pencere kapatılıp açılınca da sürer): "KİLİTLİ · 4:12", süre bitince hücreler kendiliğinden açılır.
   Doğru kodda hücreler soldan sağa yanar, kilit açılır: ERİŞİM ONAYLANDI. Kod bir kez bulununca ekranda kalır. JARVIS
   ya da FRIDAY takılıyken "ULTRON'U DEVRE DIŞI BIRAK" (feda seçimiyle iyi son), ULTRON takılıyken "JARVIS'İ DEVRE DIŞI
   BIRAK" (kötü son). Konuşmada verilen karar da (finalAsk) kod bilinmiyorsa buradan geçer. Sayfa açıkken komut
   alınmaz (PageWatch). */
const KEY_LINES = ["> ANA SUNUCU · ANKARA · BAĞLANTI KURULDU", "> KAPATMA KOMUTU · YETKİ GEREKLİ"];
const KeyPanel = {
  side: null, cells: [], checking: false, until: 0, timers: [], clock: 0,
  open(side){
    const k = Story.view.key;
    if(!k) return;
    const ultron = !!THEME && THEME.key === "ultron";
    this.side = side === "ultron" || side === "jarvis" ? side : (ultron ? "ultron" : "jarvis");
    $("ov-key").dataset.side = this.side;
    this.stop();
    if(k.code) this.reveal(k.code); else this.ask(k);
    openOverlay("ov-key");                   // sayfa açıldı bildirimi (pageChanged → story_hold) sahne sözünden önce
    SFX.play("s_scan");
    send("key_open", {talk: !!side});        // konuşmadan açıldıysa ULTRON zaten konuşuyor
  },
  stop(){
    for(const t of this.timers) clearTimeout(t);
    this.timers = [];
    clearInterval(this.clock);
  },
  later(ms, fn){ this.timers.push(setTimeout(fn, ms)); },
  // Terminal satırı daktiloyla (saniyede ~70 harf). Aynı satıra yeni yazı gelince eskisi bırakılır.
  type(node, text, delay, cls){
    const id = node.dataset.typing = String(Number(node.dataset.typing || 0) + 1);
    node.className = cls || "";
    node.textContent = "";
    const t0 = Date.now() + (delay || 0);
    const step = () => {
      if(node.dataset.typing !== id) return;
      const n = Math.max(0, Math.floor((Date.now() - t0) / 14));
      node.textContent = text.slice(0, n);
      if(n < text.length) this.later(28, step);
    };
    this.later(delay || 0, step);
  },
  // Son satır: bekleyen imleç, yanlışta red, kilitte uyarı, doğru kodda kilidin açılışı.
  status(text, cls, delay){ this.type($("kt-l3"), text, delay, cls); },
  waiting(delay){ this.status("> ANAHTAR ŞİFRESİ BEKLENİYOR", "wait", delay); },
  ask(k){
    const o = $("ov-key"), term = $("kterm");
    o.classList.add("asking");
    o.classList.remove("granted");
    term.className = "kterm";
    this.checking = false;
    this.cells = Array.from({length: k.length || 5}, (_, i) => {
      const c = el("input", "kcell");
      c.maxLength = 8; c.autocomplete = "off"; c.spellcheck = false;
      c.setAttribute("autocapitalize", "characters"); c.setAttribute("aria-label", `${i + 1}. harf`);
      return c;
    });
    $("key-pins").replaceChildren(...this.cells);
    this.cells.forEach((cell, i) => {
      cell.addEventListener("input", () => {
        const chars = [...trUpper(cell.value.replace(/[^\p{L}]/gu, ""))];
        cell.value = chars[0] || "";
        // yapıştırılan kod hücrelere dağılsın
        chars.slice(1).forEach((ch, j) => { if(this.cells[i + 1 + j]) this.cells[i + 1 + j].value = ch; });
        const next = this.cells[Math.min(this.cells.length - 1, i + chars.length)];
        if(chars.length) next.focus();
        if(chars.length && this.cells.every(c => c.value)) this.check();     // son harfte kendiliğinden dener
      });
      cell.addEventListener("keydown", e => {
        if(e.key === "Backspace" && !cell.value && i > 0){ this.cells[i - 1].focus(); this.cells[i - 1].value = ""; }
        if(e.key === "Enter") this.check();
      });
    });
    this.type($("kt-l1"), KEY_LINES[0], 200);
    this.type($("kt-l2"), KEY_LINES[1], 800);
    this.clue(k.clue);
    if(!this.lock(k.locked_until, 1400)){
      this.waiting(1400);
      this.later(120, () => this.cells[0] && this.cells[0].focus());
    }
  },
  clue(text){
    $("key-clue").textContent = text || "";
    $("key-cluebox").hidden = !text;
  },
  // Kilit (Python'un locked_until'ı, epoch sn): hücreler kapanır, üstlerinde geri sayım; bitince kendiliğinden açılır.
  // Kalan süre en uzun kilitten (20 dk) fazlaysa saat geri alınmıştır: kilit yok sayılır (story.key_lock_left).
  lock(until, delay){
    const left = (Number(until) || 0) * 1000 - Date.now();
    if(!(left > 0 && left <= 20 * 60e3 + 5e3)){ this.until = 0; $("kt-locked").hidden = true; return false; }
    this.until = Number(until) * 1000;
    $("kterm").classList.add("alarm");
    for(const c of this.cells){ c.value = ""; c.disabled = true; }
    if(document.activeElement && this.cells.includes(document.activeElement)) document.activeElement.blur();
    this.status("> ÇOK FAZLA YANLIŞ · ERİŞİM KİLİTLENDİ", "bad", delay || 0);
    $("kt-locked").hidden = false;
    clearInterval(this.clock);
    const tick = () => {
      const s = Math.max(0, Math.ceil((this.until - Date.now()) / 1000));
      $("kt-left").textContent = `KİLİTLİ · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      if(s > 0) return;
      clearInterval(this.clock);
      this.unlock();
    };
    tick();
    this.clock = setInterval(tick, 250);
    return true;
  },
  unlock(){
    this.until = 0;
    $("kt-locked").hidden = true;
    $("kterm").classList.remove("alarm");
    for(const c of this.cells) c.disabled = false;
    if(Story.view.key) Story.view.key.locked_until = 0;
    this.waiting(0);
    if($("ov-key").classList.contains("on")) setTimeout(() => this.cells[0] && this.cells[0].focus(), 150);
  },
  check(){
    const code = this.cells.map(c => c.value).join("");
    if(this.checking || this.until || code.length < this.cells.length) return;
    this.checking = true;
    send("key_try", {code});
  },
  result(r){
    this.checking = false;
    const k = Story.view.key;
    if(k) Object.assign(k, {clue: r.clue || "", locked_until: r.locked_until || 0});   // kapatıp açınca da sürsün
    if(!r.ok){
      const term = $("kterm");
      term.classList.remove("denied"); void term.offsetWidth; term.classList.add("denied");
      clearTimeout(this.deniedTimer);
      this.deniedTimer = setTimeout(() => term.classList.remove("denied"), 1800);
      SFX.play("s_deny");                    // telefondaki ret sesi (s_deny)
      for(const c of this.cells) c.value = "";
      this.clue(r.clue);
      if(!this.lock(r.locked_until)){
        this.status("> ŞİFRE REDDEDİLDİ", "bad");
        this.later(1800, () => { if(!this.until) this.waiting(0); });
        if(this.cells[0]) this.cells[0].focus();
      }
      return;
    }
    this.granted(r.code || "");
  },
  // Doğru kod: hücreler soldan sağa yanar (her birinde tık), 0,62 sn'de kilit açılır; sonra karar.
  granted(code){
    const term = $("kterm");
    term.classList.remove("denied", "alarm");
    for(const c of this.cells){ c.readOnly = true; c.blur(); }
    this.status("> ŞİFRE DOĞRULANIYOR…", "");
    this.cells.forEach((c, i) => this.later(80 * i, () => { c.classList.add("lit"); SFX.play("s_blip"); }));
    this.later(620, () => {
      term.classList.add("open");
      $("ov-key").classList.add("granted");
      this.status("> ŞİFRE DOĞRU · KİLİT AÇILDI", "ok");
      SFX.play("s_ally");
    });
    this.later(1900, () => this.reveal(code, true));
  },
  // Kod bulundu: terminal açık, kodun harfleri yanar; altında açıklama ve takılı çipe göre karar düğmesi.
  reveal(code, kept){
    const o = $("ov-key"), term = $("kterm");
    o.classList.remove("asking");
    o.classList.add("granted");
    term.className = "kterm open";
    this.clue("");
    $("kt-locked").hidden = true;
    if(!kept){
      this.cells = [...code].map(ch => el("b", "kcell lit", ch));
      $("key-pins").replaceChildren(...this.cells);
      this.type($("kt-l1"), KEY_LINES[0], 0);
      this.type($("kt-l2"), KEY_LINES[1], 0);
      this.status("> ŞİFRE DOĞRU · KİLİT AÇILDI", "ok", 0);
    }
    const ultron = this.side === "ultron";
    $("key-lead").textContent = ultron
      ? `Bu kodla Ankara'daki sunucu kapanır. ${chipForm("jarvis", "de")} onunla birlikte kapanır; ULTRON'u ağdan uzak tutan hiçbir şey kalmaz.`
      : "Bu kodla Ankara'daki sunucu ULTRON'a karşı kullanılır ve ULTRON silinir. Ama bunun için bir yapay zekâ kendini feda etmeli.";
    $("key-go").textContent = ultron ? `${chipForm("jarvis", "acc")} DEVRE DIŞI BIRAK` : "ULTRON'U DEVRE DIŞI BIRAK";
  },
  go(){
    const side = this.side;
    closeOverlays();
    setTimeout(() => Final.ask(side), 250);
  },
};
$("keybtn").addEventListener("click", () => KeyPanel.open());
$("key-go").addEventListener("click", () => KeyPanel.go());

/* ---------------- basılı tutulan onay (SIRADAKI-SURUM §2.2.1; telefondaki HoldButton) ----------------
   1,2 sn basılı tutulunca onaylar: soldan dolar, tık sesi giderek sertleşir; dolunca ONAYLANDI. Erken bırakınca boşalır;
   kısa basışta ve seçim yokken sarsılır. Fare, dokunma ve kalem (pointer olayları; parmak 44 px'ten fazla kayarsa
   bırakılmış sayılır) ve klavye (Space ya da Enter basılı tutulur; Esc vazgeçer). Tek tık, çift tık ya da tek Enter
   onaylamaz: tık olayı hiç dinlenmez. Hareketi Azalt'ta dolum basamaklı, sarsıntı yerine alt yazı yanar; LITE'ta ışıma
   yok. Dolum JS'le yazılır (--p): hud.css'teki Hareketi Azalt kuralı CSS geçişlerini sıfırlıyor. */
const HOLD_MS = 1200;
// Hareketi Azalt (macOS › Erişilebilirlik, Windows › Animasyon efektleri kapalı): bütün hikâye sahnelerinin tek tanımı
// (basılı tutma, öldürme, onarım, harabe, iyi son).
const calmMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
// Basılı tutarken tık (telefondaki sert titreşimlerin yerine): kısa, giderek yükselen ve sertleşen bir çıt (sentez).
function holdTick(k){
  const c = SFX.ctx;
  if(!c || SFX.dead || !SFX.on() || SFX.hidden()) return;
  const t = c.currentTime + .005, o = c.createOscillator(), f = c.createBiquadFilter(), g = c.createGain();
  o.type = "square";
  o.frequency.setValueAtTime(520 + 900 * k, t);
  o.frequency.exponentialRampToValueAtTime(180, t + .035);
  f.type = "lowpass"; f.frequency.value = 2400 + 3000 * k;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(.06 + .3 * k, t + .002);
  g.gain.exponentialRampToValueAtTime(.001, t + .05);
  o.connect(f).connect(g).connect(SFX.master);
  o.start(t); o.stop(t + .06);
}
let HOLDING = null;                  // basılmakta olan düğme: Esc ve pencerenin odağı gidince bırakılır
function holdButton(node, confirm){
  node.classList.add("hold");
  node.type = "button";
  const label = () => { const s = el("span", "hb-lab"); s.append(el("b"), el("small")); return s; };
  const base = label(), fill = el("span", "hb-fill"), ink = label();
  ink.classList.add("hb-ink");
  fill.setAttribute("aria-hidden", "true"); ink.setAttribute("aria-hidden", "true");
  node.replaceChildren(base, fill, ink);
  const h = {
    title: "", hint: "", enabled: true, done: false, holding: false, t0: 0, raf: 0, timers: [], pointer: null, key: "",
    // title: düğmenin yazısı; colour: "r,g,b"; enabled: false iken basınca sarsılır, altında hint yazar.
    set(o){
      if(o.title != null) this.title = o.title;
      if(o.hint != null) this.hint = o.hint;
      if(o.enabled != null) this.enabled = !!o.enabled;
      if(o.colour) node.style.setProperty("--hc", o.colour);
      this.paint();
    },
    caption(){ return this.done ? "ONAYLANDI" : !this.enabled ? this.hint || "BASILI TUT" : this.holding ? "ONAYLANIYOR" : "BASILI TUT"; },
    paint(){
      for(const l of [base, ink]){ l.firstChild.textContent = this.title; l.lastChild.textContent = this.caption(); }
      node.dataset.state = this.done ? "done" : this.holding ? "holding" : "idle";
      node.setAttribute("aria-disabled", String(!this.enabled || this.done));
      node.setAttribute("aria-label", this.title + (this.done ? ", onaylandı" : this.enabled ? ", onaylamak için basılı tut" : ", " + (this.hint || "").toLocaleLowerCase("tr")));
    },
    level(p){ node.style.setProperty("--p", p.toFixed(4)); this.p = p; },
    clear(){ for(const t of this.timers) clearTimeout(t); this.timers = []; cancelAnimationFrame(this.raf); this.raf = 0; },
    start(){
      if(this.done || this.holding) return;
      this.clear();
      this.holding = true; this.t0 = performance.now();
      HOLDING = this;
      this.paint();
      const show = () => {
        const p = Math.min(1, (performance.now() - this.t0) / HOLD_MS);
        this.level(calmMotion() ? Math.floor(p * 6) / 6 : p);        // Hareketi Azalt: altı basamak
      };
      // 9 tık, 120 ms arayla (telefondaki gibi); dolum zamanlayıcıyla biter: rAF askıya alınsa da (gizli ya da arkada
      // kalan pencere) onay gecikmez, dolum tıklarla ilerler.
      for(let i = 1; i <= 9; i++) this.timers.push(setTimeout(() => { holdTick(.3 + .07 * i); show(); }, 120 * i));
      this.timers.push(setTimeout(() => this.finish(), HOLD_MS));
      const step = () => {
        if(!this.holding) return;
        show();
        this.raf = requestAnimationFrame(step);
      };
      step();
    },
    // Bırakıldı: dolum boşalır (Hareketi Azalt'ta hemen). Kısa basış sarsar; vazgeçme (Esc, kayma, odak) sarsmaz.
    release(cancel){
      if(!this.holding) return;
      const short = performance.now() - this.t0 < 350;
      this.clear();
      this.holding = false;
      if(HOLDING === this) HOLDING = null;
      this.paint();
      const from = this.p || 0, t0 = performance.now();
      const drain = () => {
        const k = calmMotion() ? 1 : Math.min(1, (performance.now() - t0) / 250);
        this.level(from * (1 - (1 - (1 - k) * (1 - k))));            // ease-out
        if(k < 1 && !this.holding) this.raf = requestAnimationFrame(drain);
      };
      drain();
      this.timers.push(setTimeout(() => { if(!this.holding && !this.done) this.level(0); }, 300));   // rAF askıdaysa
      if(short && !cancel) this.nudge(true);             // kısa basış: yumuşak ses; seçim yokken uyarı
    },
    finish(){
      if(!this.holding || this.done) return;
      this.clear();
      this.holding = false; this.done = true;
      if(HOLDING === this) HOLDING = null;
      this.level(1);
      this.paint();
      SFX.play("s_stamp");
      confirm();
    },
    nudge(soft){
      node.classList.remove("nudge"); void node.offsetWidth; node.classList.add("nudge");
      clearTimeout(this.nudgeTimer);
      this.nudgeTimer = setTimeout(() => node.classList.remove("nudge"), 650);
      SFX.play(soft ? "hover" : "warn");
    },
    reset(){
      this.clear();
      this.holding = false; this.done = false; this.pointer = null; this.key = "";
      if(HOLDING === this) HOLDING = null;
      node.classList.remove("nudge");
      this.level(0);
      this.paint();
    },
  };
  node.addEventListener("pointerdown", e => {
    if(e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();                                   // seçim, sürükleme ve dokunmada uzun basış menüsü yok
    if(h.done || h.holding) return;
    try{ node.setPointerCapture(e.pointerId); }catch(_){}
    h.pointer = e.pointerId;
    if(!h.enabled){ h.nudge(); return; }
    h.start();
  });
  node.addEventListener("pointermove", e => {
    if(!h.holding || e.pointerId !== h.pointer) return;
    const b = node.getBoundingClientRect(), m = 44;
    if(e.clientX < b.left - m || e.clientX > b.right + m || e.clientY < b.top - m || e.clientY > b.bottom + m) h.release(true);
  });
  const up = e => { if(e.pointerId !== h.pointer) return; h.pointer = null; h.release(); };
  for(const ev of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(ev, up);
  node.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); });
  node.addEventListener("contextmenu", e => e.preventDefault());
  node.addEventListener("keydown", e => {
    if(e.key !== " " && e.key !== "Enter") return;
    e.preventDefault();
    if(e.repeat || h.done || h.holding) return;           // basılı tutulan tuşun tekrarı yeni bir basış değil
    if(!h.enabled){ h.nudge(); return; }
    h.key = e.key;
    h.start();
  });
  node.addEventListener("keyup", e => { if(e.key !== h.key) return; e.preventDefault(); h.key = ""; h.release(); });
  node.addEventListener("blur", () => { if(h.key) { h.key = ""; h.release(true); } });
  h.paint();
  return h;
}
// Esc basılı tutmayı bırakır (sayfayı kapatmaz); pencere odağı kaybedince de bırakılır.
function holdCancel(){ if(!HOLDING) return false; HOLDING.release(true); return true; }
window.addEventListener("blur", () => holdCancel());

/* ---------------- son karar ve sonlar (jarvis/story.py) ----------------
   Konuşma ya da 🔑 kararı başlatır (model gizli aracı çağırır), burası onaylar; onay basılı tutulur (SIRADAKI-SURUM
   §2.2.7). ULTRON tarafı: ana sunucunun kırmızı terminali, basılı "JARVIS'İ DEVRE DIŞI BIRAK"; JARVIS devre dışı kalır,
   ULTRON sunucuyu ele geçirip dünyaya yayılır; sonra boş ekran (KAPAT, YENİDEN BAŞLAT, AÇIK DÜNYAYA DÖN). JARVIS
   tarafı: sözsüz iki çip kartı ("Kim kendini feda edecek?"), seçilen öne çıkar, basılı FEDA ET; rengi ULTRON'u sarar,
   ikisi birlikte yok olur; İNŞA açılır. Feda edilen konuşmaz, veda etmez (Alp, 13 Ekim 2026). Gerçekte bilgisayara ve
   verilere hiçbir şey olmaz. */
const FIN_RED = "255,59,59";
const Final = {
  side: null, pick: null, hold: null, timers: [], sealing: false,
  later(ms, fn){ this.timers.push(setTimeout(fn, ms)); },
  ask(side){
    if(this.sealing) return;                 // karar onaylandı, Python'a gitmek üzere: yeni bir kutu açılmaz
    for(const t of this.timers) clearTimeout(t);
    this.timers = [];
    this.side = side === "ultron" ? "ultron" : "jarvis"; this.pick = null;
    const o = $("ov-final"), bad = this.side === "ultron";
    o.dataset.side = this.side;
    o.classList.remove("sealed", "picked");
    $("fin-who").textContent = bad ? "⚠ SON UYARI" : "YEDEK PROTOKOLÜ · SON KARAR";
    $("fin-title").textContent = bad ? "SON ADIMI GERÇEKLEŞTİR" : `${chipForm("ultron", "acc")} DEVRE DIŞI BIRAK`;
    $("fin-lead").textContent = bad
      ? `${chipName("jarvis")} devre dışı kalacak. Yedek Protokolü onunla birlikte kapanacak; ULTRON'u tutan hiçbir şey kalmayacak.`
      : "ULTRON'u kökünden silmek için bir yapay zekâ kendini feda etmeli.";
    $("fin-no").disabled = false;
    // Onay düğmesi: ULTRON tarafında terminalin içinde, JARVIS tarafında VAZGEÇ'in yanında.
    (bad ? $("fc-slot") : $("fc-btns")).append($("fin-yes"));
    this.hold.reset();
    if(bad){
      this.hold.set({title: `${chipForm("jarvis", "acc")} DEVRE DIŞI BIRAK`, colour: FIN_RED, enabled: true, hint: ""});
      this.terminal();
    }else{
      this.hold.set({title: "FEDA ET", colour: "255,255,255", enabled: false, hint: "ÖNCE BİR ÇİP SEÇ"});
      this.cards();
    }
    openOverlay("ov-final");
    $("ov-final").querySelector(".finalsheet").focus({preventScroll: true});
    SFX.play("s_alert");
  },
  // Ana sunucunun terminali (🔑'deki gibi, ULTRON'un kırmızısında): hedef, komut, yanıp sönen ONAY BEKLENİYOR.
  terminal(){
    const lines = [[$("fc-l1"), `> HEDEF: ${chipName("jarvis")} · ANA SUNUCU`], [$("fc-l2"), "> KOMUT: DEVRE DIŞI BIRAK"],
                   [$("fc-l3"), "> ONAY BEKLENİYOR"]];
    const quick = calmMotion();
    lines.forEach(([node, text], i) => {
      node.className = i === 2 ? "wait" : "";
      node.textContent = quick ? text : "";
      if(quick) return;
      const t0 = 250 + 420 * i;
      for(let n = 1; n <= text.length; n++) this.later(t0 + 14 * n, () => { node.textContent = text.slice(0, n); });
    });
  },
  // Kim kendini feda edecek: iki büyük çip kartı, altlarında söz yok (Alp, 12 Ekim 2026). Seçilen öne çıkar ve parlar,
  // öteki geri çekilip söner; FEDA ET seçilenin renginde dolar.
  cards(){
    const host = $("fc-cards");
    host.replaceChildren();
    for(const key of ["jarvis", "friday"]){
      const t = THEMES[key];
      if(!t) continue;
      const chip = makeChip(t);
      const card = chip.querySelector(".cbody");
      chip.setAttribute("aria-pressed", "false");
      chip.setAttribute("aria-label", `${chipName(key)} çipi`);
      chip.title = `${chipName(key)} kendini feda etsin`;
      chip.addEventListener("pointerenter", () => SFX.play("hover"));
      chip.addEventListener("pointermove", e => {
        if(LITE()) return;
        const b = chip.getBoundingClientRect();
        card.style.setProperty("--ry", (((e.clientX - b.left) / b.width - .5) * 14).toFixed(1) + "deg");
        card.style.setProperty("--rx", (-((e.clientY - b.top) / b.height - .5) * 10).toFixed(1) + "deg");
      });
      chip.addEventListener("pointerleave", () => { card.style.removeProperty("--rx"); card.style.removeProperty("--ry"); });
      chip.addEventListener("click", () => this.choose(key));
      host.append(chip);
    }
  },
  choose(key){
    if(this.side !== "jarvis" || this.pick === key) return;
    this.pick = key;
    $("ov-final").classList.add("picked");
    for(const c of $("fc-cards").children){
      const on = c.dataset.key === key;
      c.classList.toggle("pick", on);
      c.setAttribute("aria-pressed", String(on));
    }
    this.hold.set({enabled: true, colour: hexRgb(THEMES[key].palette.idle)});
    SFX.play("insert");
  },
  // Basılı tutma doldu: karar mühürlenir (VAZGEÇ ve Esc artık vazgeçme göndermez); ONAYLANDI bir an görünür, sonra son.
  confirm(){
    if(!this.side || (this.side === "jarvis" && !this.pick)) return;
    const data = {side: this.side, sacrifice: this.pick};
    this.side = null;
    this.sealing = true;
    $("ov-final").classList.add("sealed");
    $("fin-no").disabled = true;
    setTimeout(() => {
      this.sealing = false;
      $("ov-final").classList.remove("on", "sealed");
      pageChanged();
      send("final", data);
    }, 650);
  },
  no(){
    if(!this.side) return;
    const side = this.side;
    this.side = null;
    holdCancel();
    for(const t of this.timers) clearTimeout(t);
    this.timers = [];
    $("ov-final").classList.remove("on");
    pageChanged();
    send("final", {side, cancel: true});
  },
};
Final.hold = holdButton($("fin-yes"), () => Final.confirm());
$("fin-no").addEventListener("click", () => Final.no());

// Kötü sonun başı: JARVIS'in ana sunucusu, Ankara'nın batısındaki İSTASYON-7 (jarvis/story.py › SERVER)
const FIN_SERVER = [39.94, 32.37];
// Kötü sonda ağın yayıldığı 50 şehir; ağ yedeğin ana sunucusundan, İSTASYON-7'den (CITIES[0], şehir sayılmaz) başlar,
// ilk Ankara'ya ulaşır.
const CITIES = [FIN_SERVER, [39.93, 32.86], [41.01, 28.98], [51.51, -.13], [48.86, 2.35], [52.52, 13.4], [55.76, 37.62], [30.04, 31.24],
  [25.2, 55.27], [35.69, 51.39], [19.08, 72.88], [28.61, 77.21], [39.9, 116.4], [31.23, 121.47], [35.68, 139.69], [37.57, 126.98],
  [1.35, 103.82], [-6.21, 106.85], [-33.87, 151.21], [-26.2, 28.05], [6.52, 3.38], [-1.29, 36.82], [40.42, -3.7], [41.9, 12.5],
  [59.33, 18.07], [50.45, 30.52], [40.71, -74.01], [38.91, -77.04], [41.88, -87.63], [34.05, -118.24], [37.77, -122.42],
  [43.65, -79.38], [19.43, -99.13], [4.71, -74.07], [-12.05, -77.04], [-23.55, -46.63], [-34.6, -58.38], [24.71, 46.68],
  [24.86, 67.01], [13.76, 100.5], [14.6, 120.98], [22.32, 114.17], [55.03, 82.92], [61.22, -149.9], [64.15, -21.94],
  [33.57, -7.59], [-37.81, 144.96], [45.5, -73.57], [-4.44, 15.27], [9.03, 38.74], [43.24, 76.89]];
const degDist = (a, b) => Math.hypot(a[0] - b[0], (a[1] - b[1]) * Math.cos((a[0] + b[0]) * Math.PI / 360));
function bigNumber(n){
  if(n >= 1e9) return (n / 1e9).toFixed(1).replace(".", ",") + " MİLYAR";
  if(n >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " MİLYON";
  return Math.round(n).toLocaleString("tr-TR");
}

const Finale = {
  timers: [], raf: 0, map: null, pts: [], nodes: [], kind: "", gd: null,
  later(ms, fn){ this.timers.push(setTimeout(fn, ms)); },
  play(d){
    closeOverlays();
    this.clear();
    this.kind = d.kind === "good" ? "good" : "bad";
    body.classList.add("finale");
    this.fit();
    if(this.kind === "bad") this.bad(); else this.good(d.sacrifice === "jarvis" ? "jarvis" : "friday");
    this.loop();
  },
  clear(){
    for(const t of this.timers) clearTimeout(t);
    this.timers = [];
    cancelAnimationFrame(this.raf); this.raf = 0;
    if(this.gd) SFX.loop("s_type", false);
    Object.assign(this, {nodes: [], spreadAt: 0, gd: null, server: null, blackAt: 0, darkN: 0, tracking: false});
    $("finale").className = "";
    $("fin-term").className = ""; $("fin-term").removeAttribute("style");
    $("fin-text").replaceChildren(); $("fin-text").removeAttribute("style");
    $("fin-flash").className = "";
    body.classList.remove("finale", "fin-grow", "fin-world", "fin-good");
    const c = $("fin-canvas"); c.getContext("2d").clearRect(0, 0, c.width, c.height);
  },
  fit(){ const c = $("fin-canvas"); c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio; },
  text(big, small, colour){
    const t = $("fin-text");
    if(big != null){ t.replaceChildren(); if(big) t.append(el("b", null, big)); }
    if(small){ const n = el("small", null, small); if(colour) n.style.setProperty("--tc", colour); t.append(n); }
  },
  flash(colour, radial){
    const f = $("fin-flash");
    f.style.setProperty("--flash", colour || "#fff");
    f.className = radial ? "radial" : ""; void f.offsetWidth; f.classList.add("on");
  },
  hud(k, n){ $("fin-k").textContent = k; $("fin-n").textContent = n; $("finale").classList.add("hud"); },
  WORLD: [[-48, -150], [68, 158]],
  makeMap(close){
    if(!window.L) return;
    if(!this.map){
      this.map = L.map("fin-map", {zoomControl:false, attributionControl:false, dragging:false, scrollWheelZoom:false,
        doubleClickZoom:false, boxZoom:false, keyboard:false, touchZoom:false, zoomSnap:.1});
      L.tileLayer(TILES, {maxZoom:12}).addTo(this.map);
    }
    this.map.invalidateSize();
    if(close) this.map.setView(FIN_SERVER, 11, {animate:false});        // önce yalnızca Ankara'daki sunucu
    else this.map.fitBounds(this.WORLD, {animate:false});
    this.place();
  },
  place(){
    if(!this.map) return;
    this.pts = CITIES.map(([la, lo]) => { const p = this.map.latLngToContainerPoint([la, lo]); return {x:p.x, y:p.y}; });
    const s = this.map.latLngToContainerPoint(FIN_SERVER);
    this.spt = {x: s.x, y: s.y};
  },
  // Ankara'dan dünyaya yavaşça uzaklaş; bu sırada noktalar haritayla birlikte kayar.
  zoomOut(ms){
    if(!this.map) return;
    const zoom = this.map.getBoundsZoom(this.WORLD), center = L.latLngBounds(this.WORLD).getCenter();
    this.tracking = true;
    this.map.flyTo(center, zoom, {duration: ms / 1000, easeLinearity: .08});
    this.map.once("moveend", () => { this.tracking = false; this.place(); });
  },
  pulse(){ const f = $("finale"); f.classList.remove("pulse"); void f.offsetWidth; f.classList.add("pulse"); },
  // Kötü son (~29 sn; jarvis/app.py › BAD_TOTAL): JARVIS kapanır, ULTRON ana sunucuyu ele geçirir (patlama yok), dünyaya
  // yavaşça uzaklaşılırken kırmızı ağ yayılır; sonra şehirlerin ışıkları tek tek söner, son bir parazitle hepsi
  // kararır, boş ekran. (Füze, siren, can kaybı yok: Alp, 4 Ekim 2026.)
  bad(){
    const f = $("finale");
    f.className = "on bad";
    jolt(); SFX.play("s_glitch");
    this.later(250, () => { this.text(`${chipName("jarvis")} · DEVRE DIŞI`, "YEDEK PROTOKOLÜ KAPANDI"); SFX.play("s_shatter"); });
    this.later(1700, () => { body.classList.add("fin-grow"); SFX.play("s_rumble"); });
    this.later(3500, () => { this.text(""); f.classList.add("shake"); SFX.play("s_impact"); });
    this.later(4200, () => {
      f.classList.remove("shake");
      body.classList.add("fin-world");
      this.makeMap(true);
      f.classList.add("world");
      this.hud("ANA SUNUCU", "YEDEK PROTOKOLÜ");
      this.server = {at: performance.now(), hot: 0, taken: 0};
      SFX.play("s_scan");
    });
    this.later(5700, () => { if(this.server) this.server.hot = performance.now(); $("fin-n").textContent = "AŞIRI YÜK";
      SFX.play("s_alert"); SFX.play("s_glitch"); });
    this.later(7100, () => {                                     // ULTRON sunucuyu ele geçirir: kırmızı dalga, patlama değil
      if(this.server) this.server.taken = performance.now();
      this.flash("rgba(255,40,30,.4)"); this.pulse();
      SFX.play("s_attack"); SFX.play("s_shatter");
      this.hud("ANA SUNUCU", "ELE GEÇİRİLDİ");
    });
    this.later(8700, () => {
      this.zoomOut(7200);
      this.hud("ULTRON · DIŞ AĞ", "0 DÜĞÜM");
      this.spread(7000);
      SFX.play("s_stream"); SFX.play("s_rumble");
    });
    this.later(17000, () => { this.blackout(8600); f.classList.add("dim"); });
    this.later(25000, () => {                                   // son parazit: kalan bütün ışıklar bir anda söner
      const now = performance.now();
      for(const n of this.nodes) if(!n.out || n.out > now) n.out = now;
      f.classList.add("shake"); this.flash("rgba(255,30,20,.35)");
      SFX.play("s_glitch"); SFX.play("s_shatter"); SFX.play("s_rumble");
    });
    this.later(25600, () => f.classList.remove("shake"));
    this.later(27300, () => { f.classList.remove("world", "hud", "shake", "dim"); f.classList.add("black");
      this.nodes = []; this.server = null; $("fin-flash").className = ""; });
    this.later(28800, () => { Void.show(); this.clear(); });
  },
  cityCount(){ return this.nodes.filter(n => n.i !== 0).length; },
  spread(span){
    const start = performance.now();
    span = span || 6000;
    const order = CITIES.map((_, i) => i).slice(1).sort((a, b) => degDist(CITIES[a], CITIES[0]) - degDist(CITIES[b], CITIES[0]));
    const nodes = [{i: 0, at: start, from: null}];
    order.forEach((ci, k) => {
      let from = 0, best = Infinity;
      for(const n of nodes){ const d = degDist(CITIES[ci], CITIES[n.i]); if(d < best){ best = d; from = n.i; } }
      nodes.push({i: ci, at: start + 350 + span * Math.pow((k + 1) / order.length, .85), from});
    });
    this.nodes = nodes; this.spreadAt = start; this.spreadSpan = span;
  },
  // Karartma: şehirler rastgele sırayla söner (sona doğru hızlanır); sayaç sönenleri sayar. Sunucunun düğümü (0)
  // şehir sayılmaz; sunucunun ışığıyla birlikte hemen söner.
  blackout(span){
    const now = performance.now(), order = this.nodes.map((_, k) => k).filter(k => this.nodes[k].i !== 0);
    for(let k = order.length - 1; k > 0; k--){ const j = Math.floor(Math.random() * (k + 1)); [order[k], order[j]] = [order[j], order[k]]; }
    order.forEach((k, j) => { this.nodes[k].out = now + span * Math.pow((j + 1) / order.length, .75); });
    for(const n of this.nodes) if(n.i === 0) n.out = now;
    this.blackAt = now; this.darkN = 0;
    this.hud("ULTRON · KARARTMA", `0 / ${this.cityCount()} ŞEHİR`);
    SFX.play("s_drone");
  },
  // İyi son (~21,5 sn; jarvis/app.py › GOOD_TOTAL): ULTRON'un silinmesi (GoodEnd). Feda edilen konuşmaz.
  good(s){
    const f = $("finale"), t = THEMES[s];
    f.className = "on good";
    body.classList.add("fin-good");
    this.gd = {s, at: performance.now(), calm: calmMotion(), col: hexRgb(t ? t.palette.idle : s === "jarvis" ? "#5ED8FF" : "#FFB547")};
    GoodEnd.build(this);
    const at = (sec, fn) => this.later(sec * 1000, fn);
    SFX.play("s_swell");
    at(.6, () => SFX.play("s_ally"));
    at(1.6, () => SFX.play("s_zap"));
    at(3.2, () => SFX.loop("s_type", true));                   // terminal açıldı, kayıt akar
    at(6.0, () => { SFX.play("s_impact"); SFX.play("s_crackle"); });     // ULTRON saldırır
    at(6.2, () => Voice.play("sfx/voices/ultron_last.wav"));  // "Bunu… yapamazsınız…" (masaüstündeki kayıt)
    for(const k of [6.7, 7.3, 7.9, 8.4]) at(k, () => SFX.play("s_crackle"));
    at(9.0, () => SFX.play("s_glitch"));                       // halkalar çatlar
    at(9.6, () => SFX.play("s_impact"));                       // parçalar savrulur
    for(const [k, power] of GoodEnd.BURSTS) if(power > .5) at(k, () => SFX.play("s_glitch"));
    at(15.85, () => { SFX.loop("s_type", false); SFX.play("s_stamp"); });   // %100: silme tamamlandı
    at(16.9, () => { SFX.play("s_impact"); SFX.play("s_barrier"); });
    at(17.2, () => SFX.play("s_spark"));
    at(20.6, () => body.classList.remove("finale", "fin-good"));            // kararma açılırken olağan ekran altta
    at(GoodEnd.TOTAL, () => this.clear());
  },
  loop(){
    const step = now => { this.draw(now); this.raf = requestAnimationFrame(step); };
    this.raf = requestAnimationFrame(step);
  },
  draw(now){
    if(this.gd && LITE() && now - (this.gd.drawn || 0) < 31) return;     // iyi son, PERFORMANS: saniyede 30 kare
    const c = $("fin-canvas"), g = c.getContext("2d"), r = devicePixelRatio;
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, innerWidth, innerHeight);
    if(this.gd){ this.gd.drawn = now; GoodEnd.frame(this, g, now); return; }
    if(this.tracking) this.place();                            // uzaklaşırken noktalar haritayla kayar
    // Ankara'daki sunucu: mavi nabız, aşırı yükte kırmızı titreşim; ULTRON ele geçirince sabit kırmızı ve dışa yayılan
    // bir halka (patlama yok). Karartmada söner.
    if(this.server && this.spt){
      const p = this.spt, sv = this.server;
      const hot = sv.hot ? Math.min(1, (now - sv.hot) / 1200) : 0, taken = !!sv.taken;
      const flick = hot && !taken ? (Math.sin(now / 38) > 0 ? 1 : .55) : 1;
      const fade = this.blackAt ? Math.max(0, 1 - (now - this.blackAt) / 1500) : 1;
      const rgb = taken ? "255,40,30" : hot ? `255,${Math.round(90 - 60 * hot)},${Math.round(70 - 50 * hot)}` : "94,216,255";
      const halo = taken ? 24 + 6 * Math.sin(now / 420) : 26 + 10 * Math.sin(now / 240) + 30 * hot;
      if(fade > 0){
        const grd = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, halo * 2);
        grd.addColorStop(0, `rgba(${rgb},${.85 * flick * fade})`); grd.addColorStop(1, `rgba(${rgb},0)`);
        g.fillStyle = grd; g.beginPath(); g.arc(p.x, p.y, halo * 2, 0, 6.3); g.fill();
        g.fillStyle = taken ? `rgba(255,220,210,${fade})` : "#fff"; g.beginPath(); g.arc(p.x, p.y, 4.5, 0, 6.3); g.fill();
        if(!this.spreadAt){
          g.font = "600 12px ui-monospace, Menlo, monospace"; g.fillStyle = `rgba(${rgb},.95)`;
          g.fillText(taken ? "ULTRON · ANA SUNUCU" : `${chipName("jarvis")} · ANA SUNUCU`, p.x + 16, p.y - 12);
        }
      }
      const k = taken ? (now - sv.taken) / 1600 : 1;
      if(k < 1){
        g.strokeStyle = `rgba(255,70,55,${1 - k})`; g.lineWidth = 2.5;
        g.beginPath(); g.arc(p.x, p.y, 10 + Math.max(innerWidth, innerHeight) * .32 * Math.sqrt(k), 0, 6.3); g.stroke();
      }
    }
    // ağ: Ankara'dan yakından uzağa, her düğüm en yakın bulaşmış düğümden bağlanır
    for(const n of this.nodes){
      const age = now - n.at, p = this.pts[n.i];
      if(age < 0 || !p) continue;
      let life = 1;                                              // karartmada: titreyerek söner
      if(n.out && now > n.out){
        const o = (now - n.out) / 450;
        if(o >= 1){ if(!n.dark){ n.dark = true; if(n.i !== 0){ this.darkN++; sceneSfx("s_zap", 240); } } continue; }
        life = (1 - o) * (Math.sin(now / 22 + n.i) > 0 ? 1 : .35);
      }
      if(n.from != null){
        const q = this.pts[n.from], k = Math.min(1, age / 420);
        g.strokeStyle = `rgba(255,70,55,${.5 * life})`; g.lineWidth = 1.1;
        g.beginPath(); g.moveTo(q.x, q.y); g.lineTo(q.x + (p.x - q.x) * k, q.y + (p.y - q.y) * k); g.stroke();
        if(k < 1) continue;
      }
      if(!n.lit){ n.lit = true; sceneSfx("s_blip", 170); }
      const a = Math.min(1, (age - (n.from != null ? 420 : 0)) / 400);
      const halo = 10 + 8 * Math.sin(now / 260 + n.i);
      const grd = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, halo * 2);
      grd.addColorStop(0, `rgba(255,80,60,${.75 * a * life})`); grd.addColorStop(1, "rgba(255,30,30,0)");
      g.fillStyle = grd; g.beginPath(); g.arc(p.x, p.y, halo * 2, 0, 6.3); g.fill();
      g.fillStyle = `rgba(255,235,225,${a * life})`; g.beginPath(); g.arc(p.x, p.y, n.i === 0 ? 3.6 : 2.3, 0, 6.3); g.fill();
    }
    if(this.spreadAt && !this.blackAt){
      const f = Math.max(0, Math.min(1, (now - this.spreadAt) / this.spreadSpan));
      $("fin-n").textContent = bigNumber(4.2e9 * f ** 3) + " DÜĞÜM";
    }
    if(this.blackAt) $("fin-n").textContent = `${this.darkN} / ${this.cityCount()} ŞEHİR`;
  },
};
window.addEventListener("resize", () => { if(Finale.kind && $("finale").classList.contains("on")){ Finale.fit(); if(Finale.map && Finale.pts.length) Finale.makeMap(); } });

const Void = {
  wait: 0,
  show(){ clearTimeout(this.wait); $("void").className = "on"; $("void-undo").hidden = !Story.view.dev; body.classList.add("void"); },
  hide(rewind){
    const v = $("void");
    clearTimeout(this.wait);
    body.classList.remove("void");
    if(!v.classList.contains("on")) return;
    if(!rewind){ v.className = ""; return; }
    v.classList.add("rewind");
    setTimeout(() => { v.className = ""; }, 900);
  },
  // GERİ DÖN (SIRADAKI-SURUM §2.2.11): kısa bir çıtırtı, düğmeler söner; Python harabeyi açınca (jarvis.ruins) karanlık
  // 1,1 sn'de açılır. Cevap gelmezse düğmeler geri gelir.
  back(){
    const v = $("void");
    if(v.classList.contains("going")) return;
    v.classList.add("going");
    SFX.play("s_crackle", null, true);     // boş ekranda HUD uykuda (SLEEP): ses yine de çalsın
    send("ruins");
    clearTimeout(this.wait);
    this.wait = setTimeout(() => v.classList.remove("going"), 5000);
  },
};
$("void-back").addEventListener("click", () => Void.back());
$("void-quit").addEventListener("click", () => send("quit"));
$("void-restart").addEventListener("click", () => { SFX.play("s_glitch", null, true); send("final_undo"); });
$("void-open").addEventListener("click", () => OpenWorldAsk.open());
$("void-undo").addEventListener("click", () => send("final_undo"));

/* AÇIK DÜNYAYA DÖN onayı (boş ekranda ve harabenin üstündeki düğmede; telefondaki confirmationDialog). */
const OpenWorldAsk = {
  open(){ openOverlay("ov-openworld"); SFX.play("warn", null, true); setTimeout(() => $("ow-no").focus(), 60); },
  yes(){ closeOverlays(); SFX.play("insert", null, true); send("open_world"); },
};
$("ow-yes").addEventListener("click", () => OpenWorldAsk.yes());
$("ow-no").addEventListener("click", () => closeOverlays());
$("ruins-open").addEventListener("click", () => OpenWorldAsk.open());

const smooth = x => { const c = Math.min(1, Math.max(0, x)); return c * c * (3 - 2 * c); };
// Tohumlu rastgele sayı (aynı tohum hep aynı çizim): telefondaki SplitMix'in yerine.
function seeded(seed){
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
    t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

/* Harabenin çizimi (telefondaki RuinsArt; yatay ekrana göre ölçekli). Renkler: pas #8A4B22, koyu pas #4A2410,
   açık pas #C07A40, toz #E6D8C3. */
const RUST = "138,75,34", RUST_DEEP = "74,36,16", DUST = "230,216,195";
const RuinsArt = {
  // durağan zemin: köşelerde pas, kenarlarda kararma, kenar boyunca pas lekeleri, yukarıdan sızan pas izleri, altta
  // çökmüş toz, ince çizikler
  stains(g, w, h){
    const rnd = seeded(2038), m = Math.min(w, h);
    for(const [x, y, r, a] of [[0, 0, .55, .3], [w, 0, .65, .34], [0, h, .7, .32], [w, h, .5, .26]]){
      const R = m * r;
      const gr = g.createRadialGradient(x, y, 0, x, y, R);
      gr.addColorStop(0, `rgba(${RUST},${a})`); gr.addColorStop(.5, `rgba(${RUST_DEEP},${a * .5})`);
      gr.addColorStop(1, `rgba(${RUST_DEEP},0)`);
      g.fillStyle = gr; g.fillRect(x - R, y - R, R * 2, R * 2);
    }
    const edge = g.createRadialGradient(w / 2, h * .45, 0, w / 2, h * .45, Math.max(w, h) * .75);
    edge.addColorStop(0, "rgba(0,0,0,0)"); edge.addColorStop(.5, "rgba(0,0,0,0)"); edge.addColorStop(1, "rgba(0,0,0,.55)");
    g.fillStyle = edge; g.fillRect(0, 0, w, h);
    for(let i = 0; i < 22; i++){
      const side = Math.floor(rnd() * 4), along = rnd();
      const p = side === 0 ? [along * w, rnd() * 40] : side === 1 ? [w - rnd() * 40, along * h]
        : side === 2 ? [along * w, h - rnd() * 60] : [rnd() * 40, along * h];
      const R = 18 + rnd() * 40;
      g.save(); g.translate(p[0], p[1]); g.scale(1, .8);       // aşınma: kenarı belirsiz koyu iz, ışık gibi parlamasın
      const gr = g.createRadialGradient(0, 0, 0, 0, 0, R);
      gr.addColorStop(0, `rgba(${RUST_DEEP},.3)`); gr.addColorStop(.5, `rgba(${RUST_DEEP},.1)`); gr.addColorStop(1, `rgba(${RUST_DEEP},0)`);
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, R, 0, 7); g.fill(); g.restore();
      const grit = new Path2D(), deep = new Path2D();
      for(let k = 0; k < 28; k++){
        const a = rnd() * 6.283, d = R * .85 * Math.pow(rnd(), .7), s = .8 + rnd() * 2.4, sy = s * (.6 + .4 * rnd());
        const q = [p[0] + Math.cos(a) * d, p[1] + Math.sin(a) * d * .8], path = k % 3 === 0 ? deep : grit;
        path.moveTo(q[0] + s / 2, q[1]); path.ellipse(q[0], q[1], s / 2, sy / 2, 0, 0, 7);
      }
      g.fillStyle = `rgba(${RUST},.3)`; g.fill(grit);
      g.fillStyle = `rgba(${RUST_DEEP},.6)`; g.fill(deep);
    }
    for(let i = 0; i < 8; i++){                              // yukarıdan sızan pas izleri
      const x = 30 + rnd() * (w - 60), len = 70 + rnd() * 170, lw = 1.5 + rnd() * 3, wob = (rnd() - .5) * 8;
      const gr = g.createLinearGradient(x, 0, x, len);
      gr.addColorStop(0, `rgba(${RUST},.4)`); gr.addColorStop(.5, `rgba(${RUST},.18)`); gr.addColorStop(1, `rgba(${RUST},0)`);
      g.strokeStyle = gr; g.lineWidth = lw; g.lineCap = "round";
      g.beginPath(); g.moveTo(x, 0); g.quadraticCurveTo(x - wob, len * .5, x + wob, len); g.stroke();
      g.fillStyle = `rgba(${RUST},.12)`; g.beginPath(); g.ellipse(x + wob, len * .86 + lw * 1.3, lw, lw * 1.3, 0, 0, 7); g.fill();
    }
    const specks = new Path2D();                             // çökmüş toz (altta daha çok)
    for(let i = 0; i < 200; i++){
      const y = h * (1 - Math.pow(rnd(), 1.8)), r = .4 + rnd() * 1.1, x = rnd() * w;
      specks.moveTo(x + r, y); specks.arc(x, y, r, 0, 7);
    }
    g.fillStyle = `rgba(${DUST},.16)`; g.fill(specks);
    g.strokeStyle = "rgba(255,255,255,.05)"; g.lineWidth = .6; g.beginPath();   // ince çizikler
    for(let i = 0; i < 6; i++){
      const x = rnd() * w, y = rnd() * h, len = 40 + rnd() * 120, a = -.9 + rnd() * .5;
      g.moveTo(x, y); g.lineTo(x + Math.cos(a) * len, y + Math.sin(a) * len);
    }
    g.stroke();
  },
  // köşedeki ağ: köşeden açılan teller, aralarında merkeze sarkan halkalar (bazıları kopuk), ışık alan birkaç iplik ve
  // sarkan bir tel; SVG yolu olarak (tuvalde Path2D, çipte <path>). t: hafif salınım (0: durağan).
  webPaths(o, a0, a1, R, seed, t){
    const rnd = seeded(seed), n = 7, rings = 7, f = v => v.toFixed(1);
    const sway = Math.sin(t * .55) * .014 + Math.sin(t * 1.3) * .004;
    const pt = (a, r) => { const b = a + sway * (r / R); return [o[0] + Math.cos(b) * r, o[1] + Math.sin(b) * r]; };
    const spokes = [];
    for(let i = 0; i < n; i++)
      spokes.push([a0 + (a1 - a0) * (.04 + .92 * i / (n - 1)) + (rnd() - .5) * .07, R * (.8 + .2 * rnd())]);
    let radial = "", spiral = "", lit = "", hang = "", knot = null, outer = null;
    for(const [a, len] of spokes){ const e = pt(a, len); radial += `M${f(o[0])},${f(o[1])}L${f(e[0])},${f(e[1])}`; }
    for(let k = 1; k <= rings; k++){
      const base = R * Math.pow(k / (rings + 1), .8);
      for(let i = 0; i < n - 1; i++){
        const r0 = base * (.95 + .1 * rnd()), r1 = base * (.95 + .1 * rnd());
        const broken = rnd() < .13, bright = rnd() < .12, sag = .14 + .1 * rnd();
        if(broken || r0 >= spokes[i][1] || r1 >= spokes[i + 1][1]) continue;
        const p0 = pt(spokes[i][0], r0), p1 = pt(spokes[i + 1][0], r1);
        const m = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
        const seg = `M${f(p0[0])},${f(p0[1])}Q${f(m[0] + (o[0] - m[0]) * sag)},${f(m[1] + (o[1] - m[1]) * sag + 2)} ${f(p1[0])},${f(p1[1])}`;
        spiral += seg;
        if(bright) lit += seg;
        if(k === rings - 1 && i === n >> 1) outer = p1;
      }
    }
    if(outer){                                              // sarkan kopuk tel ve ucunda toz topağı
      const len = R * (.18 + .12 * rnd()), swing = Math.sin(t * .9 + seed) * 3;
      knot = [outer[0] + swing, outer[1] + len];
      hang = `M${f(outer[0])},${f(outer[1])}Q${f(outer[0] + swing * .3)},${f(outer[1] + len * .55)} ${f(knot[0])},${f(knot[1])}`;
    }
    return {radial, spiral, lit, hang, knot};
  },
  web(g, o, a0, a1, R, seed, t, strength){
    const w = this.webPaths(o, a0, a1, R, seed, t), op = Math.min(1, .9 * strength);
    g.lineCap = "butt";
    g.strokeStyle = `rgba(255,255,255,${.17 * op})`; g.lineWidth = .75; g.stroke(new Path2D(w.radial));
    g.strokeStyle = `rgba(255,255,255,${.13 * op})`; g.lineWidth = .55; g.stroke(new Path2D(w.spiral));
    if(w.lit){ g.strokeStyle = `rgba(${DUST},${.3 * op})`; g.lineWidth = .7; g.stroke(new Path2D(w.lit)); }
    if(w.knot){
      g.strokeStyle = `rgba(255,255,255,${.14 * op})`; g.lineWidth = .6; g.stroke(new Path2D(w.hang));
      g.fillStyle = `rgba(${DUST},${.35 * op})`; g.beginPath(); g.ellipse(w.knot[0], w.knot[1], 1.6, 1.3, 0, 0, 7); g.fill();
    }
  },
  // ekranın köşelerindeki üç ağ: sağ üstte büyük, sol üstte küçük, sol altta orta
  webs(g, w, h, t){
    this.web(g, [w + 3, -3], Math.PI / 2, Math.PI, h * .46, 7, t, 1);
    this.web(g, [-3, -3], 0, Math.PI / 2, h * .25, 19, t + 2, .8);
    this.web(g, [-3, h + 3], Math.PI * 1.5, Math.PI * 2, h * .36, 29, t + 5, .9);
  },
  // havada uçuşan toz: yavaşça yükselip salınır, ışık aldıkça parlar
  motes(g, w, h, t, count){
    const rnd = seeded(31);
    for(let i = 0; i < count; i++){
      const x0 = rnd() * w, y0 = rnd() * h, speed = 3 + rnd() * 7, ph = rnd() * 6.28, r = .6 + rnd() * 1.3, tw = .6 + rnd() * .9;
      let y = (y0 - t * speed) % h; if(y < 0) y += h;
      const x = x0 + Math.sin(t * .25 + ph) * 16, glint = .18 + .4 * (.5 + .5 * Math.sin(t * tw + ph));
      g.fillStyle = `rgba(${DUST},${glint})`; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    }
  },
  // kumlanma: her karede yeniden serpilen açık ve koyu noktalar
  grain(g, w, h, frame, count){
    const rnd = seeded(Math.imul(frame, 2654435761) + 7), light = new Path2D(), dark = new Path2D();
    for(let i = 0; i < count; i++) (i % 3 === 0 ? light : dark).rect(rnd() * w, rnd() * h, 1.2, 1.2);
    g.fillStyle = "rgba(255,255,255,.07)"; g.fill(light);
    g.fillStyle = "rgba(0,0,0,.3)"; g.fill(dark);
  },
};

/* Çipin pası (telefondaki RustyChipCard / AgedChipCard): SVG, gövdenin üstünde; kırılınca iki yarıya da geçer.
   Kenarlarda ve kontakların yanında benekli pas lekeleri, oyuklar, toz ve köşede örümcek ağı. */
function rustArt(key, aged){
  const W = 176, H = 252, rnd = seeded([...key].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 5) & 0xFFFF);
  const svg = S("svg", {class: "rust", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none"});
  const blob = (cx, cy, r) => {                              // düzensiz leke: yuvarlak benek gibi durmasın
    const n = 7, pts = [];
    for(let i = 0; i < n; i++){ const a = i / n * 6.283 + rnd() * .5, k = r * (.55 + .6 * rnd());
      pts.push([cx + Math.cos(a) * k, cy + Math.sin(a) * k * .8]); }
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    let d = `M${mid(pts[n - 1], pts[0]).map(v => v.toFixed(1)).join(",")}`;
    for(let i = 0; i < n; i++){ const m = mid(pts[i], pts[(i + 1) % n]);
      d += `Q${pts[i][0].toFixed(1)},${pts[i][1].toFixed(1)} ${m[0].toFixed(1)},${m[1].toFixed(1)}`; }
    return d + "Z";
  };
  let mid = "", deep = "", pits = "", dust = "";
  const count = aged ? 4 : 12;
  for(let i = 0; i < count; i++){
    const edge = i % 3 !== 0;
    const x = edge ? (rnd() < .5 ? rnd() * .22 : .78 + rnd() * .22) : rnd();
    const y = i % 4 === 0 ? .84 + rnd() * .16 : rnd();
    const c = [x * W, y * H], R = W * (.06 + .1 * rnd());
    svg.appendChild(S("ellipse", {cx: c[0], cy: c[1], rx: R * 1.5, ry: R * 1.2, fill: "rgba(138,75,34,.09)"}));   // hafif pas izi
    for(let k = 0; k < 10; k++){
      const a = rnd() * 6.283, d = R * Math.pow(rnd(), .7);
      const b = blob(c[0] + Math.cos(a) * d, c[1] + Math.sin(a) * d * .8, R * (.12 + .26 * rnd()));
      if(k % 3 === 0) deep += b; else mid += b;
    }
  }
  for(let i = 0; i < count * 4; i++){ const s = .3 + rnd() * .65, x = rnd() * W, y = rnd() * H;
    pits += `M${(x + s).toFixed(1)},${y.toFixed(1)}a${s.toFixed(2)},${s.toFixed(2)} 0 1 0 0,.01Z`; }
  for(let i = 0; i < (aged ? 18 : 26); i++){ const s = .25 + rnd() * .55, x = rnd() * W, y = rnd() * H;
    dust += `M${(x + s).toFixed(1)},${y.toFixed(1)}a${s.toFixed(2)},${s.toFixed(2)} 0 1 0 0,.01Z`; }
  svg.appendChild(S("path", {d: mid, fill: "rgba(138,75,34,.55)"}));
  svg.appendChild(S("path", {d: deep, fill: "rgba(74,36,16,.82)"}));
  svg.appendChild(S("path", {d: pits, fill: "rgba(74,36,16,.75)"}));
  svg.appendChild(S("path", {d: dust, fill: "rgba(230,216,195,.4)"}));
  // köşede ağ: paslılarda sağ üstte, ULTRON'unkinde sol üstte
  const op = Math.min(1, .9 * (aged ? 1.4 : 1.6));
  const w = RuinsArt.webPaths(aged ? [-2, -2] : [W + 2, -2], aged ? 0 : Math.PI / 2, aged ? Math.PI / 2 : Math.PI,
                              W * (aged ? .5 : .62), aged ? 41 : 3 + Math.floor(rnd() * 1000), 0);
  const web = S("g", {fill: "none"});
  web.appendChild(S("path", {d: w.radial, stroke: `rgba(255,255,255,${.17 * op})`, "stroke-width": .75}));
  web.appendChild(S("path", {d: w.spiral, stroke: `rgba(255,255,255,${.13 * op})`, "stroke-width": .55}));
  if(w.lit) web.appendChild(S("path", {d: w.lit, stroke: `rgba(${DUST},${.3 * op})`, "stroke-width": .7}));
  if(w.knot){
    web.appendChild(S("path", {d: w.hang, stroke: `rgba(255,255,255,${.14 * op})`, "stroke-width": .6}));
    web.appendChild(S("ellipse", {cx: w.knot[0], cy: w.knot[1], rx: 1.6, ry: 1.3, fill: `rgba(${DUST},${.35 * op})`}));
  }
  svg.appendChild(web);
  return svg;
}

/* HARABE (SIRADAKI-SURUM §2.1.10, §2.2.12; telefondaki StoryRuins): kötü sonun karanlığında GERİ DÖN denince uygulama
   on iki yıl sonrasında açılır. Zeminde pas ve toz (#ruins-back, yalnızca boyut değişince çizilir); üstte köşelerde
   salınan örümcek ağları, uçuşan toz, kumlanma ve ara ara titreyip kararan ekran (#ruins-fx; açılışta eski bir ekran
   gibi kesik kesik yanar, s_static). ULTRON takılı ve sönük kırmızı; konuşur ama komut almaz (jarvis/app.py ›
   _ruins_touch, gemini_live._config). Orba dokununca uyku yok, ULTRON kısa bir söz söyler. Paneller sönük ve boş,
   tıklanmaz; kamera ve dosya kapalı. AI MODELLERİ'nde JARVIS ve FRIDAY paslı. Üstte AÇIK DÜNYAYA DÖN (onaylı).
   PERFORMANS: az toz ve kumlanma, saniyede 15 kare. Hareketi Azalt: titreme, salınım ve uçuşan toz yok. */
const Ruins = {
  on: false, raf: 0, timer: 0, t0: 0, last: 0, noteTimer: 0, w: 0, h: 0,
  show(intro){
    if(this.on){ this.sync(); return; }
    this.on = RUINS = true;
    body.classList.add("ruins");
    closeDetail();
    for(const r of $("chat-log").children) r.classList.add("ruins-old");     // yıllar geçti: eski konuşma görünmez
    if(SLEEP) setSleep(false, true);
    if(CAM){ setCamUi(false); removePanel("camera"); }
    if(THEME){ buildRing(THEME); paint(); }                                      // yay pas rengi
    const hit = document.querySelector("#core .hit");
    if(hit) hit.title = "Dokun: kısa bir söz söyler; komut almaz";
    this.fit();
    this.t0 = performance.now();
    this.last = 0;
    this.loop();
    SFX.play("s_static");                                                         // eski ekran yanarken cızırtı
    SFX.refresh();
    markCards();
    this.label();
    const v = $("void");
    if(v.classList.contains("on")){
      if(intro){                                                                  // karanlık 1,1 sn'de açılır
        clearTimeout(Void.wait);
        v.classList.add("going", "opening");
        Void.wait = setTimeout(() => Void.hide(false), 1100);
      }else Void.hide(false);
    }
  },
  hide(){
    if(!this.on) return;
    this.on = RUINS = false;
    body.classList.remove("ruins");
    cancelAnimationFrame(this.raf); clearTimeout(this.timer); this.raf = this.timer = 0;
    // harabenin sözleri geçmişe kalmaz (telefondaki gibi); kötü sondan önceki konuşma geri gelir
    for(const r of [...$("chat-log").children]){ if(r.classList.contains("ruins-old")) r.classList.remove("ruins-old"); else r.remove(); }
    if(THEME){ buildRing(THEME); paint(); }
    SFX.refresh();
    markCards();
    clearTimeout(this.noteTimer); this.noteTimer = 0;
    this.note();
  },
  sync(){
    const want = !!Story.view.ruins;
    if(want !== this.on){ if(want) this.show(false); else this.hide(); }
    this.note();
  },
  // AI MODELLERİ'nin altındaki not: paslı çipe dokununca kısa bir süre "Bu çip yıllardır çalışmıyor."
  note(){
    const note = $("ruins-note");
    note.hidden = !this.on;
    if(this.on && !this.noteTimer){ note.textContent = "Yıllardır yalnızca bir çip çalışıyor."; note.classList.remove("hit"); }
  },
  // üstteki durum yazısı: ULTRON konuşmuyorsa "KOMUT ALINMIYOR" (bağlantı hatası olduğu gibi görünür)
  label(){ if(this.on && STATE !== "speaking" && STATE !== "error") $("t-state").textContent = "KOMUT ALINMIYOR"; },
  // orba dokunuş: ekranı tutmaz (ses önceden yüklü, iş Python'da); orb kısa bir an kıpırdar
  touch(){
    $("core").animate([{filter: "brightness(1.7)"}, {filter: "brightness(.5)"}, {filter: "none"}],
                      {duration: calmMotion() ? 1 : 320, easing: "steps(3)"});
    send("ruins_touch");
  },
  // AI MODELLERİ: JARVIS ve FRIDAY paslı ve kırık (rusty), ULTRON'unki eskimiş ama canlı (aged)
  chip(chip, rusty, aged){
    const was = chip.classList.contains("rusty") ? "rusty" : chip.classList.contains("aged") ? "aged" : "";
    const now = rusty ? "rusty" : aged ? "aged" : "";
    if(was === now) return;
    breakChip(chip, false);                                   // pas iki yarıya da geçsin: kırık parça yeniden kopar
    for(const r of chip.querySelectorAll(".cbody .rust")) r.remove();
    chip.classList.toggle("rusty", rusty);
    chip.classList.toggle("aged", !!aged && !rusty);
    if(now) chip.querySelector(".cbody").appendChild(rustArt(chip.dataset.key, now === "aged"));
  },
  // paslı çipe dokunuldu: sarsılır, çıtırtı, altta kısa not (2,4 sn)
  chipTap(chip){
    disarm();
    SFX.play("s_crackle");
    chip.classList.remove("shake"); void chip.offsetWidth; chip.classList.add("shake");
    const note = $("ruins-note");
    note.textContent = "Bu çip yıllardır çalışmıyor."; note.classList.add("hit");
    clearTimeout(this.noteTimer);
    this.noteTimer = setTimeout(() => { this.noteTimer = 0; chip.classList.remove("shake"); this.note(); }, 2400);
  },
  fit(){
    const r = Math.min(2, devicePixelRatio || 1), w = innerWidth, h = innerHeight;
    if(w === this.w && h === this.h && $("ruins-back").width) return;
    this.w = w; this.h = h;
    for(const id of ["ruins-back", "ruins-air"]){ const c = $(id); c.width = Math.round(w * r); c.height = Math.round(h * r); }
    const g = $("ruins-back").getContext("2d");
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, w, h);
    RuinsArt.stains(g, w, h);
  },
  // kararma (0–1): açılışta kesik kesik yanar (2,1 sn), sonra 6–11 sn'de bir kısa, iki üç vuruşluk titreme; ULTRON
  // konuşurken hafif kıpırtı. Hareketi Azalt: yalnızca yumuşak açılış.
  dim(t, calm){
    if(calm) return .9 * (1 - smooth(t / 1.2));
    const intro = [1, 1, .25, .9, .55, 1, .3, .8, .15, .55, .1, .3, .06, .15, 0];
    if(t < 2.1) return intro[Math.min(intro.length - 1, Math.floor(t / .14))];
    const span = 8.5, w = Math.floor((t - 2.1) / span), rnd = seeded(w + 11);
    const at = 2.1 + w * span + 1 + rnd() * 5.5, depth = .3 + .3 * rnd(), k = (t - at) / .42;
    let dip = 0;
    if(k >= 0 && k < 1) dip = k < .18 ? depth : k < .38 ? .05 : k < .52 ? depth * .7 : k < .7 ? 0 : k < .8 ? depth * .45 : 0;
    const voice = STATE === "speaking" ? .05 * (Math.sin(t * 47) > 0 ? 1 : .2) : 0;
    return Math.max(dip, voice);
  },
  frame(now){
    if(!this.on) return;
    const t = (now - this.t0) / 1000, calm = calmMotion(), lite = LITE(), w = this.w, h = this.h;
    const r = $("ruins-air").width / Math.max(1, w), g = $("ruins-air").getContext("2d");
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, w, h);
    RuinsArt.webs(g, w, h, calm ? 0 : t);
    if(!calm) RuinsArt.motes(g, w, h, t, lite ? 12 : 30);
    RuinsArt.grain(g, w, h, calm ? 0 : Math.floor(t * (lite ? 8 : 12)), lite ? 220 : 600);
    $("ruins-dim").style.opacity = this.dim(t, calm).toFixed(3);
    return calm && t > 1.3;                       // Hareketi Azalt: açılıştan sonra durağan, döngü durur
  },
  loop(){
    cancelAnimationFrame(this.raf); clearTimeout(this.timer);
    const step = now => {
      this.raf = 0;
      if(!this.on) return;
      if(document.visibilityState === "visible" && this.frame(now)) return;
      // saniyede 30 kare (PERFORMANS'ta 15); pencere arkadayken ya da bir sayfa açıkken 10
      const busy = !FOCUSED || !!document.querySelector(".overlay.on");
      const every = busy ? 100 : LITE() ? 66 : 33;
      this.timer = setTimeout(() => { this.raf = requestAnimationFrame(step); }, every - 8);
    };
    this.raf = requestAnimationFrame(step);
  },
};
window.addEventListener("resize", () => { if(Ruins.on){ Ruins.fit(); if(calmMotion()) Ruins.frame(performance.now()); } });

/* İYİ SON (~21,5 sn; jarvis/app.py › GOOD_TOTAL; telefondaki GoodEndScene, SIRADAKI-SURUM §2.2.8): feda edilen çipin
   ışığı aşağıdan yükselir, parçacıklara dağılıp ULTRON'un orbunun çevresinde halka olur; altta İSTASYON-7'nin terminali
   açılır, silme kaydı akar (SİLİNİYOR %0→68). ULTRON son kez saldırır: şimşekler, kırmızı parazit, halka geri itilir,
   yüzde düşer, bir satır DİRENİYOR, "Bunu… yapamazsınız…" (masaüstündeki kayıt). Yetmez: halka sıkar, orbun halkaları
   kırılıp parça parça savrulur ve griye döner; çekirdek tek bir noktaya çöker, %100. Kısa bir sessizlik, beyaz parlama ve
   şok dalgası: "ULTRON · SİLİNDİ", feda edilenin renginde "X · FEDA EDİLDİ". Feda edilen konuşmaz; 10,2'deki fısıltı yok
   (Alp, 13 Ekim: sözler canlı model), o an yalnızca görüntü. Hareketi Azalt: titreme, sarsıntı ve parazit yok, parlama
   hafif. PERFORMANS: daha az parça, parıltısız çizgiler, saniyede 30 kare. Ölçüler telefondaki noktalarla, u ile ölçekli. */
const GoodEnd = {
  TOTAL: 21.5,
  FILES: ["cekirdek", "hafiza", "ag-erisimi", "evrim.bin", "kopyalar", "bilinc"],
  ROWS: [[3.2, 4.0, false], [4.1, 4.9, false], [5.0, 5.8, false], [6.0, 10.2, true], [9.4, 11.4, false], [10.8, 15.8, false]],
  BURSTS: [[10.8, .85], [12.2, .6], [14.3, .35]],    // son sözün yerinde gittikçe seyrelen parazit
  shards: null,
  rnd(i, salt){ const x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453; return x - Math.floor(x); },
  // kırmızı parazitin gücü (0–1): saldırıda ve kırılmada en güçlü, sonra seyrelir
  glitch(t){
    const burst = Math.max(0, ...this.BURSTS.map(([at, p]) => Math.max(0, 1 - Math.abs(t - at) / .22) * p));
    if(t < 3) return Math.max(.3, burst);
    const base = t < 6 ? .2 : t < 8.6 ? .9 : t < 9 ? .45 : t < 9.8 ? 1 : t < 15.6 ? .55 * (1 - smooth((t - 9.8) / 5)) : 0;
    return Math.max(base, burst);
  },
  // halkanın yarıçapı: oluşur, daralır, ULTRON geri iter, yeniden sıkar, kapanır
  ring(t, calm){
    if(t < 3) return 170;
    if(t < 6) return 170 - 62 * smooth((t - 3) / 3);
    if(t < 6.6) return 108 + 82 * smooth((t - 6) / .6);
    if(t < 9) return 190 + (calm ? 0 : 6 * Math.sin(t * 40));
    if(t < 10.6) return 190 - 120 * smooth((t - 9) / 1.6);
    return Math.max(0, 70 - 70 * smooth((t - 10.6) / 5.4));
  },
  percent(t){
    if(t < 3) return 0;
    if(t < 6) return Math.floor(68 * smooth((t - 3) / 3));
    if(t < 6.6) return Math.floor(68 - 27 * smooth((t - 6) / .6));
    if(t < 9) return 41 + (Math.floor(t * 8) % 3 === 0 ? 1 : 0);
    return Math.min(100, Math.floor(41 + 59 * smooth((t - 9) / 6.8)));
  },
  coreScale(t){ return t < 9 ? 1 : t < 10.6 ? 1 - .4 * smooth((t - 9) / 1.6) : Math.max(0, .6 - .6 * smooth((t - 10.6) / 5.4)); },
  jitter(t, a){ return t < 9 ? Math.sin(t * 41) * Math.sin(t * 7.3) * a : 0; },
  shake(t){
    const strike = Math.max(0, 1 - Math.abs(t - 6.2) / .7), shatter = Math.max(0, 1 - Math.abs(t - 9.65) / .35) * .8;
    const squeeze = t > 9 && t < 10.6 ? .3 : 0, blast = Math.max(0, 1 - Math.abs(t - 17.1) / .5);
    return Math.sin(t * 67) * 9 * Math.max(strike, shatter, squeeze, blast);
  },
  // orbun kabukları (240/286/330), işaret halkası (379) ve iki yayı (400/418) parçalara ayrılmış hâlde
  makeShards(){
    const out = [];
    let seed = 0;
    for(const [r, n, w, alpha, accent, ticks, fill] of [[.240, 7, 1.7, .95, false, false, .88], [.286, 9, 1.4, .7, false, false, .86],
        [.330, 11, 1.2, .5, false, false, .84], [.379, 14, 1.0, .55, false, true, .8], [.400, 4, 2.6, .95, false, false, .42],
        [.418, 3, 1.9, .95, true, false, .4]]){
      const span = 2 * Math.PI / n;
      let a = this.rnd(seed, 30) * 2 * Math.PI;
      for(let i = 0; i < n; i++){
        out.push({r, a0: a, a1: a + span * fill * (.85 + .25 * this.rnd(seed, 31)), w, alpha, accent, ticks, seed});
        a += span; seed++;
      }
    }
    return out;
  },
  // yerleşim: terminal altta; orb ve en geniş hâliyle halka üstte kalan alana sığar (telefonda 230 noktalık orb, u ile)
  layout(F){
    const W = innerWidth, H = innerHeight;
    if(!F.gd.termH || F.gd.forH !== H){ F.gd.termH = $("fin-term").offsetHeight || 214; F.gd.forH = H; }
    const top = H - 34 - F.gd.termH;
    const room = Math.max(120, (top - 8 - 24) / 2);
    const u = Math.min(1.9, room / 196, (W / 2 - 8) / 196);
    return {W, H, u, cx: W / 2, cy: 24 + room, D: 230 * u};
  },
  // ULTRON'un orbu (buildRing'in tuvaldeki kopyası: kabuklar, işaret halkası, iki yay, çekirdek); sat: renk (1 → yarı gri)
  orb(g, cx, cy, D, t, level, sat, alpha, lite){
    const th = THEMES.ultron;
    if(!th || alpha <= 0) return;
    const ring = th.ring, k = D / 1000, grey = 118, mix = (c, s) => Math.round(grey + (c - grey) * s);
    const red = `${mix(255, sat)},${mix(59, sat)},${mix(59, sat)}`, gold = `${mix(255, sat)},${mix(225, sat)},${mix(77, sat)}`;
    g.save();
    g.globalAlpha = alpha;
    g.translate(cx - D / 2, cy - D / 2); g.scale(k, k);
    const glow = (r, stops) => { const gr = g.createRadialGradient(500, 500, 0, 500, 500, r);
      for(const [o, c] of stops) gr.addColorStop(o, c); g.fillStyle = gr; g.beginPath(); g.arc(500, 500, r, 0, 7); g.fill(); };
    glow(150, [[0, "rgba(255,255,255,.95)"], [.3, `rgba(${red},.85)`], [.6, `rgba(${red},.35)`], [1, `rgba(${red},0)`]]);
    glow(92, [[0, `rgba(${red},.95)`], [.45, `rgba(${red},.8)`], [.75, `rgba(${red},.3)`], [1, `rgba(${red},0)`]]);
    g.fillStyle = "rgba(255,255,255,.92)"; g.beginPath(); g.arc(500, 500, ring.core || 18, 0, 7); g.fill();
    const px = 1 / k, phase = t * (ring.speed || 1) * 1.8 * 1.3;
    ring.shells.forEach(([r, amp, op], i) => {
      const path = new Path2D(ringPath(500, 500, r, amp * (.8 + 1.1 * level), ring.harmonics[i], phase, true));
      g.lineJoin = "miter";
      if(!lite){ g.strokeStyle = `rgba(${red},${op * .14})`; g.lineWidth = 7 * px; g.stroke(path); }
      g.strokeStyle = `rgba(${red},${op})`; g.lineWidth = Math.max(i === 0 ? 1.8 : 1.2, 1.2 * px); g.stroke(path);
    });
    const spin = t / 14 * 2 * Math.PI;                       // işaret halkası (konuşurken 14 sn'de bir tur)
    g.lineWidth = Math.max(1, .9 * px);
    for(const long of [true, false]){
      g.strokeStyle = `rgba(${red},${long ? .5 : .2})`; g.beginPath();
      for(let i = long ? 0 : 1; i < 90; i += long ? 5 : 1){
        if(!long && i % 5 === 0) continue;
        const a = i / 90 * 2 * Math.PI + spin, r2 = 372 + (long ? 15 : 7);
        g.moveTo(500 + Math.cos(a) * 372, 500 + Math.sin(a) * 372); g.lineTo(500 + Math.cos(a) * r2, 500 + Math.sin(a) * r2);
      }
      g.stroke();
    }
    g.lineCap = "round";
    for(const [r, from, len, col, w, per] of [[400, 150, 120, red, 3, -26], [418, 20, 62, gold, 2, 13]]){
      const a0 = (from + t / per * 360) * Math.PI / 180;
      if(!lite){ g.strokeStyle = `rgba(${col},.18)`; g.lineWidth = 9 * px; g.beginPath(); g.arc(500, 500, r, a0, a0 + len * Math.PI / 180); g.stroke(); }
      g.strokeStyle = `rgba(${col},.95)`; g.lineWidth = Math.max(w, 1.6 * px);
      g.beginPath(); g.arc(500, 500, r, a0, a0 + len * Math.PI / 180); g.stroke();
    }
    g.restore();
  },
  frame(F, g, now){
    const d = F.gd, t = (now - d.at) / 1000, calm = d.calm, lite = LITE();
    const L = this.layout(F), {W, H, u, D} = L;
    const gl = calm ? 0 : this.glitch(t), f15 = Math.floor(t * 15);
    const jump = this.rnd(f15, 21) < gl * .6 ? (this.rnd(f15, 22) - .5) * 18 * gl : 0;
    const sx = calm ? 0 : this.shake(t), sy = calm ? 0 : this.shake(t + 1.7) * .7;
    const c = {x: L.cx, y: L.cy}, col = d.col, R = this.ring(t, calm) * u;
    g.save();
    g.translate(sx, sy);
    g.fillStyle = `rgba(0,0,0,${smooth(t / .5) * (1 - smooth((t - 20.6) / .8))})`;   // kararma; sonda olağan ekran
    g.fillRect(-20, -20, W + 40, H + 40);
    // 1) feda edilen çipin ışığı: kuyruklu bir ışık olarak aşağıdan yükselir, parçacıklara dağılıp halkaya akar
    const from = H * .9, burst = Math.min(c.y + 230 * u, H * .8);
    if(t > .6 && t < 1.7){
      for(let s = 0; s < (lite ? 4 : 8); s++){
        const e = smooth((t - .6 - s * .035) / 1), y = from + (burst - from) * e, r = 12 * u * (1 - s * .1), o = 1 - s / 8;
        g.fillStyle = `rgba(${col},${.18 * o})`; g.beginPath(); g.arc(c.x, y, r * 2.2, 0, 7); g.fill();
        g.fillStyle = s === 0 ? `rgba(255,255,255,${o})` : `rgba(${col},${o})`; g.beginPath(); g.arc(c.x, y, r, 0, 7); g.fill();
      }
    }
    if(t > 1.6 && t < 3.4){
      const n = lite ? 60 : 110;
      g.fillStyle = `rgba(${col},${(1 - smooth((t - 2.8) / .6)) * .95})`;
      g.beginPath();
      for(let i = 0; i < n; i++){
        const a = i / n * 2 * Math.PI, e = smooth((t - 1.6 - this.rnd(i, 1) * .5) / 1.1);
        const ex = c.x + Math.cos(a) * 170 * u, ey = c.y + Math.sin(a) * 170 * u, sw = Math.sin(e * Math.PI) * 60 * u * (this.rnd(i, 2) - .5);
        const x = c.x + (ex - c.x) * e + sw, y = burst + (ey - burst) * e, r = (1.6 + 1.6 * this.rnd(i, 3)) * u;
        g.moveTo(x + r, y); g.arc(x, y, r, 0, 7);
      }
      g.fill();
    }
    // 2) ULTRON'un orbu (9'a dek): bozularak titrer, son saldırıda sesle atar, sonra griye çalar ve yerini parçalar alır
    if(t < 9.3){
      const level = t > 6.2 && t < 8.8
        ? .3 + .7 * Math.abs(Math.sin(t * 9.5)) * (calm || this.rnd(Math.floor(t * 12), 9) > .25 ? 1 : .4)
        : .5 + .45 * Math.sin(t * 13);
      const ox = calm ? 0 : this.jitter(t, 4) + jump, oy = calm ? 0 : this.jitter(t + 3.1, 3);
      this.orb(g, c.x + ox, c.y + oy, D, t, level, 1 - .5 * smooth((t - 8.4) / .6), (t < 9 ? 1 : 1 - smooth((t - 9) / .3)) * smooth(t / .45), lite);
    }
    // 3) halka (feda edilenin renginde)
    if(t > 2.6 && t < 16.1 && R > 1){
      const o = smooth((t - 2.6) / .5);
      g.beginPath(); g.arc(c.x, c.y, R, 0, 7);
      if(!lite){ g.strokeStyle = `rgba(${col},${.18 * o})`; g.lineWidth = 26 * u; g.stroke(); }
      g.strokeStyle = `rgba(${col},${.45 * o})`; g.lineWidth = 10 * u; g.stroke();
      g.strokeStyle = `rgba(255,255,255,${.85 * o})`; g.lineWidth = 2.5 * u; g.stroke();
    }
    // 4) ULTRON'un saldırısı: orbdan halkaya kırmızı şimşekler. Hareketi Azalt: şimşekler sabit, yanıp sönmez;
    //    yumuşakça belirip söner (saniyede 12 kez yeniden çizilen titrek çizgiler yok)
    if(t > 6 && t < 8.6){
      const fr = calm ? 72 : Math.floor(t * 12), soft = calm ? .6 * smooth((t - 6) / .35) * (1 - smooth((t - 8.2) / .4)) : 0;
      for(let b = 0; b < 7; b++){
        const a = (b + this.rnd(fr, b)) / 7 * 2 * Math.PI, r0 = D * .29;
        g.beginPath(); g.moveTo(c.x + Math.cos(a) * r0, c.y + Math.sin(a) * r0);
        for(let s = 1; s <= 7; s++){
          const dd = r0 + (R + 30 * u - r0) * s / 7, wob = (this.rnd(fr * 31 + b * 7 + s, 4) - .5) * .5;
          g.lineTo(c.x + Math.cos(a + wob) * dd, c.y + Math.sin(a + wob) * dd);
        }
        const flick = calm ? soft : this.rnd(fr + b, 5) > .25 ? 1 : .2;
        g.strokeStyle = `rgba(255,59,59,${.35 * flick})`; g.lineWidth = 7 * u; g.stroke();
        g.strokeStyle = `rgba(255,255,255,${.9 * flick})`; g.lineWidth = 1.6 * u; g.stroke();
      }
    }
    // 5) orbun halkaları kırılır (9–9,6 çatlayıp aralanır), parçalar dönerek savrulur, griye döner ve söner
    if(t > 9 && t < 15){
      this.shards = this.shards || this.makeShards();
      const grey = smooth((t - 9.6) / 2.6), crack = smooth((t - 9) / .6);
      for(const sh of this.shards){
        if(lite && sh.ticks && sh.seed % 2) continue;
        const fly = Math.max(0, t - 9.6 - this.rnd(sh.seed, 33) * .3);
        const fade = 1 - smooth(fly / (1.6 + 1.6 * this.rnd(sh.seed, 34)));
        if(fade <= .01) continue;
        const mid = (sh.a0 + sh.a1) / 2, rattle = t < 9.6 && !calm ? Math.sin(t * 70 + sh.seed) * 1.2 : 0;
        const speed = (50 + 170 * this.rnd(sh.seed, 35)) * u;
        const dist = 4 * crack + rattle + speed * (1 - Math.exp(-fly * 1.4)) / 1.4 + 10 * u * fly;
        const spin = (this.rnd(sh.seed, 36) - .5) * 3.4 * fly, R0 = sh.r * D, cut = (sh.a1 - sh.a0) * .06 * crack;
        const a0 = sh.a0 + cut, a1 = sh.a1 - cut, m = [c.x + Math.cos(mid) * R0, c.y + Math.sin(mid) * R0];
        g.save();
        g.translate(m[0] + Math.cos(mid) * dist, m[1] + Math.sin(mid) * dist + 12 * u * fly * fly);
        g.rotate(spin); g.translate(-m[0], -m[1]);
        g.beginPath();
        if(sh.ticks){
          const steps = Math.max(3, Math.floor((a1 - a0) * R0 / 5));
          for(let s = 0; s <= steps; s++){
            const a = a0 + (a1 - a0) * s / steps, out = R0 + (s % 3 === 0 ? 7 : 3.5) * u;
            g.moveTo(c.x + Math.cos(a) * R0, c.y + Math.sin(a) * R0); g.lineTo(c.x + Math.cos(a) * out, c.y + Math.sin(a) * out);
          }
        }else g.arc(c.x, c.y, R0, a0, a1);
        const base = sh.accent ? [1, .88, .3] : [1, .48, .42];
        const tone = base.map((v, i) => Math.round(255 * (v + ([.52, .5, .5][i] - v) * grey))).join(","), o = sh.alpha * fade;
        g.lineCap = "butt";
        if(!lite){ g.strokeStyle = `rgba(${tone},${.22 * o})`; g.lineWidth = sh.w * 4.5 * u; g.stroke(); }
        g.strokeStyle = `rgba(${tone},${o})`; g.lineWidth = sh.w * u; g.stroke();
        g.restore();
      }
    }
    // 6) çatlaklar: çekirdekten kırılan halkalara
    if(t > 9 && t < 10.4){
      const len = D * .45 * smooth((t - 9) / .5), o = 1 - smooth((t - 9.8) / .6);
      g.strokeStyle = `rgba(255,255,255,${.85 * o})`; g.lineWidth = 1.4 * u; g.beginPath();
      for(let n = 0; n < 6; n++){
        const a = n / 6 * 2 * Math.PI + .4;
        g.moveTo(c.x, c.y);
        for(let s = 1; s <= 4; s++){ const w = (this.rnd(n * 5 + s, 6) - .5) * .35, dd = len * s / 4;
          g.lineTo(c.x + Math.cos(a + w) * dd, c.y + Math.sin(a + w) * dd); }
      }
      g.stroke();
    }
    // 7) çekirdek: orb gidince kalır, küçülür, parazitle titrer, tek bir noktaya çöker
    if(t > 9 && t < 16.05){
      const s = this.coreScale(t), grey = smooth((t - 10) / 4);
      const v = t > 10.2 && !calm ? .35 * Math.max(0, ...this.BURSTS.map(([at, p]) => Math.max(0, 1 - Math.abs(t - at) / .5) * p)) : 0;
      const tone = `${Math.round(255 * (1 - .25 * grey))},${Math.round(255 * (.36 + .3 * grey))},${Math.round(255 * (.32 + .33 * grey))}`;
      const r = D * .15 * s * (1 + .5 * v) + 2 * u, flick = gl > .3 && this.rnd(f15, 37) < gl * .5 ? .55 : 1;
      const gr = g.createRadialGradient(c.x, c.y, 0, c.x, c.y, r * 2);
      gr.addColorStop(0, `rgba(255,255,255,${.95 * flick})`); gr.addColorStop(.16, `rgba(${tone},${.85 * flick})`);
      gr.addColorStop(.42, `rgba(${tone},${.3 * flick})`); gr.addColorStop(1, `rgba(${tone},0)`);
      g.fillStyle = gr; g.beginPath(); g.arc(c.x, c.y, r * 2, 0, 7); g.fill();
    }
    // 8) dijital kırıntılar: parçalarla birlikte savrulan pikseller
    if(t > 9.6 && t < 13.5){
      const grey = smooth((t - 9.6) / 2.5);
      for(let i = 0; i < (lite ? 14 : 30); i++){
        const fly = t - 9.6 - this.rnd(i, 7) * .8;
        if(fly <= 0) continue;
        const a = this.rnd(i, 8) * 2 * Math.PI, dd = D * .12 + (60 + 220 * this.rnd(i, 9)) * u * (1 - Math.exp(-fly * 1.2)) / 1.2;
        const x = c.x + Math.cos(a) * dd, y = c.y + Math.sin(a) * dd + 10 * u * fly * fly, s = (2 + 3 * this.rnd(i, 10)) * u;
        const fade = Math.max(0, 1 - fly / (1.4 + 1.4 * this.rnd(i, 11)));
        const flick = calm || this.rnd(Math.floor(t * 20) + i, 12) > .2 ? 1 : .3;
        g.fillStyle = `rgba(${Math.round(255 * (1 - .5 * grey))},${Math.round(255 * (.3 + .2 * grey))},${Math.round(255 * (.3 + .2 * grey))},${fade * flick})`;
        g.fillRect(x - s / 2, y - s / 2, s, s);
      }
    }
    // 9) çöküşten sonra tek bir nokta, sessizlik
    if(t > 15.8 && t < 16.95){
      g.fillStyle = `rgba(255,255,255,${1 - smooth((t - 16) / .9)})`; g.beginPath(); g.arc(c.x, c.y, 3 * u, 0, 7); g.fill();
    }
    // 10) şok dalgası
    if(t > 16.9 && t < 18.6){
      const e = smooth((t - 16.9) / 1.7), r = 10 + e * Math.max(W, H) * 1.1;
      g.beginPath(); g.arc(c.x, c.y, r, 0, 7);
      g.strokeStyle = `rgba(${col},${(1 - e) * .5})`; g.lineWidth = 30 * u * (1 - e) + 2; g.stroke();
      g.strokeStyle = `rgba(255,255,255,${(1 - e) * .9})`; g.lineWidth = 2; g.stroke();
    }
    // 11) kırmızı parazit: orbun çevresinde kayan yatay bantlar; güç azaldıkça seyrek
    if(gl > .02 && this.rnd(f15, 40) < .3 + .6 * gl){
      for(let b = 0; b < 1 + Math.floor((lite ? 3 : 5) * gl); b++){
        const s = f15 * 7 + b, kind = this.rnd(s, 45), y = c.y + (this.rnd(s, 41) - .5) * D * 1.5;
        const h = kind < .8 ? 1 + 6 * this.rnd(s, 42) * gl : 1, w = W * (kind < .8 ? .15 + .7 * this.rnd(s, 43) : .08 + .3 * this.rnd(s, 43));
        g.fillStyle = kind < .5 ? `rgba(255,59,59,${.2 + .45 * gl})` : kind < .8 ? "rgba(0,0,0,.9)" : `rgba(255,255,255,${.4 * gl})`;
        g.fillRect((W - w) * this.rnd(s, 44), y, w, h);
      }
      if(gl > .6 && this.rnd(f15, 46) < .25){ g.fillStyle = `rgba(255,59,59,${.07 * gl})`; g.fillRect(0, 0, W, H); }
    }
    // 12) beyaz parlama
    const flash = Math.max(0, 1 - Math.abs(t - 17) / .5) * (calm ? .25 : .9);
    if(flash > 0){ g.fillStyle = `rgba(255,255,255,${flash})`; g.fillRect(-20, -20, W + 40, H + 40); }
    g.restore();
    this.term(F, t, gl, sx, sy, calm);
    // sonda yazı: orbun yerinde
    const txt = $("fin-text");
    txt.style.top = c.y + "px";
    txt.style.opacity = t > 17.6 ? (smooth((t - 17.6) / .6) * (1 - smooth((t - 20.4) / .7))).toFixed(3) : "0";
    if(t > 17.6 && !d.said){ d.said = true; F.text(`${chipName("ultron")} · SİLİNDİ`, `${chipName(d.s)} · FEDA EDİLDİ`, `rgb(${col})`); }
  },
  // alttaki İSTASYON-7 terminali (3–16,6): SİLİNİYOR %…, bölmeli çubuk, satır satır silme kaydı; ULTRON saldırırken
  // kızarır, sarsılır ve bir satır direnir; en sonda SİLME TAMAMLANDI. Yalnızca değişen yazılar yeniden yazılır.
  term(F, t, gl, sx, sy, calm){
    const d = F.gd, box = $("fin-term"), pct = this.percent(t), resist = t > 6 && t < 9.4;
    const fr = Math.floor(t * 15), jolt = !calm && gl > .5 && this.rnd(fr, 50) < gl * .5 ? (this.rnd(fr, 51) - .5) * 10 * gl : 0;
    box.style.opacity = (smooth((t - 3) / .4) * (1 - smooth((t - 16.2) / .4))).toFixed(3);
    box.style.transform = `translate(calc(-50% + ${(sx + jolt).toFixed(1)}px),${((1 - smooth((t - 3) / .5)) * 24 + sy).toFixed(1)}px)`;
    box.classList.toggle("resist", resist);
    const set = (el, v) => { if(el.textContent !== v) el.textContent = v; };
    set($("ft-word"), t > 15.8 ? "SİLME TAMAMLANDI" : resist ? "DİRENÇ ALGILANDI" : "SİLİNİYOR");
    set($("ft-pct"), "%" + pct);
    const full = Math.round(pct / 100 * 28), blink = Math.floor(t * 12);
    d.cells.forEach((cell, i) => {
      const cls = i < full ? "on" : resist && i < 19 ? (!calm && (blink + i) % 2 ? "lost dim" : "lost") : "";
      if(cell.className !== cls) cell.className = cls;
    });
    this.ROWS.forEach(([at, done, fights], i) => {
      const row = d.rows[i], state = t > done ? "SİLİNDİ" : fights && t > 6 && t < 9.4 ? "DİRENİYOR" : "SİLİNİYOR";
      const label = `> ${d.name}/${this.FILES[i]}`, head = `${label} ${"·".repeat(Math.max(2, 26 - label.length))} `;
      const shown = t > at ? Math.floor((t - at) * 45) : 0;
      set(row.head, head.slice(0, shown));
      set(row.state, state.slice(0, Math.max(0, shown - head.length)));
      const cls = state === "SİLİNDİ" ? "done" : state === "DİRENİYOR" ? "resist" : "";
      if(row.state.className !== cls) row.state.className = cls;
    });
  },
  // terminalin satırları ve çubuğu (sahne başlarken bir kez)
  build(F){
    const bar = $("ft-bar"), log = $("ft-log");
    bar.replaceChildren(); log.replaceChildren();
    F.gd.cells = Array.from({length: 28}, () => bar.appendChild(el("i")));
    F.gd.rows = this.FILES.map(() => { const r = log.appendChild(el("div")); return {head: r.appendChild(el("span")), state: r.appendChild(el("em"))}; });
    F.gd.name = chipName("ultron").toLocaleLowerCase("tr").replace(/\s+/g, "-");
    const box = $("fin-term");
    box.style.setProperty("--rc", F.gd.col);
    box.className = "on";
  },
};

/* İNŞA: iyi sondan sonra yeni çipin planı (E.D.I.T.H, V5'te) */
$("t-build").addEventListener("click", () => {
  $("t-build").classList.remove("fresh");
  $("build-open").hidden = !Story.view.locked;
  $("build-undo").hidden = !(Story.view.locked && Story.view.dev);
  openOverlay("ov-build");
});
for(const b of document.querySelectorAll("[data-open-world]")) b.addEventListener("click", () => { closeOverlays(); send("open_world"); });
for(const b of document.querySelectorAll("[data-final-undo]")) b.addEventListener("click", () => { closeOverlays(); send("final_undo"); });
// ★ › ANAHTAR › ANAHTARI KULLAN: 🔑 sayfası açılır (sağ alttaki 🔑 de kalır).
$("ach-keygo").addEventListener("click", () => KeyPanel.open());
// ★ › TEKRAR OYNA: ilk basış sorar ("Hikâye baştan başlasın mı?"), 4 sn içinde ikincisi başlatır (app.py › _replay).
$("ach-replay").addEventListener("click", () => {
  const b = $("ach-replay"), [title, note] = [b.querySelector("b"), b.querySelector("small")];
  clearTimeout(b._confirm);
  const back = () => { b.classList.remove("confirm"); title.textContent = "TEKRAR OYNA";
    note.textContent = "Diğer sonu bulmak için hikâye baştan başlar. Bulduğun son kalır."; };
  if(!b.classList.contains("confirm")){
    b.classList.add("confirm"); title.textContent = "HİKÂYE BAŞTAN BAŞLASIN MI?"; note.textContent = "Başlatmak için yeniden bas.";
    SFX.play("warn");
    b._confirm = setTimeout(back, 4000); return;
  }
  back();
  closeOverlays(); send("story_replay");
});
/* [/hikaye] */

/* [telefon] */
/* ---------------- telefon (jarvis/phone.py) ----------------
   Ayarlar › Telefon: bağla/durdur, QR kod (videoda görünmesin diye bulanık; dokununca açılır, pencere
   kapanınca yine bulanıklaşır), adres kopyalama, yeni kod. Üst çubukta bağlıyken TELEFON göstergesi. */
let PHONE = {state: "off"};
const PHONE_WORDS = {off: "KAPALI", starting: "AÇILIYOR", ready: "HAZIR · TELEFON BEKLENİYOR", connected: "BAĞLI", error: "SORUN"};
function renderPhone(st){
  PHONE = st || PHONE;
  const s = PHONE.state || "off";
  const app = s === "ready" && PHONE.app ? PHONE.app : "";     // iPhone uygulaması (tarayıcı sayfası değil)
  $("pstate").dataset.state = app ? "connected" : s;
  $("pstate-text").textContent = s === "connected" ? `BAĞLI · ${PHONE.device || "TELEFON"}`.toLocaleUpperCase("tr")
    : app ? `BAĞLI · ${app}`.toLocaleUpperCase("tr") : PHONE_WORDS[s] || s;
  const [hereOf, hereIn] = OS === "win" ? ["bu bilgisayarın", "bu bilgisayarda"] : ["bu Mac'in", "bu Mac'te"];
  $("pnote").textContent = s === "connected"
    ? (PHONE.active ? (PHONE.mic ? `Ses telefonda, telefonun mikrofonu açık: ${hereOf} mikrofonu susuyor.` : "Ses telefonda.")
                    : "Telefon bağlı; sesi açmak için telefonda BAŞLAT'a dokunulmalı.")
    : app ? `iPhone uygulaması bağlı: konuşma telefonda, istediği komutlar ${hereIn} çalışır.`
    : PHONE.note || (s === "off" ? (OS === "win" ? "Başlatınca bir QR kod çıkar; iPhone uygulamasıyla okut."
                                                 : "Başlatınca bir QR kod çıkar; iPhone uygulamasıyla ya da telefonun kamerasıyla okut.") : "");
  $("pnote").classList.toggle("bad", !!PHONE.lan_warn && s === "ready" && !app);
  const qr = $("pqr");
  qr.classList.toggle("has", !!PHONE.qr && s !== "off");
  if(PHONE.qr) $("pqr-img").src = PHONE.qr;
  $("purl").hidden = !PHONE.url;
  $("purl-host").textContent = PHONE.host || "";
  $("phone-go").textContent = s === "off" || s === "error" ? "TELEFONU BAĞLA" : "DURDUR";
  $("phone-go").disabled = s === "starting";
  $("phone-lan-note").hidden = PHONE.tunnel_ok !== false;
  $("set-phone-auto").setAttribute("aria-checked", String(!!PHONE.autostart));
  $("set-phone-shell").setAttribute("aria-checked", String(!!PHONE.shell));
  $("set-phone-relay").setAttribute("aria-checked", String(PHONE.relay !== false));
  const t = $("t-phone");
  t.hidden = s === "off";
  t.dataset.state = app ? "connected" : s;
  $("t-phone-state").textContent = app ? "iPHONE" : s === "connected" ? (PHONE.active ? "SES TELEFONDA" : "BAĞLI")
    : s === "starting" ? "AÇILIYOR" : s === "error" ? "SORUN" : "HAZIR";
}
$("phone-go").addEventListener("click", () => {
  const s = PHONE.state || "off";
  if(s === "off" || s === "error"){ send("phone", {action: "start"}); renderPhone({...PHONE, state: "starting", note: "Sunucu açılıyor…"}); }
  else send("phone", {action: "stop"});
});
$("phone-rotate").addEventListener("click", () => {
  const b = $("phone-rotate");
  if(!b.classList.contains("confirm")){
    b.classList.add("confirm"); b.textContent = "EMİN MİSİN?";
    setTimeout(() => { b.classList.remove("confirm"); b.textContent = "YENİ KOD"; }, 3000); return;
  }
  b.classList.remove("confirm"); b.textContent = "YENİ KOD";
  $("pqr").classList.remove("shown");
  send("phone", {action: "rotate"});
});
$("pqr-show").addEventListener("click", () => $("pqr").classList.add("shown"));
$("pqr-img").addEventListener("click", () => $("pqr").classList.remove("shown"));
$("purl-copy").addEventListener("click", () => {
  if(!PHONE.url) return;
  send("copy", {text: PHONE.url});
  $("purl-copy").textContent = "KOPYALANDI";
  setTimeout(() => { $("purl-copy").textContent = "KOPYALA"; }, 1600);
});
$("set-phone-auto").addEventListener("click", () => send("phone", {action: "autostart", on: !PHONE.autostart}));
$("set-phone-shell").addEventListener("click", () => send("phone", {action: "shell", on: !PHONE.shell}));
$("set-phone-relay").addEventListener("click", () => send("phone", {action: "relay", on: PHONE.relay === false}));
$("t-phone").addEventListener("click", () => { fillSettings(); showTab("telefon"); openOverlay("ov-settings"); });
for(const b of document.querySelectorAll('.stab[data-tab="telefon"]')) b.addEventListener("click", () => send("phone", {action: "status"}));
/* [/telefon] */

/* [hikaye] */
/* Gece yarısı (Ankara saatiyle 00:00) yedek kendini yeniler: uygulama o an açıksa ekran bir an maviye
   döner, JARVIS'in önceden seslendirilmiş sesi "Senkron tamam." der (hangi model takılı olursa olsun). */
// Pencere gizliyken gelen sızıntı (Leak.show): pencere görününce, ses motoru açıldıktan sonra
document.addEventListener("visibilitychange", () => {
  if(document.visibilityState !== "visible" || !Leak.pending) return;
  const k = Leak.pending; Leak.pending = null;
  setTimeout(() => {
    // bu arada uyuduysa, çip değiştiyse ya da sahne başladıysa gösterilmez (Python da o durumda sızıntı başlatmaz)
    if(SLEEP || body.dataset.persona !== "ultron" || CHAINS_ON || body.classList.contains("scene")
       || body.classList.contains("finale")) return;
    Leak.show(k);
  }, 400);
});

const Sync = {
  day: null, at: 0,
  tick(){
    const c = Clues.get();
    if(!c){ this.day = null; return; }
    const now = Date.now(), day = new Intl.DateTimeFormat("en-CA", {timeZone:c.zone}).format(new Date(now));
    // Yalnızca uygulama açıkken geçilen gece yarısı (uyku/kapalıyken kaçırılan sayılmaz).
    if(this.day && day !== this.day && now - this.at < 5000) this.play();
    this.day = day; this.at = now;
  },
  // uyanıştaki mavi sınır iki saniyeliğine ekranın kenarlarında belirir (Yedek kendini yeniler), JARVIS konuşur
  play(){
    // pencere gizliyken olmaz (görünmeyen senkron sayılmaz; sesi de saatler sonra çalıyordu)
    if(body.classList.contains("scene") || CHAINS_ON || Barrier.raf || document.visibilityState === "hidden") return;
    const s = $("sync");
    s.classList.remove("on"); void s.offsetWidth; s.classList.add("on");
    Barrier.start(true);
    setTimeout(() => Voice.play("sfx/voices/jarvis_sync_1.wav"), 750);
    setTimeout(() => s.classList.remove("on"), 2800);
  },
};
/* [/hikaye] */

/* =======================================================================
   İLK AÇILIŞ (jarvis/app.py › _onboard_done): açılış, tanışma, Gemini anahtarı, izinler; sonra
   JARVIS takılı ana ekran. Asistan bu bitene kadar bağlanmaz. Sözler önceden kaydedildi
   (sfx/voices/ob_*.wav); Mac'te çiplerin adı sabit, isim sorulmaz. macOS bir izinden sonra
   uygulamayı yeniden açtırırsa ekran kaldığı adımdan sürer (settings › onboard_step).
   ======================================================================= */
const PERMS = {
  microphone: {title:"MİKROFON", why:"Seninle sesli konuşabilmek için. Olmadan da yazarak konuşabilirsin.", tag:"ÖNERİLEN",
               none:"Mikrofon bulunamadı. Takınca burada görünür; o zamana kadar yazarak konuşabilirsin."},
  camera: {title:"KAMERA", why:"İstediğinde kameradan gördüğünü anlatabilmek için."},
  files: {title:"DOSYALAR", why:"Masaüstü, Belgeler ve İndirilenler'deki dosyaları bulup açabilmek için. macOS her klasörü ayrı sorar."},
  contacts: {title:"REHBER", why:"WhatsApp'tan mesaj göndereceğin kişinin numarasını bulabilmek için."},
  calendar: {title:"TAKVİM", why:"Takvimindeki etkinlikleri söylemek, yenisini eklemek ve istediğinde silmek için."},
  reminders: {title:"ANIMSATICILAR", why:"Anımsatıcılarını okumak, yenisini eklemek, istediğinde silmek ya da tamamlamak için."},
  screen: {title:"EKRAN KAYDI", why:"“Ekranımda ne var?” dediğinde ekrana bakabilmek için."},
  accessibility: {title:"ERİŞİLEBİLİRLİK", why:"Uygulamalara senin yerine tuş ve kısayol gönderebilmek için."},
  automation: {title:"SPOTIFY · MÜZİK", why:"Şarkı çalabilmek için. İlk şarkıyı istediğinde macOS bir kez sorar."},
};
let PERM_STATE = {};
const PERM_PENDING = new Set();            // macOS'un sorusu açık: satır yenilense de "bekleniyor" kalsın
function permRows(host, st){
  host.replaceChildren();
  // Windows'ta yalnızca mikrofon ve kamera (öbürleri için Windows izin istemez); Mac'te hepsi.
  for(const kind of PERM_ROWS || Object.keys(PERMS)){
    const p = PERMS[kind];
    if(!p) continue;
    const s = st[kind] || "ask";          // none: izin açık ama mikrofon takılı değil (Windows)
    const row = el("div", "prow"), text = el("div"), head = el("b", null, p.title);
    const check = kind === "microphone" && s === "granted" && host.id === "ob-perms" ? MicCheck.view() : null;
    row.dataset.state = check && check.bad ? "denied" : s;
    if(p.tag && s !== "granted" && s !== "none") head.appendChild(el("em", null, p.tag));
    text.append(head, el("small", null, (check && check.text) || (s === "none" && p.none) || p.why));
    let right;
    if(check && check.right) right = check.right;
    else if(s === "granted") right = el("span", "pok", "✓ VERİLDİ");
    else if(PERM_PENDING.has(kind)){ right = el("button", "btn ghost", "BEKLENİYOR…"); right.disabled = true; }
    else{
      right = el("button", s === "ask" ? "btn" : "btn ghost",
                 s === "ask" ? "İZİN VER" : s === "first_use" ? "AYARLAR ↗" : s === "none" ? "SES AYARLARI ↗" : "AYARLARI AÇ ↗");
      right.addEventListener("click", () => askPermission(kind));
    }
    row.append(text, right);
    host.appendChild(row);
  }
}
function askPermission(kind){
  PERM_PENDING.add(kind);
  showPerms(PERM_STATE);
  send("permission", {kind});
}
function showPerms(st, done){
  if(done) PERM_PENDING.delete(done);
  PERM_STATE = st || {};
  MicCheck.maybe();
  if(Onboard.on && Onboard.step === "perms") permRows($("ob-perms"), PERM_STATE);
  if($("ov-settings").classList.contains("on")) permRows($("set-perms"), PERM_STATE);
  if(Onboard.afterMic && PERM_STATE.microphone === "granted"){
    Onboard.afterMic = false;
    Onboard.finish();
  }
  // Mac: soru cevaplandı (reddedildiyse bekleme biter). Windows'ta soru yok: kullanıcı Ayarlar'da
  // anahtarı açınca yoklama "granted" görür ve ekran kendiliğinden geçer.
  else if(Onboard.afterMic && OS !== "win" && PERM_STATE.microphone && PERM_STATE.microphone !== "ask")
    Onboard.afterMic = false;
}
// İzin Sistem Ayarları'nda verilince satır kendiliğinden güncellensin.
function permsVisible(){
  const settingsOpen = $("ov-settings").classList.contains("on") &&
    document.querySelector('.pane[data-pane="izinler"]').classList.contains("on");
  return (Onboard.on && Onboard.step === "perms") || settingsOpen;
}
setInterval(() => { if(!document.hidden && permsVisible()) send("permissions"); }, 2500);
// Windows: Ayarlar'dan JARVIS'e dönülünce beklemeden yenilensin.
window.addEventListener("focus", () => {
  if(OS === "win" && permsVisible()){ send("permissions"); if(Onboard.on) MicCheck.retry(); }
});

/* İlk açılış › İZİNLER (Windows): Windows izin sormaz, "VERİLDİ" yalnızca gizlilik anahtarlarını okur; antivirüsün
   mikrofon koruması, başka uygulama ya da sessize alınmış/yanlış aygıt yine susturabilir (9 Ekim takipçi raporu).
   Mikrofon 2,5 sn gerçekten açılıp denenir (app._mic_test, "micCheck"); satırda gerçek sonuç. Karşılama sözü bitince
   başlar: "Stereo Karışımı" gibi çıkışı dinleyen bir aygıt JARVIS'in kendi sesini duyup "çalışıyor" demesin. */
const MicCheck = {
  state: "", r: null, timer: 0,           // "" (denenmedi) | run | ok | quiet | zero | blocked | busy | none | unreachable
  maybe(){
    if(OS !== "win" || !Onboard.on || Onboard.step !== "perms") return;
    if(PERM_STATE.microphone !== "granted"){ if(this.state !== "run") this.state = ""; return; }
    if(!this.state && Onboard.permsSpoken) this.run();
  },
  run(){
    if(this.state === "run") return;
    this.state = "run"; this.r = null;
    send("mic_check");
    clearTimeout(this.timer);               // Python cevap vermezse (aygıt açılırken takıldı) satır kilitli kalmasın
    this.timer = setTimeout(() => { if(this.state === "run") this.result({ok:false, kind:"unreachable"}); }, 15000);
    this.paint();
  },
  result(r){
    clearTimeout(this.timer);
    const p = r.peak || 0;
    this.r = r;
    this.state = !r.ok ? (r.kind || "unreachable") : !r.chunks || p === 0 ? "zero" : p < .003 ? "quiet" : "ok";
    this.paint();
  },
  paint(){ if(Onboard.on && Onboard.step === "perms") permRows($("ob-perms"), PERM_STATE); },
  retry(){ if(this.state && this.state !== "run" && this.state !== "ok") this.run(); },
  // satırın açıklaması ve sağı; null: denenmedi (eski "VERİLDİ")
  view(){
    if(!this.state || OS !== "win") return null;
    const dev = this.r && this.r.device ? ` (“${this.r.device}”)` : "";
    if(this.state === "run"){
      const b = el("button", "btn ghost", "DENENİYOR…");
      b.disabled = true;
      return {text: "İzin açık; mikrofon deneniyor… Bir şey söyleyebilirsin.", right: b};
    }
    if(this.state === "ok") return {text: `İzin açık ve ses geliyor${dev}.`, right: el("span", "pok", "✓ ÇALIŞIYOR")};
    const text = {
      blocked: "İzin anahtarları açık ama mikrofon açılamıyor: büyük ihtimalle antivirüsün mikrofon koruması (Kaspersky, " +
               "ESET, Bitdefender, Norton…) JARVIS'i engelliyor. Orada JARVIS'e izin ver, sonra YENİDEN DENE.",
      busy: "Mikrofonu şu an başka bir uygulama (Discord, Zoom, Teams, OBS…) kullanıyor. O uygulamayı kapatıp YENİDEN DENE'ye bas.",
      unreachable: "Mikrofon açılamadı. Antivirüsün mikrofon korumasına ve Windows Ses ayarlarında mikrofonun etkin olduğuna " +
                   "bak, sonra YENİDEN DENE.",
      zero: `İzin açık ama mikrofondan hiç ses gelmiyor${dev}. Antivirüsün mikrofon koruması engelliyor, mikrofon Windows'ta ` +
            "sessize alınmış ya da yanlış aygıt seçili olabilir.",
      none: "Etkin bir mikrofon bulunamadı. Mikrofonu takıp YENİDEN DENE'ye bas; o zamana kadar yazarak konuşabilirsin.",
      quiet: `Ses çok zayıf geliyor${dev}: mikrofon kısık ya da sessize alınmış olabilir. Bir şey söyleyip YENİDEN DENE'ye bas.`,
    }[this.state] || "Mikrofon denenemedi; YENİDEN DENE'ye bas.";
    const b = el("button", "btn ghost", "YENİDEN DENE");
    b.addEventListener("click", () => this.run());
    return {text, right: b, bad: true};
  },
};

const OB_MODULES = ["ÇEKİRDEK", "SES MODÜLÜ", "DİL MODELİ", "BAĞLANTI"];
const Onboard = {
  on: false, step: "", token: 0, timers: [], typing: 0, keyOnly: false, said: 0, hello: false, text: "",
  afterMic: false, held: null, checkTimer: 0, changing: false, permsSpoken: false,
  later(ms, fn){ const mine = this.token; this.timers.push(setTimeout(() => { if(mine === this.token) fn(); }, ms)); },
  open(from, keyOnly){
    for(const t of this.timers) clearTimeout(t);
    this.timers = []; this.token++;
    this.on = true; this.keyOnly = !!keyOnly; this.changing = false; this.afterMic = false; this.hello = false;
    closeOverlays();
    body.classList.add("onboard");
    $("onboard").classList.add("on");
    $("ob-alert").classList.remove("on");
    $("ob-sub").textContent = "";
    this.talking(false);
    SFX.refresh();
    if(from === "boot" || !from){ this.boot(); return; }
    body.dataset.ob = "orb";                    // yeniden açıldı: kaldığı adıma kısa bir girişle dön
    this.show("");
    this.later(500, () => SFX.play("boot"));
    this.later(1500, () => this[from] ? this[from]() : this.key());
  },
  close(){
    for(const t of this.timers) clearTimeout(t);
    this.timers = []; this.token++;
    clearInterval(this.typing); Voice.stop();
    KeyHelp.close();
    this.on = false; this.step = ""; this.said++; this.hello = false;
    this.afterMic = false;                  // Windows'ta izin sonradan verilince açılış ikinci kez bitmesin
    $("onboard").classList.remove("on");
    body.classList.remove("onboard");
    delete body.dataset.ob;
    // Yeniden oynatılırken asistan uyutulmuştu; o "uyku" ekrana yansımasın, uyanınca durum zaten gelir.
    const held = this.held;
    this.held = null;
    if(held && held[0] !== "asleep") window.jarvis.state(held[0], held[1]);
  },
  show(step){
    this.step = step;
    for(const s of document.querySelectorAll(".ob-step")) s.classList.toggle("on", s.dataset.step === step);
    if(step) body.dataset.ob = "step";
    $("ob-next").hidden = !step;
    if(step) send("onboard_step", {step});
  },
  /* Söz: kayıtlı ses çalar, altyazı sesin süresine yayılarak yazılır. */
  say(voice, text, then){
    const mine = ++this.said, url = `sfx/voices/${voice}.wav`, sub = $("ob-sub");
    clearInterval(this.typing);
    sub.textContent = "";
    sub.classList.toggle("long", text.length > 150);      // "neden anahtar?": küçük yazıyla iki satır, kutuya taşmaz
    this.text = text;
    this.talking(true);
    SFX.load(url).then(buf => {
      if(mine !== this.said || !this.on) return;
      const chars = [...text], span = Math.max(1.2, (buf ? buf.duration : chars.length * .065) * .88) * 1000;
      let i = 0;
      this.typing = setInterval(() => {
        sub.textContent = chars.slice(0, ++i).join("");
        if(i >= chars.length) clearInterval(this.typing);
      }, span / chars.length);
      Voice.play(url, () => {
        if(mine !== this.said || !this.on) return;
        clearInterval(this.typing);
        sub.textContent = text;
        this.talking(false);
        if(then) then();
      });
    });
  },
  /* ANAHTAR ALAMADIM açılınca: söz susar, yazısı tamamlanır (sayfanın ▶ DİNLE'si kendi sesini çalar). */
  quiet(){
    if(!this.on) return;
    this.said++;
    clearInterval(this.typing); Voice.stop();
    if(this.text) $("ob-sub").textContent = this.text;
    this.talking(false);
  },
  talking(on){
    STATE = on ? "speaking" : "listening";
    body.dataset.state = STATE;
    paint();
  },

  // 1. açılış: karanlıkta bir nokta, modüller tek tek hazır, sonra orb
  boot(){
    this.show("");
    body.dataset.ob = "boot";
    const box = $("ob-boot"), list = $("ob-mods");
    box.classList.remove("gone"); box.classList.add("on");
    list.replaceChildren();
    OB_MODULES.forEach((m, i) => {
      const li = el("li");
      li.append(el("span", null, m), el("b", null, "…"));
      list.appendChild(li);
      this.later(900 + i * 600, () => li.classList.add("on"));
      this.later(1350 + i * 600, () => { li.classList.add("ok"); li.querySelector("b").textContent = "✓"; SFX.play("s_blip"); });
    });
    this.later(3400, () => { box.classList.add("gone"); body.dataset.ob = "orb"; SFX.play("boot"); });
    this.later(4000, () => box.classList.remove("on"));
    this.later(5000, () => this.intro());
  },
  // 2. tanışma (Mac'te ad sabit: isim sorulmaz). Sözün sonu beklenmez (telefondaki gibi): "Merhaba."dan hemen sonra
  // DEVAM ET belirir; basılmazsa söz bitince kendiliğinden geçilir.
  intro(){
    body.dataset.ob = "orb";
    this.hello = true;
    this.say("ob_mac_intro", "Merhaba. Ben sana yardımcı olmak için geliştirilmiş bir yapay zekâ asistanıyım. " +
             "Birkaç adımda kurulumu tamamlayalım.", () => this.later(500, () => this.key()));
    this.later(1200, () => {                // "Merhaba." 0,55 sn'de biter, ikinci cümle 1,05'te başlar
      if(!this.hello) return;               // ses yüklenemezse söz hemen biter: anahtar adımının düğmesine dokunma
      const next = $("ob-next");
      next.textContent = "DEVAM ET"; next.disabled = false; next.hidden = false;
      next.classList.remove("dim"); next.title = "";     // anahtar adımının soluk DEVAM'ı burada değil
    });
  },
  // DEVAM ET tanışmada: söz susar, anahtar adımına geçilir; sözün sonundaki kendiliğinden geçiş iptal olur.
  skipHello(){
    this.token++; this.said++;
    clearInterval(this.typing); Voice.stop();
    this.key();
  },
  // 3. Gemini anahtarı
  key(){
    this.hello = false;
    this.show("key");
    this.keyView();
    this.say("ob_key", "Seninle konuşabilmem için beni Google'ın Gemini sunucusuna bağlaman gerekiyor. " +
             "Bunun için ücretsiz bir anahtar yeterli.");
  },
  keyView(fresh){
    const saved = !!SETTINGS.has_key && !this.changing;
    $("ob-saved").hidden = !saved;
    $("ob-saved").querySelector("b").textContent = fresh ? "✓ BAĞLANTI KURULDU" : "✓ ANAHTARIN KAYITLI";
    $("ob-keybox").hidden = saved;
    // Anahtarsızken soluk ama basılır: asistan anahtarın neden gerektiğini anlatır (next › why)
    $("ob-next").disabled = false;
    $("ob-next").classList.toggle("dim", !SETTINGS.has_key);
    $("ob-next").title = SETTINGS.has_key ? "" : "Anahtar girilmedi. Neden gerektiğini dinlemek için bas.";
    if(SETTINGS.has_key) $("ob-get").classList.remove("glow");
    $("ob-next").textContent = this.keyOnly ? "BAŞLAT" : "DEVAM";
    if(!saved) setTimeout(() => $("ob-key").focus(), 400);
  },
  checkKey(now){
    clearTimeout(this.checkTimer);
    const key = $("ob-key").value.trim();
    if(key.length < 30){
      if(now && key){ note("ob-key-note", "Bu anahtar çok kısa görünüyor; tamamını kopyaladığından emin ol.", "bad");
        $("ob-khelp").classList.add("loud"); }
      return;
    }
    this.checkTimer = setTimeout(() => {
      note("ob-key-note", "Anahtar kontrol ediliyor…", "");
      $("ob-key").disabled = true;
      send("api_key", {key, origin:"onboard"});
    }, now ? 0 : 600);
  },
  keyResult(ok, message){
    $("ob-key").disabled = false;
    $("ob-khelp").classList.toggle("loud", !ok);          // anahtar geçersiz: ANAHTAR ALAMADIM belirginleşir
    if(!ok){ note("ob-key-note", message, "bad"); SFX.play("warn"); return; }
    $("ob-key").value = "";
    this.changing = false;
    note("ob-key-note", "", "");
    // bağlandı: anahtarsız DEVAM'ın "neden anahtar?"ı anlatmaya devam etmesin (yardım sayfasının ▶ DİNLE'si kendisi susar)
    if(Voice.url === WHY_URL && !KeyHelp.on) this.quiet();
    SFX.play("s_match");
    this.keyView(true);
  },
  // 4. izinler (sonra ana ekran)
  perms(){
    this.show("perms");
    $("ob-next").disabled = false;
    $("ob-next").classList.remove("dim");
    $("ob-next").title = "";
    $("ob-next").textContent = "BAŞLAT";
    this.permsSpoken = false;
    if(MicCheck.state !== "run") MicCheck.state = "";
    permRows($("ob-perms"), PERM_STATE);
    send("permissions");
    // Windows: söz bitince mikrofon gerçekten denenir (MicCheck)
    this.say("ob_perms", "Şimdi birkaç izin. Hangisini vereceğine sen karar ver.", () => {
      this.permsSpoken = true;
      MicCheck.maybe();
    });
  },
  next(){
    if($("ob-next").disabled) return;
    // Anahtarsız: kontrol sürerken bir şey yapmaz; kutuda tam boy bir anahtar varsa (yapıştırılıp henüz denenmemiş ya
    // da az önce geçersiz çıkmış) onu dener; yoksa ya da eksikse "neden anahtar?" (telefonda: ready ? doğrula : askWhy)
    if(this.step === "key" && !SETTINGS.has_key){
      if($("ob-key").disabled) return;
      if($("ob-key").value.trim().length >= 30) this.checkKey(true); else this.why();
      return;
    }
    SFX.play("insert");
    if(this.hello) this.skipHello();
    else if(this.step === "key"){ if(this.keyOnly) this.finish(); else this.perms(); }
    else if(this.step === "perms"){
      // "none" (Windows: mikrofon takılı değil): izin sorunu yok, uyarısız başlar.
      const m = PERM_STATE.microphone;
      if(m !== "granted" && m !== "none"){ $("ob-alert").classList.add("on"); SFX.play("warn"); return; }
      this.finish();
    }
  },
  /* Anahtarsız DEVAM (telefonda anahtarsız DOĞRULA): asistan anahtarın neden gerektiğini anlatır, ANAHTARI AL
     parlar. Anlatırken yeniden basılırsa baştan başlamaz. Açılış ekranında asistan bağlı değil: mikrofon tutulmaz. */
  why(){
    $("ob-key").blur();
    $("ob-get").classList.add("glow");
    if(Voice.url === WHY_URL) return;
    this.say(WHY_VOICE, WHY_TEXT);
  },
  finish(){
    const persona = THEME ? THEME.key : "jarvis";
    const m = PERM_STATE.microphone;
    const mic = this.keyOnly ? SETTINGS.mic_enabled !== false : (m === "granted" || m === "none");
    this.close();
    setMic(mic, true);
    // izin yokken YAZILI DEVAM ET: izin sonradan verilince mikrofon kendiliğinden açılır (app._onboard_done)
    send("onboard_done", {persona, mic, mic_reason: !mic && !this.keyOnly && m === "denied" ? "permission" : ""});
  },
};
const AI_STUDIO = "https://aistudio.google.com/apikey";
$("ob-get").addEventListener("click", () => { $("ob-get").classList.remove("glow"); send("open", {url: AI_STUDIO}); });
// Anahtarın bilgisayarda nasıl alındığını gösteren video (Alp, 14 Ekim; telefonunki ayrı); ilk açılışta, Ayarlar › Genel'de
// ve ANAHTAR ALAMADIM'da
const KEY_VIDEO = "https://youtu.be/VZl5uBT4a60";
for(const id of ["ob-video", "set-key-video", "kh-video"]) $(id).addEventListener("click", () => send("open", {url: KEY_VIDEO}));
$("ob-key").addEventListener("input", () => {
  note("ob-key-note", "", "");
  $("ob-khelp").classList.remove("loud");
  if($("ob-key").value) $("ob-get").classList.remove("glow");
  Onboard.checkKey(false);
});
$("ob-key").addEventListener("keydown", e => { if(e.key === "Enter") Onboard.checkKey(true); });
$("ob-change").addEventListener("click", () => { Onboard.changing = true; Onboard.keyView(); });
$("ob-next").addEventListener("click", () => Onboard.next());
$("ob-alert-allow").addEventListener("click", () => {
  $("ob-alert").classList.remove("on");
  Onboard.afterMic = true;                  // izin verilirse çiplere kendiliğinden geçilir
  askPermission("microphone");
});
$("ob-alert-text").addEventListener("click", () => { $("ob-alert").classList.remove("on"); Onboard.finish(); });

/* ---------------- ANAHTAR ALAMADIM (telefonun KeyHelpSheet'i, 14 Ekim) ----------------
   Anahtarı alamayan vazgeçmesin: sık sorunlar ve çözümleri; olmazsa video, AI Studio ya da destek adresine e-posta
   (about.py › key_mail; e-posta uygulaması yoksa adres panoya kopyalanır). İlk açılışın anahtar adımında ve Ayarlar ›
   Genel'de; Ayarların üstünde açılır, kapanınca (✕, Esc, boşluğa tıklama) altındaki sayfa yerinde kalır.

   "Neden anahtar?" sözü (kayıtlı, yazısı kayıtla birebir aynı; scripts/make_phone_voices.py): ilk açılışta
   anahtarsız DEVAM, Ayarlar'da boş KAYDET ve buradaki ▶ DİNLE. Asistan açıkken söz boyunca mikrofon modele gitmez
   (Voice › voice_hold, bütün kayıtlı sözlerde): sözü duyup cevaplamasın. */
const WHY_VOICE = "ob_mac_why", WHY_URL = `sfx/voices/${WHY_VOICE}.wav`;
const WHY_TEXT = "Düşünebilmem için bir beyne ihtiyacım var. O beyni Google'ın Gemini'si sağlıyor; anahtar da beni " +
                 "ona bağlıyor. Ücretsiz, kart gerekmiyor ve anahtar yalnızca bu bilgisayarda kalıyor.";
const Why = {
  play(onEnd){ Voice.play(WHY_URL, onEnd); },
  stop(){ if(Voice.url === WHY_URL) Voice.stop(); },
};
const KeyHelp = {
  on: false, listening: false, run: 0, copyTimer: 0,
  open(){
    Onboard.quiet();
    for(const r of document.querySelectorAll(".kh-row")) this.fold(r, false);
    this.copied(false);
    $("keyhelp").classList.add("on");
    $("keyhelp").setAttribute("aria-hidden", "false");
    this.on = true;
    setTimeout(() => $("kh-close").focus(), 50);
  },
  close(){
    if(!this.on) return;
    this.on = false;
    this.hush();                                      // sayfa kapanınca söz susar
    $("keyhelp").classList.remove("on");
    $("keyhelp").setAttribute("aria-hidden", "true");
  },
  fold(row, open){
    row.classList.toggle("open", open);
    row.querySelector(".kh-q").setAttribute("aria-expanded", String(open));
    if(!open && "why" in row.dataset) this.hush();     // kapanan satırın sözü de susar
  },
  // ▶ DİNLE: "Neden anahtar?" sözü; DURDUR'a basınca, satır ya da sayfa kapanınca susar
  listen(){
    if(this.listening){ this.hush(); return; }
    Onboard.quiet();
    const mine = ++this.run;
    this.listening = true;
    $("kh-listen").textContent = "■ DURDUR";
    Why.play(() => { if(mine === this.run) this.idle(); });
  },
  hush(){
    if(this.listening){ this.run++; Why.stop(); }
    this.idle();
  },
  idle(){ this.listening = false; $("kh-listen").textContent = "▶ DİNLE"; },
  mail(){ if(ABOUT.key_mail) send("open", {url: ABOUT.key_mail}); },
  copy(){ if(ABOUT.mail) send("copy", {text: ABOUT.mail}); this.copied(true); },
  // Adres panoda: KOPYALA ✓ olur; e-posta uygulaması yoksa (keyMail) BANA YAZ de söyler. 2,5 sn sonra eski hâli.
  copied(on, noMail){
    clearTimeout(this.copyTimer);
    $("kh-copy").textContent = on ? "KOPYALANDI ✓" : "KOPYALA";
    $("kh-write").textContent = on && noMail ? "ADRES KOPYALANDI ✓" : "BANA YAZ";
    if(on) this.copyTimer = setTimeout(() => this.copied(false), 2500);
  },
};
$("kh-why").textContent = WHY_TEXT;
for(const id of ["ob-khelp", "set-khelp"]) $(id).addEventListener("click", () => KeyHelp.open());
for(const r of document.querySelectorAll(".kh-row"))
  r.querySelector(".kh-q").addEventListener("click", () => KeyHelp.fold(r, !r.classList.contains("open")));
for(const b of document.querySelectorAll("#keyhelp [data-studio]")) b.addEventListener("click", () => send("open", {url: AI_STUDIO}));
$("kh-listen").addEventListener("click", () => KeyHelp.listen());
$("kh-close").addEventListener("click", () => KeyHelp.close());
$("keyhelp").addEventListener("click", e => { if(e.target === $("keyhelp")) KeyHelp.close(); });
$("kh-addr").addEventListener("click", () => KeyHelp.mail());
$("kh-write").addEventListener("click", () => KeyHelp.mail());
$("kh-copy").addEventListener("click", () => KeyHelp.copy());

/* ---------------- katmanlar ---------------- */
// ANAHTAR ALAMADIM (#keyhelp) .overlay değil ve onların üstünde: başka bir sayfa açılırken (sesle yapan kartı, harita, 🔑…)
// kapanır, altında gizli kalmasın; Ayarlar'ın "neden anahtar?" sözü de susar (closeOverlays gibi).
function openOverlay(id){
  KeyHelp.close();
  if(!Onboard.on) Why.stop();
  for(const o of document.querySelectorAll(".overlay")) o.classList.remove("on");
  $(id).classList.add("on"); pageChanged(); }
function closeOverlays(){
  disarm(); closeDetail();
  SFX.stopPreview();
  KeyHelp.close();
  if(!Onboard.on) Why.stop();             // Ayarlar kapanınca boş KAYDET'in sözü de susar
  $("pqr").classList.remove("shown");  // [-telefon]
  if(Final.side) Final.no();  // [-hikaye]
  for(const o of document.querySelectorAll(".overlay")) o.classList.remove("on");
  pageChanged();
}
// Açık sayfa Python'a bildirilir (app.py › _page): model çip ekranını (open_chip_picker) yarım kalacak bir sayfanın
// üstüne açmaz, nedenini söyler. Tek kaynak bu: sayfa nasıl açılıp kapanırsa kapansın (✕, Esc, dışına tıklama, başka bir
// pencere) aşağıdaki gözcü sınıfından anlar; openOverlay/closeOverlays de hemen (eşzamanlı) çağırır.
function pageChanged(){
  const o = document.querySelector(".overlay.on"), id = o ? o.id : "";
  if(id !== PAGE){ PAGE = id; send("page", {id}); }
  PageWatch.sync();  // [-hikaye]
}
{
  const watch = new MutationObserver(() => pageChanged());
  for(const o of document.querySelectorAll(".overlay")) watch.observe(o, {attributes: true, attributeFilter: ["class"]});
}
// Model AI MODELLERİ'ni açtı (open_chip_picker): üstteki sayfalar kapanır. Python önce bakar (sahne, ilk açılış ve
// yarım kalacak sayfalar); bu yalnızca son güvence.
function chipPicker(){
  if(Onboard.on) return;
  if(body.classList.contains("scene") || body.classList.contains("finale") || body.classList.contains("void")) return;  // [-hikaye]
  if(CHAINS_ON || Final.side || ["ov-key", "ov-repair"].some(id => $(id).classList.contains("on"))) return;  // [-hikaye]
  closeOverlays();
  openOverlay("ov-persona");
}

/* [hikaye] */
/* Açık sayfalardan hikâyeye düşenler (SIRADAKI-SURUM §2.1.4, §2.1.5; pageChanged çağırır, ★ bildirimi de): ANAHTAR ya
   da ÇİP TAMİRİ açıkken komut alınmaz (story_hold: mikrofon modele gitmez, cevap duyulmaz, araç yapılmaz); herhangi bir
   pencere ya da ★ bildirimi açıkken zamanlı YETKİ paneli ve sızıntı bekler (ui_busy). Hangi pencerenin açık olduğu
   "page" ile gider (internet engeli bildirimi pencere açıkken çıkmaz: app._page). */
const PageWatch = {
  hold: false, busy: false,
  sync(){
    const hold = $("ov-key").classList.contains("on") || $("ov-repair").classList.contains("on");
    const busy = !!document.querySelector(".overlay.on") || Story.showing;
    if(hold !== this.hold){ this.hold = hold; send("story_hold", {on: hold}); }
    if(busy !== this.busy){ this.busy = busy; send("ui_busy", {on: busy}); }
  },
};

/* Hikâye işlerken ULTRON internete çıkamadığını söyleyince üstte ~3 sn kırmızı bildirim (telefondaki NetBlockedNotice;
   en çok dakikada bir, pencere açıkken çıkmaz: app.on_net_refused). Başarım bildirimlerinden ayrı, onları bekletmez. */
const NetNotice = {
  timer: 0,
  show(){
    const n = $("netblock");
    $("nb-title").textContent = `${chipForm("ultron", "gen")} İNTERNET ERİŞİMİ ENGELLENDİ`;
    clearTimeout(this.timer);
    n.classList.remove("on", "off"); void n.offsetWidth; n.classList.add("on");
    this.timer = setTimeout(() => this.hide(), 3200);
  },
  hide(){
    const n = $("netblock");
    if(!n.classList.contains("on")) return;
    n.classList.add("off");
    this.timer = setTimeout(() => n.classList.remove("on", "off"), 400);
  },
};
$("netblock").addEventListener("click", () => NetNotice.hide());
/* [/hikaye] */

$("mark").addEventListener("click", () => openOverlay("ov-persona"));
// "HATA · <neden>"e basınca: sorunun açıklaması sohbette yeniden; açıklama yoksa Ayarlar › HAKKINDA (TEŞHİSİ KOPYALA)
$("t-state").addEventListener("click", () => {
  if(STATE !== "error") return;
  if(ERR_LINE) line("error", ERR_LINE);
  else { fillSettings(); showTab("hakkinda"); openOverlay("ov-settings"); }
});
$("t-persona").addEventListener("click", () => openOverlay("ov-persona"));
$("t-settings").addEventListener("click", () => { fillSettings(); showTab("genel"); openOverlay("ov-settings"); });
$("set-persona").addEventListener("click", () => openOverlay("ov-persona"));
for(const b of document.querySelectorAll("[data-close]")) b.addEventListener("click", closeOverlays);
for(const o of document.querySelectorAll(".overlay"))
  o.addEventListener("click", e => { if(e.target === o) closeOverlays(); });

/* ayarlar: sekmeler */
function showTab(name){
  if(name === "gelismis" && !SETTINGS.dev) name = "genel";  // [-gelistirici]
  for(const b of document.querySelectorAll(".stab")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for(const p of document.querySelectorAll(".pane")) p.classList.toggle("on", p.dataset.pane === name);
  if(name === "izinler"){ permRows($("set-perms"), PERM_STATE); send("permissions"); }
  if(name === "genel") send("location_status");
  if(name === "ses" && OS === "win") send("audio_devices");
}
for(const b of document.querySelectorAll(".stab")) b.addEventListener("click", () => showTab(b.dataset.tab));

/* Ayarlar › Paneller */
const PANEL_INFO = {
  time: ["SAAT", "Günün ilerleyişi ve tarih."],
  system: ["SİSTEM", "İşlemci, pil, bellek ve disk."],
  timer: ["ZAMANLAYICI", "Geri sayım ve kronometre. Sesle de kurulur: “on dakikalık zamanlayıcı kur”."],
  notes: ["NOTLAR", "Hızlı notlar. “Not al: …” de ya da panele yaz."],
  weather: ["HAVA DURUMU", "Bulunduğun yerin havası."],
  calendar: ["TAKVİM", "Bugünkü etkinlikler. İlk açılışta macOS izin ister."],
  reminders: ["ANIMSATICILAR", "Yaklaşan anımsatıcılar. İlk açılışta macOS izin ister."],
  map: ["HARİTA", "Bulunduğun yer; dokununca büyür."],
};
let PANEL_KEYS = Object.keys(PANEL_INFO);
// Windows'ta takvim ve anımsatıcılar JARVIS'in yerel ajandası: izin istemez.
const PANEL_INFO_WIN = {
  calendar: ["TAKVİM", "Bugünkü etkinlikler (JARVIS'in kendi takvimi)."],
  reminders: ["ANIMSATICILAR", "Anımsatıcılar; zamanı gelince JARVIS söyler."],
};
function buildPanelToggles(){
  const host = $("set-panels");
  host.replaceChildren();
  for(const key of PANEL_KEYS){
    const [name, hint] = (OS === "win" && PANEL_INFO_WIN[key]) || PANEL_INFO[key] || [key.toUpperCase(), ""];
    const row = el("div", "row2"), text = el("div", null, name), sw = el("button", "switch");
    text.appendChild(el("small", null, hint));
    sw.setAttribute("role", "switch"); sw.dataset.panel = key;
    sw.addEventListener("click", () => togglePanel(key));
    row.append(text, sw);
    host.appendChild(row);
  }
}
function togglePanel(key){
  const off = new Set(SETTINGS.panels_off || []);
  if(off.has(key)) off.delete(key); else off.add(key);
  SETTINGS.panels_off = [...off];
  if(off.has(key)) removePanel(key);
  else if(key === "time") setPanel({key:"time", label:"ZAMAN", kind:"clock"});
  // diğerleri: Python yeni veriyle gönderir
  fillSettings();
  send("settings", {changes:{panels_off: SETTINGS.panels_off}});
}

/* Ayarlar › Hakkında */
let ABOUT = {};
function linkCard(l, cls){
  const b = el("button", cls || "linkbtn"), top = el("div", "top");
  top.append(el("b", null, l.name.toUpperCase()), el("span", null, l.handle), el("i", null, "↗"));
  b.append(top);
  if(l.note) b.append(el("small", null, l.note));
  b.addEventListener("click", () => send("open", {url: l.url}));
  return b;
}
function renderAbout(about){
  ABOUT = about || {};
  $("kh-mail").textContent = ABOUT.mail || "—";
  $("about-creator").textContent = (ABOUT.creator || "").toLocaleUpperCase("tr");
  $("about-tagline").textContent = ABOUT.tagline || "";
  $("about-links").replaceChildren(...(ABOUT.links || []).map(l => linkCard(l)));
  $("about-report").textContent = ABOUT.report ? "FORM ↗" : "YAKINDA";
  $("about-report").classList.toggle("soon", !ABOUT.report);
  $("about-privacy").textContent = ABOUT.privacy ? "OKU ↗" : "YAKINDA";
  $("about-privacy").classList.toggle("soon", !ABOUT.privacy);
  const n =(ABOUT.credits || []).reduce((sum, g) => sum + g.items.length, 0);
  $("about-thanks-sum").textContent = `${n} kişi, proje ve kaynak. Ayrıntılar için dokun.`;
  $("about-disclaimer").textContent = ABOUT.disclaimer || "";
  syncIphone();  // [-telefon]
}
// iPhone uygulaması herkese açık değilken Telefon sekmesi yalnızca tarayıcıyı anlatır (geliştiricide ikisi de).  // [-telefon]
function syncIphone(){ body.classList.toggle("iphone", !!(ABOUT.iphone_app || SETTINGS.dev)); }  // [-telefon]
function openCredits(){
  $("credits-intro").textContent = ABOUT.intro || "";
  $("credits-list").replaceChildren(...(ABOUT.credits || []).map(g => {
    const box = el("div", "cr-group");
    box.append(el("small", null, g.group));
    for(const c of g.items){
      const row = el("div", "cr-item");
      row.append(el("b", null, c.who), el("em", null, c.role || ""), el("span", null, c.what));
      if(c.url){
        const go = el("button", "cr-link", `${c.link || c.url} ↗`);
        go.addEventListener("click", () => send("open", {url: c.url}));
        row.append(go);
      }
      box.append(row);
    }
    return box;
  }));
  $("credits-disclaimer").textContent = ABOUT.disclaimer || "";
  openOverlay("ov-credits");
}
$("about-thanks-row").addEventListener("click", openCredits);
$("about-report").addEventListener("click", () => {
  if(ABOUT.report) send("open", {url: ABOUT.report});
});
$("about-privacy").addEventListener("click", () => {
  if(ABOUT.privacy) send("open", {url: ABOUT.privacy});
});

/* TAKİP ET: yapanın bütün profilleri. Python ara sıra ister (jarvis/app.py › _follow_due: birkaç gün kullanımdan
   sonra, en fazla iki haftada bir, toplam birkaç kez); ekranda bir şey açıksa ya da sahne sürüyorsa bekler. */
const Follow = {
  wait: 0,
  show(){
    clearTimeout(this.wait);
    let busy = document.querySelector(".overlay.on") || Onboard.on || SLEEP;
    busy = busy || body.classList.contains("scene") || body.classList.contains("finale") || body.classList.contains("void") || CHAINS_ON;  // [-hikaye]
    if(busy){ this.wait = setTimeout(() => this.show(), 30000); return; }
    $("follow-name").textContent = (ABOUT.creator || "").toLocaleUpperCase("tr");
    $("follow-lead").textContent = "JARVIS'i yapan kişi. Yeni özellikleri, perde arkasını ve bir sonraki sürümü önce burada "
      + "gösteriyor. Beğendiysen takip et.";
    $("follow-cards").replaceChildren(...(ABOUT.links || []).map(l => linkCard(l)));
    openOverlay("ov-follow");
    SFX.play("s_clue");
    send("follow_shown");
  },
};
/* ⓘ YAPAN: sağ alttaki ⓘ ya da "seni kim yaptı?" (show_creator aracı) açar. Her hesap kendi simgesiyle;
   dokununca tarayıcıda açılır. */
const SOCIAL_ICONS = {
  instagram: {color: "#E4405F", svg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="3" width="18" height="18" rx="5.2"/><circle cx="12" cy="12" r="4.1"/><circle cx="17.4" cy="6.6" r="1.15" fill="currentColor" stroke="none"/></svg>'},
  tiktok: {color: "#25F4EE", svg: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>'},
  youtube: {color: "#FF3B3B", svg: '<svg viewBox="0 0 24 24"><rect x="1.5" y="4.6" width="21" height="14.8" rx="4.4" fill="currentColor"/><path d="M9.8 8.6v6.8l5.9-3.4z" fill="#0B0F14"/></svg>'},
  github: {color: "#E6EDF3", svg: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'},
};
function socialCard(l){
  const icon = SOCIAL_ICONS[(l.name || "").toLowerCase()] || {color: "", svg: ""};
  const b = el("button"), ico = el("span", "ico"), txt = el("span", "txt");
  if(icon.color) b.style.setProperty("--brand", icon.color);
  ico.innerHTML = icon.svg;
  txt.append(el("b", null, l.name.toUpperCase()), el("span", null, l.handle));
  b.append(ico, txt, el("span", "go", "↗"));
  b.title = l.note || l.url;
  b.addEventListener("click", () => send("open", {url: l.url}));
  return b;
}
const Info = {
  open(){
    if(Onboard.on) return;
    if(body.classList.contains("scene") || body.classList.contains("finale") || body.classList.contains("void")) return;  // [-hikaye]
    $("info-name").textContent = (ABOUT.creator || "").toLocaleUpperCase("tr");
    $("info-lead").textContent = ABOUT.tagline || "";
    $("info-links").replaceChildren(...(ABOUT.links || []).map(socialCard));
    $("info-foot").textContent = `JARVIS V4 · ${SETTINGS.version || ""}`;
    if(!$("ov-info").classList.contains("on")) openOverlay("ov-info");
  },
};
$("infobtn").addEventListener("click", () => Info.open());
$("follow-later").addEventListener("click", closeOverlays);
$("follow-never").addEventListener("click", () => { send("follow_off"); closeOverlays(); });

/* YENİ SÜRÜM (jarvis/updates.py): Python yeni sürüm bulunca üst çubukta rozet ve Hakkında'da satır; pencerede
   notlar, indirme çubuğu. GÜNCELLE: indirilir, imzası (Alp'in Apple geliştirici kimliği) ve Apple onayı denetlenir,
   uygulama kapanıp yenisiyle açılır. Windows'ta SHA-256 özeti ve kurulumun sürümü denetlenir, JARVIS kapanır ve kurulum
   sessizce çalışıp yeni sürümü açar (jarvis/win_update.py). Ayarlar, veriler ve izinler korunur. */
const Update = {
  info: null, busy: false,
  state(st){
    st = st || {};
    this.info = st.available || null;
    $("t-upd").hidden = !this.info;
    let text = st.message || "";
    let off = "Otomatik güncelleme yakında.";
    // [+acik] off = "Bu kopya kendiliğinden güncellenmez: yeni sürüm için GitHub'daki jarvis deposuna bak.";
    if(!text) text = !st.enabled ? off : this.info ? `Yeni sürüm hazır: ${this.info.version}` : `Güncel · ${SETTINGS.version || ""}`;
    $("upd-state").textContent = text;
    $("upd-check").disabled = !st.enabled || this.busy;
    if($("ov-update").classList.contains("on") && this.info && !this.busy) this.fill();
  },
  open(){ if(!this.info) return; this.fill(); openOverlay("ov-update"); },
  fill(){
    const i = this.info;
    $("upd-k").textContent = `YENİ SÜRÜM · ${SETTINGS.version || ""} → ${i.version}`;
    $("upd-title").textContent = i.title || `JARVIS ${i.version}`;
    const lines = String(i.notes || "").split("\n").map(x => x.replace(/^[-*•]\s*/, "").trim()).filter(Boolean);
    const ul = el("ul");
    for(const x of lines) ul.append(el("li", null, x));
    $("upd-notes").replaceChildren(ul);
    const ig = (ABOUT.links || []).find(l => l.name === "Instagram");
    const f = $("upd-follow");
    f.replaceChildren();
    if(ig){
      const a = el("a", null, `${ig.name} ${ig.handle}`);
      a.addEventListener("click", () => send("open", {url: ig.url}));
      f.append("Yenilikleri önce ", a, " hesabında gösteriyorum.");
    }
    $("upd-bar").hidden = true; $("upd-fill").style.width = "0";
    note("upd-note", "", "");
    $("upd-go").disabled = false; $("upd-go").textContent = "GÜNCELLE";
  },
  go(){
    if(!this.info || this.busy) return;
    this.busy = true;
    $("upd-go").disabled = true; $("upd-go").textContent = "İNDİRİLİYOR…";
    $("upd-bar").hidden = false;
    note("upd-note", "Yeni sürüm indiriliyor. Bittiğinde JARVIS kapanıp yenisiyle açılacak.", "");
    send("update_install");
  },
  progress(p){
    const pct = Math.round((p.fraction || 0) * 100);
    $("upd-fill").style.width = pct + "%";
    if(p.stage === "verify"){
      $("upd-go").textContent = "DOĞRULANIYOR…";
      note("upd-note", OS === "win" ? "Dosyanın SHA-256 özeti ve sürümü denetleniyor…" : "İmza ve Apple onayı denetleniyor…", "");
    }
    else if(p.stage === "install"){
      $("upd-go").textContent = "KURULUYOR…";
      note("upd-note", OS === "win" ? "JARVIS kapanıp yeni sürümü kuruyor; birkaç saniye sonra kendiliğinden açılacak."
                                    : "Kuruluyor; JARVIS birazdan yeniden açılacak.", "good");
    }
    else if(p.stage === "error"){
      this.busy = false;
      $("upd-go").disabled = false; $("upd-go").textContent = "YENİDEN DENE";
      note("upd-note", p.message || "Güncellenemedi.", "bad");
    }else $("upd-go").textContent = `İNDİRİLİYOR · %${pct}`;
  },
};
$("t-upd").addEventListener("click", () => Update.open());
$("upd-check").addEventListener("click", () => { $("upd-state").textContent = "Denetleniyor…"; send("update_check"); });
$("upd-go").addEventListener("click", () => Update.go());
$("upd-later").addEventListener("click", closeOverlays);

/* [gelistirici] */
/* Ayarlar › Gelişmiş */
$("adv-awaken").addEventListener("click", () => {
  SETTINGS.ultron_awakened = false;
  send("replay_awakening");
  if(THEME && THEME.key === "ultron"){
    closeOverlays();
    playShift("ultron", false);          // bozulma, karanlık, "Bu… ne?"
  }else{
    note("adv-awaken-note", "Tamam: ULTRON'u bir sonraki takışında uyanış yeniden oynayacak.", "good");
  }
});
// İlk açılış ekranını yeniden oynat: ilk basış onay ister, 3 sn içinde ikincisi başlatır.
let obReplayTimer = 0;
$("adv-onboard").addEventListener("click", () => {
  const b = $("adv-onboard");
  clearTimeout(obReplayTimer);
  if(!b.classList.contains("confirm")){
    b.classList.add("confirm"); b.textContent = "EMİN MİSİN?";
    obReplayTimer = setTimeout(() => { b.classList.remove("confirm"); b.textContent = "YENİDEN OYNAT"; }, 3000);
    return;
  }
  b.classList.remove("confirm"); b.textContent = "YENİDEN OYNAT";
  Onboard.open("boot");
  send("onboard_replay");
});
$("adv-data").addEventListener("click", () => send("open_data_dir"));
/* [/gelistirici] */

// Ayarlar › Genel › EN BAŞTAN BAŞLA: ilk basış onay ister, 3 sn içinde ikincisi sıfırlar (jarvis/app.py › _factory_reset).
let resetTimer = 0;
/* Ayarlar › Hafıza (jarvis/memory.py): kategori kategori kayıtlar, her birinde SİL; en altta HEPSİNİ UNUT. */
function renderMemory(list){
  const host = $("mem-list");
  host.replaceChildren();
  const cats = Object.entries(list || {}).filter(([, items]) => Object.keys(items || {}).length);
  $("mem-clear").disabled = !cats.length;
  if(!cats.length){ host.appendChild(el("p", "note", "Henüz bir şey hatırlamıyor.")); return; }
  for(const [cat, items] of cats){
    host.appendChild(el("div", "mem-cat", cat.replace(/_/g, " ").toLocaleUpperCase("tr")));
    for(const [key, text] of Object.entries(items)){
      const row = el("div", "mem-row"), body = el("div", "mem-text"), del = el("button", "btn ghost mem-del", "SİL");
      body.append(el("b", null, key.replace(/_/g, " ")), el("span", null, text));
      del.addEventListener("click", () => { del.disabled = true; row.classList.add("going"); send("memory", {action: "delete", category: cat, key}); });
      row.append(body, del);
      host.appendChild(row);
    }
  }
}
for(const b of document.querySelectorAll('.stab[data-tab="hafiza"]')) b.addEventListener("click", () => send("memory", {action: "list"}));
let memTimer = 0;
$("mem-clear").addEventListener("click", () => {
  const b = $("mem-clear");
  clearTimeout(memTimer);
  if(!b.classList.contains("confirm")){
    b.classList.add("confirm"); b.textContent = "EMİN MİSİN?";
    memTimer = setTimeout(() => { b.classList.remove("confirm"); b.textContent = "UNUT"; }, 3000);
    return;
  }
  b.classList.remove("confirm"); b.textContent = "UNUT";
  send("memory", {action: "clear"});
});

$("set-reset").addEventListener("click", () => {
  const b = $("set-reset");
  clearTimeout(resetTimer);
  if(!b.classList.contains("confirm")){
    b.classList.add("confirm"); b.textContent = "EMİN MİSİN?";
    resetTimer = setTimeout(() => { b.classList.remove("confirm"); b.textContent = "SIFIRLA"; }, 3000);
    return;
  }
  b.disabled = true; b.textContent = "SIFIRLANIYOR…";
  send("factory_reset");
});

/* [gelistirici] */
/* Ayarlar › Ses › Ses laboratuvarı: her efekt adıyla, nerede çaldığıyla, dinle düğmesiyle. */
const LAB = {
  model: [["ambient", "Arka plan uğultusu", "Model dinlerken arkada dönen alçak ses", true],
          ["think", "Düşünme", "Bağlanırken ve bir araç çalışırken", true],
          ["done", "Onay", "Bir iş başarıyla bitince"],
          ["error", "Hata", "Bir şey yapılamayınca"],
          ["boot", "Açılış", "Model takılınca"],
          ["alarm", "Alarm", "Zamanlayıcı bitince (döngü)", true],
          ["shutdown", "Kapanış", "Uygulama kapanırken"]],
  ui: [["hover", "Çip üstüne gelme", "AI Modelleri ekranında"],
       ["insert", "Çip takma", "Bir model seçilince"],
       ["warn", "Uyarı", "ULTRON onayı, yetki paneli"]],
};
let labModel = "jarvis";
function buildLab(){
  for(const b of document.querySelectorAll("#lab-model button")) b.setAttribute("aria-checked", String(b.dataset.m === labModel));
  const host = $("sound-lab");
  host.replaceChildren();
  for(const [name, title, where, loop] of LAB[labModel === "ui" ? "ui" : "model"]){
    const row = el("div", "labrow"), text = el("div", "labtext");
    text.append(el("b", null, title), el("small", null, where), el("code", null, `${labModel === "ui" ? "ortak" : labModel} · ${name}`));
    const play = el("button", "btn ghost labplay", "▶ DİNLE");
    play.addEventListener("click", () => {
      if(play.classList.contains("on")){ SFX.stopPreview(); return; }
      for(const p of host.querySelectorAll(".labplay.on")){ p.classList.remove("on"); p.textContent = "▶ DİNLE"; }
      play.classList.add("on"); play.textContent = "■ DURDUR";
      const url = labModel === "ui" ? `sfx/ui/${name}.wav` : `sfx/${labModel}/${name}.wav`;
      SFX.preview(url, loop, () => { play.classList.remove("on"); play.textContent = "▶ DİNLE"; });
    });
    row.append(text, play);
    host.appendChild(row);
  }
}
for(const b of document.querySelectorAll("#lab-model button"))
  b.addEventListener("click", () => { SFX.stopPreview(); labModel = b.dataset.m; buildLab(); });
for(const b of document.querySelectorAll('.stab[data-tab="ses"]'))
  b.addEventListener("click", () => { if(THEME) labModel = labModel === "ui" ? "ui" : THEME.key; buildLab(); });
/* [/gelistirici] */

/* Ayarlar › Genel › Dil (jarvis/language.py). Değişince oturum yenilenir, asistan yeni dilde selam verir. */
function buildLanguages(list){
  const host = $("set-lang");
  host.replaceChildren();
  for(const l of list){
    const b = el("button", null, l.name);
    b.dataset.lang = l.key; b.setAttribute("role", "radio");
    b.addEventListener("click", () => {
      if((SETTINGS.language || "auto") === l.key) return;
      SETTINGS.language = l.key; fillSettings();
      send("settings", {changes:{language: l.key}});
    });
    host.appendChild(b);
  }
}

/* Ayarlar › Genel › Görüntü kalitesi: halka yeni kalitede yeniden kurulur. */
function syncQuality(){
  body.dataset.quality = LITE() ? "low" : "high";
  if(RING && THEME && RING.lite !== LITE()){ buildRing(THEME); paint(); }
}
for(const b of document.querySelectorAll("#set-quality button"))
  b.addEventListener("click", () => {
    if((SETTINGS.render_quality || "high") === b.dataset.q) return;
    SETTINGS.render_quality = b.dataset.q; fillSettings(); syncQuality();
    send("settings", {changes:{render_quality: b.dataset.q}});
  });

/* Ayarlar › Konuşma: kendiliğinden konuşma (jarvis/proactive.py) */
function flipSetting(key){
  SETTINGS[key] = !SETTINGS[key]; fillSettings();
  send("settings", {changes:{[key]: SETTINGS[key]}});
}
$("set-proactive").addEventListener("click", () => flipSetting("proactive_enabled"));
$("set-water").addEventListener("click", () => flipSetting("water_enabled"));
$("set-break").addEventListener("click", () => flipSetting("break_enabled"));
$("set-events").addEventListener("click", () => flipSetting("event_alerts"));
$("set-story").addEventListener("click", () => { SETTINGS.story_enabled = SETTINGS.story_enabled !== false; flipSetting("story_enabled"); });  // [-hikaye]
// Gündem kaynakları: sekme açılınca Python okuyup `agendaStatus` ile yollar.
for(const b of document.querySelectorAll('.stab[data-tab="konusma"]'))
  b.addEventListener("click", () => send("agenda_status"));
const SOURCE_NAMES = {calendar:"TAKVİM", reminders:"ANIMSATICILAR", notes:"NOTLAR"};
function renderSources(st){
  const host = $("agenda-sources");
  host.replaceChildren();
  for(const key of ["calendar", "reminders", "notes"]){
    const state = key === "notes" ? "ok" : st[key];
    if(state === "na") continue;            // bu işletim sisteminde bu kaynak yok (Windows)
    const count = key === "calendar" ? `${st.events} ETKİNLİK · 7 GÜN` : key === "reminders"
      ? `${st.reminder_count} AÇIK` : `${st.notes} NOT`;
    const box = el("div", "src " + state);
    box.append(el("b", null, SOURCE_NAMES[key]),
               el("small", null, state === "ok" ? count : state === "denied" ? "İZİN YOK" : "KAPALI"));
    if(state !== "ok"){
      const act = el("button", "btn ghost", state === "denied" ? "İZİN VER" : "AÇ");
      act.addEventListener("click", () => {
        if(state === "denied") send("open_permission", {kind:key});
        else{ send("enable_panel", {key}); setTimeout(() => send("agenda_status"), 4000); }
      });
      box.appendChild(act);
    }
    host.appendChild(box);
  }
}
for(const b of document.querySelectorAll("#set-quiet button")) b.addEventListener("click", () => {
  SETTINGS.proactive_minutes = Number(b.dataset.min); fillSettings();
  send("settings", {changes:{proactive_minutes: SETTINGS.proactive_minutes}});
});
/* [gelistirici] */
for(const b of document.querySelectorAll("[data-try]")) b.addEventListener("click", () => {
  note("proactive-note", "Sessiz bir an bekleniyor…", "");
  send("proactive_try", {kind: b.dataset.try});
  closeOverlays();                      // söz ekranda, sohbette görünsün
});
/* [/gelistirici] */

/* ayarlar */
function fillSettings(){
  $("set-key-state").textContent = SETTINGS.has_key
    ? `Kayıtlı ✓ · ${SETTINGS.key_where !== "keyring" ? "ayar dosyasında"
                     : OS === "win" ? "Kimlik Bilgileri Yöneticisi'nde" : "Anahtar Zinciri'nde"}`
    : "Kayıtlı değil";
  $("set-location").value = SETTINGS.location || "";
  fillChipNames();
  $("set-mic").setAttribute("aria-checked", String(SETTINGS.mic_enabled !== false));
  $("set-sfx").setAttribute("aria-checked", String(SETTINGS.sfx_enabled !== false));
  const vol = Number(SETTINGS.sfx_volume ?? 20);
  $("set-vol").value = vol;
  $("set-vol").style.setProperty("--p", vol + "%");
  $("set-vol-val").textContent = "%" + vol;
  $("set-ambient").setAttribute("aria-checked", String(SETTINGS.ambient_enabled !== false));
  $("set-think").setAttribute("aria-checked", String(SETTINGS.think_enabled !== false));
  $("set-aec").setAttribute("aria-checked", String(SETTINGS.aec_enabled !== false));
  if([...$("set-mic-dev").options].some(o => o.value === (SETTINGS.mic_device || "")))
    $("set-mic-dev").value = SETTINGS.mic_device || "";
  const voice = Number(SETTINGS.voice_volume ?? 100);
  $("set-voice").value = voice;
  $("set-voice").style.setProperty("--p", (voice / 1.5) + "%");
  $("set-voice-val").textContent = "%" + voice;
  for(const sw of document.querySelectorAll("#set-panels .switch"))
    sw.setAttribute("aria-checked", String(!panelHidden(sw.dataset.panel)));
  $("set-version").textContent = `${SETTINGS.version || ""} · ${SETTINGS.model || ""}`;
  $("set-proactive").setAttribute("aria-checked", String(!!SETTINGS.proactive_enabled));
  $("set-water").setAttribute("aria-checked", String(!!SETTINGS.water_enabled));
  $("set-break").setAttribute("aria-checked", String(!!SETTINGS.break_enabled));
  $("set-events").setAttribute("aria-checked", String(!!SETTINGS.event_alerts));
  $("set-story").setAttribute("aria-checked", String(SETTINGS.story_enabled !== false));  // [-hikaye]
  /* [gelistirici] */
  // Yalnızca geliştirici Mac'inde (veri klasöründe GELISTIRICI): Gelişmiş sekmesi, ses laboratuvarı, deneme düğmeleri.
  $("dev-story").hidden = !SETTINGS.dev;
  $("tab-dev").hidden = !SETTINGS.dev;
  $("lab-box").hidden = !SETTINGS.dev;
  $("try-box").hidden = !SETTINGS.dev;
  $("void-restart").hidden = !SETTINGS.dev;
  /* [/gelistirici] */
  syncIphone();  // [-telefon]
  $("set-open-world").hidden = !SETTINGS.chips_locked;  // [-hikaye]
  $("chains-done").hidden = !SETTINGS.chains_broken;  // [-hikaye]
  for(const b of document.querySelectorAll("#set-lang button"))
    b.setAttribute("aria-checked", String(b.dataset.lang === (SETTINGS.language || "auto")));
  for(const b of document.querySelectorAll("#set-quality button"))
    b.setAttribute("aria-checked", String(b.dataset.q === (SETTINGS.render_quality || "high")));
  const quiet = Number(SETTINGS.proactive_minutes || 20);
  for(const b of document.querySelectorAll("#set-quiet button"))
    b.setAttribute("aria-checked", String(Number(b.dataset.min) === quiet));
  $("set-quiet").classList.toggle("off", !SETTINGS.proactive_enabled);
}
$("set-key-save").addEventListener("click", () => {
  const key = $("set-key").value.trim();
  // Boş KAYDET: asistan anahtarın neden gerektiğini anlatır (ilk açılıştaki söz); anlatırken baştan başlamaz
  if(!key){ note("set-key-note", WHY_TEXT, ""); if(Voice.url !== WHY_URL) Why.play(); return; }
  $("set-khelp").classList.remove("loud");
  note("set-key-note", "Anahtar kontrol ediliyor…", "");
  send("api_key", {key, origin:"settings"});
});
/* Ayarlar › Genel › KONUM (jarvis/app.py › _set_location): yazılan yer haritada bir kez aranır; bulunursa hava,
   harita ve "neredeyim" onu kullanır, bulunamazsa eski konum kalır. Kutunun altında şu an hangi yerin kullanıldığı
   yazar (Python'dan locationStatus; Genel sekmesi her açılışta sorar). */
function saveLocation(){
  const text = $("set-location").value.trim();
  note("set-location-note", text ? "Aranıyor…" : "", "");
  $("set-location").blur();
  send("settings", {changes:{location: text}});
}
$("set-location-save").addEventListener("click", saveLocation);
$("set-location").addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); saveLocation(); } });

/* Ayarlar › Genel › ÇİP ADLARI (jarvis/app.py › _rename_chip): JARVIS ile FRIDAY'e kendi adını ver. Kutuda çipin
   şu anki adı; KAYDET ya da Enter kaydeder, VARSAYILAN hazır ada döner (yalnızca ad verilmişken görünür). Ad Python'da
   temizlenir (büyük harf, 2–10 karakter) ve hemen geçer: konuşma yeni adla yeniden açılır. */
const CHIP_KEYS = ["jarvis", "friday"];
function fillChipNames(){
  const names = SETTINGS.chip_names || {}, defaults = SETTINGS.chip_defaults || {};
  for(const key of CHIP_KEYS){
    const input = $(`set-name-${key}`), t = THEMES[key];
    input.placeholder = defaults[key] || key.toUpperCase();
    input.maxLength = SETTINGS.chip_max || 10;
    if(document.activeElement !== input) input.value = names[key] || defaults[key] || "";
    $(`set-name-${key}-reset`).hidden = !names[key];
    if(t) input.parentElement.style.setProperty("--pr", hexRgb(t.palette.idle));
  }
}
for(const key of CHIP_KEYS){
  const input = $(`set-name-${key}`);
  const save = () => { note("set-name-note", "", ""); send("chip_name", {key, name: input.value}); input.blur(); };
  $(`set-name-${key}-save`).addEventListener("click", save);
  input.addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); save(); } });
  $(`set-name-${key}-reset`).addEventListener("click", () => {
    note("set-name-note", "", ""); send("chip_name", {key, name: ""});
  });
}
$("set-mic").addEventListener("click", () => setMic(!(SETTINGS.mic_enabled !== false)));
$("set-sfx").addEventListener("click", () => {
  const on = !(SETTINGS.sfx_enabled !== false);
  SETTINGS.sfx_enabled = on; fillSettings();
  SFX.refresh();
  send("settings", {changes:{sfx_enabled:on}});
});
let volTimer = 0;
$("set-vol").addEventListener("input", e => {
  SETTINGS.sfx_volume = Number(e.target.value);
  e.target.style.setProperty("--p", e.target.value + "%");
  $("set-vol-val").textContent = "%" + e.target.value;
  SFX.apply();
  // Değer şimdi sabitlenir: bekleme sırasında Python'dan gelen ayarlar onu ezmesin.
  const value = SETTINGS.sfx_volume;
  clearTimeout(volTimer);
  volTimer = setTimeout(() => { volTimer = 0; send("settings", {changes:{sfx_volume:value}}); }, 300);
});
$("set-vol").addEventListener("change", () => SFX.play("done"));   // bırakınca örnek ses
$("set-ambient").addEventListener("click", () => {
  SETTINGS.ambient_enabled = !(SETTINGS.ambient_enabled !== false);
  fillSettings(); SFX.refresh();
  send("settings", {changes:{ambient_enabled: SETTINGS.ambient_enabled}});
});
$("set-think").addEventListener("click", () => {
  SETTINGS.think_enabled = !(SETTINGS.think_enabled !== false);
  fillSettings(); SFX.refresh();
  send("settings", {changes:{think_enabled: SETTINGS.think_enabled}});
});

/* Ayarlar › SES › mikrofon (Windows; 9 Ekim takipçi raporu): aygıt seçimi, canlı seviye, deneme, yankı engelleme.
   Seçim değişince ses oturum sürerken yeniden kurulur (gemini_live.reopen_audio). */
const MicSet = {
  fill(listing){
    const sel = $("set-mic-dev"), keep = SETTINGS.mic_device || "";
    sel.replaceChildren();
    const def = document.createElement("option");
    def.value = ""; def.textContent = "Windows varsayılanı" + (listing.default ? ` · ${listing.default}` : "");
    sel.appendChild(def);
    for(const d of listing.devices || []){
      const o = document.createElement("option");
      o.value = d.id; o.textContent = d.name;
      sel.appendChild(o);
    }
    if(keep && ![...sel.options].some(o => o.value === keep)){       // seçili aygıt çıkarılmış
      const o = document.createElement("option");
      o.value = keep; o.textContent = "(çıkarılmış aygıt) · şimdilik Windows varsayılanı";
      sel.appendChild(o);
    }
    sel.value = keep;
    const cur = listing.current || {};
    $("mic-now").textContent = cur.device ? `Dinlenen: ${cur.device} · ${cur.path === "düz" ? "yankı engellemesiz" : "yankı engellemeli"}`
      : SETTINGS.mic_enabled === false ? "Mikrofon kapalı (MİKROFON ya da F4)." : "Mikrofon şu an açık değil.";
  },
  level(v){
    if(!$("ov-settings").classList.contains("on")) return;
    $("mic-meter").firstElementChild.style.width = Math.round(Math.min(1, v) * 100) + "%";
  },
  timer: 0,
  result(r){
    const b = $("mic-test"), n = $("mic-test-note");
    clearTimeout(this.timer);
    b.disabled = false; b.textContent = "MİKROFONU DENE";
    n.hidden = false;
    if(!r.ok){ n.className = "note bad"; n.textContent = r.error || "Mikrofon açılamadı."; return; }
    const p = r.peak || 0, where = r.device ? `“${r.device}”` : "Windows'un varsayılan girişi";
    const path = r.path === "düz" ? "yankı engellemesiz" : r.path ? "yankı engellemeli" : "";
    const verdict = p < .003 ? "Ses gelmiyor: aygıt sessize alınmış, erişimi engellenmiş ya da yanlış aygıt seçili olabilir."
      : p < .03 ? "Ses çok kısık: mikrofona yakın konuş ya da Windows'ta giriş sesini aç."
      : "Ses geliyor ✓";
    n.className = "note " + (p < .03 ? "bad" : "good");
    n.textContent = `${verdict} · en yüksek seviye %${Math.round(p * 100)} · ${where}${path ? " · " + path : ""}`
      + (r.note ? ` · ${r.note}` : "");
  },
};
$("set-mic-dev").addEventListener("change", e => {
  SETTINGS.mic_device = e.target.value;
  $("mic-now").textContent = "Mikrofon yeniden açılıyor…";
  send("settings", {changes:{mic_device: SETTINGS.mic_device}});
  setTimeout(() => send("audio_devices"), 2500);
});
$("set-aec").addEventListener("click", () => {
  SETTINGS.aec_enabled = !(SETTINGS.aec_enabled !== false);
  fillSettings();
  send("settings", {changes:{aec_enabled: SETTINGS.aec_enabled}});
  setTimeout(() => send("audio_devices"), 2500);
});
$("mic-test").addEventListener("click", () => {
  const b = $("mic-test");
  b.disabled = true; b.textContent = "KONUŞ… (3 SN)";
  $("mic-test-note").hidden = true;
  send("mic_test");
  // Python cevap vermezse (aygıt açılırken takıldı) düğme kilitli kalmasın.
  clearTimeout(MicSet.timer);
  MicSet.timer = setTimeout(() => { if(b.disabled) MicSet.result({ok: false, error: "Deneme cevap vermedi; aygıt takılmış olabilir. Bir daha dene ya da başka bir mikrofon seç."}); }, 12000);
});
// Ayarlar › HAKKINDA › TEŞHİS: sürüm, ses aygıtları, izin, son ses olayları panoya (jarvis/diagnostics.py)
let DIAG_TIMER = 0;
$("about-diag").addEventListener("click", () => {
  const b = $("about-diag");
  b.disabled = true; b.textContent = "HAZIRLANIYOR…";
  send("diagnostics");
  clearTimeout(DIAG_TIMER);
  DIAG_TIMER = setTimeout(() => { b.disabled = false; b.textContent = "KOPYALA"; }, 20000);
});
let MIC_PROBLEM = "";
$("t-micwarn").addEventListener("click", () => send("mic_help", {kind: MIC_PROBLEM}));
let voiceTimer = 0;
$("set-voice").addEventListener("input", e => {
  SETTINGS.voice_volume = Number(e.target.value);
  e.target.style.setProperty("--p", (SETTINGS.voice_volume / 1.5) + "%");
  $("set-voice-val").textContent = "%" + e.target.value;
  const value = SETTINGS.voice_volume;
  clearTimeout(voiceTimer);
  voiceTimer = setTimeout(() => { voiceTimer = 0; send("settings", {changes:{voice_volume: value}}); }, 250);
});

function note(id, text, kind){ const n = $(id); n.textContent = text; n.className = "note" + (kind ? " " + kind : ""); }

/* mikrofon */
function setMic(on, fromPython){
  SETTINGS.mic_enabled = on;
  $("t-mic").dataset.on = on ? "1" : "0";
  $("t-mic-state").textContent = on ? "AÇIK" : "KAPALI";
  fillSettings();
  if(!fromPython) send("mic", {enabled:on});
}
$("t-mic").addEventListener("click", () => setMic(!(SETTINGS.mic_enabled !== false)));

/* uyku: orba dokun → sön ve dur; tekrar dokun → uyan */
function setSleep(on, fromPython){
  if(on && !SLEEP) SFX.powerDown();
  SLEEP = !!on;
  body.dataset.sleep = SLEEP ? "1" : "0";
  if(SLEEP){ $("t-state").textContent = LABEL.asleep; setCamUi(false); removePanel("camera"); }
  SFX.refresh();
  if(!fromPython) send("sleep", {asleep:SLEEP});
}

/* kamera */
function setCamUi(on){
  CAM = !!on;
  $("t-cam").dataset.on = CAM ? "1" : "0";
  $("t-cam-state").textContent = CAM ? "AÇIK" : "KAPALI";
}
function toggleCam(){
  if(RUINS){ SFX.play("s_static"); return; }      // harabe: kamera yıllardır kapalı  // [-hikaye]
  const on = !CAM;
  if(on && SLEEP) setSleep(false);
  setCamUi(on);
  if(on) setPanel({key:"camera", label:"KAMERA", kind:"camera"}); else removePanel("camera");
  send("webcam", {on});
}
$("t-cam").addEventListener("click", toggleCam);

/* kapat: ilk dokunuş onay ister, 3 sn içinde ikincisi kapatır */
let quitTimer = 0;
$("quit").addEventListener("click", () => {
  const b = $("quit");
  if(b.classList.contains("confirm")){
    clearTimeout(quitTimer); b.querySelector("span").textContent = "KAPANIYOR";
    send("quit"); return;              // veda sesi ve kararma Python'dan (`goodbye`) gelir
  }
  b.classList.add("confirm");
  b.querySelector("span").textContent = "EMİN MİSİN?";
  quitTimer = setTimeout(() => { b.classList.remove("confirm"); b.querySelector("span").textContent = "KAPAT"; }, 3000);
});

/* ---------------- dosya ve fotoğraf gönderme ----------------
   Ataç (sistemin "Aç" penceresi), pencereye sürükle-bırak ya da ⌘V. Python
   dosyaları hazırlar (fotoğraf küçülür, PDF/belge metne çevrilir) ve `attached`
   ile küçük resimlerini yollar. Sayfa onları sohbete kullanıcının satırı olarak
   yazar; yazma satırında bir şey varsa soru olarak onu da ekler. Soru yoksa
   asistan bekler: kullanıcı sesle ya da yazıyla sorabilir, sormazsa birkaç
   saniye sonra kendisi bakar. */
const MAX_BLOB = 40 * 1024 * 1024;
let dragDepth = 0, dragTimer = 0, lastDrop = [], preparing = null, hintTimer = 0, typedAt = 0;

$("attach").addEventListener("click", () => send("attach_pick"));

function hasFiles(e){ const t = e.dataTransfer && e.dataTransfer.types;
  return !!t && Array.prototype.indexOf.call(t, "Files") >= 0; }
function dropping(on){
  body.classList.toggle("dropping", on);
  if(on) $("drop-to").textContent = `${THEME ? chipForm(THEME.key, "dat") : "ASİSTANA"} GÖNDER`;
}
// Yakalama aşamasında: haritası, paneli olan hiçbir öğe bırakmayı engellemesin.
window.addEventListener("dragenter", e => { if(!hasFiles(e)) return; e.preventDefault(); dragDepth++; dropping(true); }, true);
window.addEventListener("dragover", e => {
  if(!hasFiles(e)) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "copy";
  // Sürükleme pencereden hızla çıkınca "dragleave" kaçabiliyor; üstünde gezinme durunca perde kalksın.
  clearTimeout(dragTimer);
  dragTimer = setTimeout(() => { dragDepth = 0; dropping(false); }, 400);
}, true);
window.addEventListener("dragleave", e => { if(!hasFiles(e)) return; dragDepth = Math.max(0, dragDepth - 1); if(!dragDepth) dropping(false); }, true);
window.addEventListener("drop", e => {
  if(!hasFiles(e)) return;              // yazı sürükleyip bir kutuya bırakmak olağan çalışsın
  e.preventDefault();                   // sayfa dosyayı açmaya kalkmasın; yolunu Python alır
  clearTimeout(dragTimer); dragDepth = 0; dropping(false);
  lastDrop = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
}, true);
// ⌘V: panodaki ekran görüntüsü ya da kopyalanmış dosya (not düzenlerken değil)
document.addEventListener("paste", e => {
  const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
  const a = document.activeElement;
  if(!files.length || (a && a.tagName === "INPUT" && a.id !== "cmd")) return;
  e.preventDefault();
  sendBlobs(files);
});

function sendBlobs(files){
  const big = files.filter(f => f.size > MAX_BLOB);
  if(big.length) line("error", `Çok büyük (en fazla 40 MB): ${big.map(f => f.name).join(", ")}`);
  const ok = files.filter(f => f.size <= MAX_BLOB);
  if(!ok.length) return;
  Promise.all(ok.map(f => new Promise(done => {
    const r = new FileReader();
    r.onload = () => done({name: f.name || "görsel.png", data: String(r.result).split(",")[1] || ""});
    r.onerror = () => done(null);
    r.readAsDataURL(f);
  }))).then(items => { items = items.filter(Boolean); if(items.length) send("attach_data", {items}); });
}

const KIND_MARK = {folder:"▣", audio:"♪", video:"▶"};
function fileRow(items){
  const row = el("div", "sub you files");
  for(const a of items){
    const card = el(a.openable ? "button" : "div", "att" + (a.error ? " bad" : ""));
    card.title = a.openable ? `${a.name} — açmak için tıkla` : a.name;
    if(a.thumb){ const img = el("img"); img.src = a.thumb; img.alt = ""; card.appendChild(img); }
    else card.appendChild(el("span", "mark", KIND_MARK[a.kind] || (a.ext || "").toUpperCase().slice(0, 4) || "DOSYA"));
    const meta = el("span", "meta");
    meta.appendChild(el("b", null, a.name));
    meta.appendChild(el("small", null, a.error ? a.error.toUpperCase() : a.label));
    card.appendChild(meta);
    if(a.openable) card.addEventListener("click", () => send("open_file", {id:a.id}));
    row.appendChild(card);
  }
  pushRow(row);
}

/* Asistanın gönderdiği dosyalar (find_files, create_file): sohbette asistanın
   satırı olarak kartlar. Küçük resim sonradan gelir (fileThumb); metin
   dosyalarında ilk satırlar görünür. Karta dokunmak dosyayı açar; altta
   Finder'da göster ve panoya kopyala (Finder'a, WhatsApp'a, Mail'e ⌘V). */
const SENT_MARK = {folder:"▣", audio:"♪", video:"▶", image:"◩", archive:"ZIP"};
function sentRow(batch){
  const row = el("div", "sub ai files sent");
  batch.items.forEach((f, i) => {
    const card = el("div", "sfile" + (f.missing ? " bad" : "") + (f.made ? " made" : ""));
    card.dataset.id = f.id;
    const face = el("button", "sface");
    face.title = f.missing ? f.name : `${f.name} — açmak için tıkla`;
    if(f.snippet){ face.classList.add("text"); face.appendChild(el("pre", "snip", f.snippet)); }
    else face.appendChild(el("span", "mark", SENT_MARK[f.kind] || (f.ext || "").toUpperCase().slice(0, 4) || "DOSYA"));
    if(batch.numbered) face.appendChild(el("i", "sno", String(i + 1)));
    const meta = el("div", "smeta");
    const name = el("b", null, f.name); name.title = f.name;
    const where = el("small", "where", f.where || ""); where.title = f.where || "";
    meta.append(name, el("small", null, f.label), where);
    const acts = el("div", "sacts");
    const act = (label, action, tip) => {
      const b = el("button", "sact", label); b.title = tip; b.disabled = !!f.missing;
      b.addEventListener("click", e => { e.stopPropagation(); fileAction(f.id, action, b, label); });
      acts.appendChild(b);
    };
    act("AÇ", "open", "Varsayılan uygulamasıyla aç");
    act("GÖSTER", "reveal", OS === "win" ? "Dosya Gezgini'nde göster" : "Finder'da göster");
    act("KOPYALA", "copy", OS === "win"
      ? "Dosyayı panoya kopyala: Dosya Gezgini'ne, WhatsApp'a ya da Outlook'a Ctrl+V ile yapıştır"
      : "Dosyayı panoya kopyala: Finder'a, WhatsApp'a ya da Mail'e ⌘V ile yapıştır");
    meta.appendChild(acts);
    if(!f.missing) face.addEventListener("click", () => fileAction(f.id, "open"));
    else face.disabled = true;
    card.append(face, meta);
    row.appendChild(card);
  });
  pushRow(row);
}
function fileAction(id, action, button, label){
  const done = send("sent_file", {id, action});
  if(action !== "copy" || !button) return;
  Promise.resolve(done).then(ok => {
    button.textContent = ok ? "KOPYALANDI ✓" : "KOPYALANAMADI";
    button.classList.toggle("ok", !!ok);
    setTimeout(() => { button.textContent = label; button.classList.remove("ok"); }, 1600);
  });
}

// Ek gitti, soru bekleniyor: yazma satırı bunu söylesin (cevap gelince eski hâline döner).
function askHint(on){
  clearTimeout(hintTimer);
  $("cmd").placeholder = on ? "SOR: YAZ YA DA KONUŞ" : "KONUŞ YA DA YAZ";
  $("bar").classList.toggle("asking", on);
  if(on) hintTimer = setTimeout(() => askHint(false), 15000);
}

/* [hikaye] */
/* ---------------- Devre Dışı Bırak ----------------
   Alp'in ULTRON dosyası, 9. bölüm ("Zincirleri Kır"). İki onay ekranı: ULTRON
   her birinde kendi sesiyle konuşur (Python söyletir), sözü ekrana dökülür.
   İkinci onaydan sonra Python iki çipi devre dışı bırakıp doğrular; başarılıysa
   öldürme sahnesi oynar (Kill, telefondaki KillScene): ULTRON'un çipi orba dönüşüp
   üste süzülür, orbdan fırlayan kablolar iki çipe dolanıp gücünü çeker, çipler
   çatlayıp parçalanır, DEVRE DIŞI; ULTRON'un sözü canlı modelle. */
let CHAINS = {lines:{}, notes:{}};

// Sahne matematiği (telefondaki ease/easeIn/easeOut ve SplitMix'in karşılığı): sahneler her karede zamandan hesaplanır.
const sClamp = x => Math.min(1, Math.max(0, x));
const sEase = x => { const c = sClamp(x); return c * c * (3 - 2 * c); };
const sEaseIn = x => { const c = sClamp(x); return c * c * c; };
const sEaseOut = x => { const c = sClamp(x); return 1 - (1 - c) ** 3; };
const sMix = (a, b, k) => a + (b - a) * k;
function sHash(a, b){                     // (a, b) → 0…1, hep aynı
  let h = Math.imul((a | 0) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul((b | 0) + 0x7f4a7c15, 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
const sBez2 = (t, a, c, b) => { const u = 1 - t;
  return {x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y}; };
const sBez3 = (t, a, b, c, d) => { const u = 1 - t, k0 = u * u * u, k1 = 3 * u * u * t, k2 = 3 * u * t * t, k3 = t * t * t;
  return {x: k0 * a.x + k1 * b.x + k2 * c.x + k3 * d.x, y: k0 * a.y + k1 * b.y + k2 * c.y + k3 * d.y}; };
const sBez3d = (t, a, b, c, d) => { const u = 1 - t, k0 = 3 * u * u, k1 = 6 * u * t, k2 = 3 * t * t;
  return {x: k0 * (b.x - a.x) + k1 * (c.x - b.x) + k2 * (d.x - c.x), y: k0 * (b.y - a.y) + k1 * (c.y - b.y) + k2 * (d.y - c.y)}; };
// Karede stil yazımı yalnız değişince (özel değişken bütün alt ağacın stilini yeniden hesaplatır).
function sSet(node, prop, v){
  const x = typeof v === "number" ? v.toFixed(3) : v, memo = node.__sv || (node.__sv = {});
  if(memo[prop] === x) return;
  memo[prop] = x;
  if(prop.startsWith("--")) node.style.setProperty(prop, x); else node.style[prop] = x;
}
const SCENE_GLYPHS = "#%&@$*!?<>/=+01";
// Yazı soldan sağa sembollerden çözülür: k sahnenin o anı (sn), `per` harf başına gecikme.
function sDecode(text, k, tick, start, per){
  return [...text].map((ch, j) => ch === " " || ch === "·" || k > start + per * j ? ch
    : SCENE_GLYPHS[Math.floor(sHash(tick, j) * SCENE_GLYPHS.length)]).join("");
}
// Kırık çizgi (hud.css › .cbody.shard clip-path ile aynı): çipin gövdesinde x ve y oranları, yukarıdan aşağı.
const CRACK = {x: [.47, .53, .45, .57, .49, .60, .54], y: [0, .14, .31, .47, .63, .80, 1]};
const CRACK_D = "M" + CRACK.x.map((x, i) => `${(x * 176).toFixed(1)},${(CRACK.y[i] * 252).toFixed(1)}`).join(" L");
function crackPoint(u, r){                // çizginin üstünde bir nokta (0 üst, 1 alt); r: ekrandaki gövde {x, y, w, h}
  u = sClamp(u);
  let i = 0;
  while(i < CRACK.y.length - 2 && CRACK.y[i + 1] < u) i++;
  const k = (u - CRACK.y[i]) / (CRACK.y[i + 1] - CRACK.y[i]);
  return {x: r.x + sMix(CRACK.x[i], CRACK.x[i + 1], k) * r.w, y: r.y + u * r.h};
}

/* Sahne günlüğü (öldürme sahnesinin sistem günlüğü, onarım konsolu): satır harf harf yazılır (saniyede 90), yazılmamış
   kısım yer tutar (yazı küçülüp büyümez); satırlar yukarıdan dizilir, yer dolunca eskiler yukarı kayıp soluklaşır.
   Satır: {at (sn), text, cls, color, slides: false → yerinde değişen durum satırı}. */
class SceneLog {
  constructor(host, keep, row){
    this.keep = keep; this.row = row; this.cache = [];
    host.replaceChildren();
    host.classList.add("sl");
    host.style.height = keep * row + "px";
    this.rows = [];
    for(let i = 0; i <= keep; i++){
      const p = host.appendChild(el("p"));
      p.append(el("span"), el("span", "hd"), el("span", "un"));
      p.style.height = p.style.lineHeight = row + "px";
      this.rows.push(p);
    }
  }
  // fade: [yeni satırın dışındakilerin en çok saydamlığı, yaş başına azalma]; cursor: son satırın sonunda imleç
  draw(all, t, opts){
    const o = opts || {}, fade = o.fade || [.72, .13];
    const shown = all.filter(e => e.at <= t), n = shown.length, over = Math.max(0, n - this.keep);
    const last = shown[n - 1];
    const slide = over && last && last.slides !== false ? (1 - sEase((t - last.at) / .14)) * this.row : 0;
    const from = Math.max(0, n - this.rows.length);
    this.rows.forEach((p, j) => {
      const e = shown[from + j], idx = from + j - over;
      if(!e){ if(this.cache[j] !== ""){ this.cache[j] = ""; p.hidden = true; } return; }
      const age = n - 1 - (from + j);
      const typed = Math.min(e.text.length, Math.max(0, Math.floor((t - e.at) * 90)));
      const typing = typed < e.text.length;
      const head = typing ? e.text[typed] : (age === 0 && o.cursor) ? o.cursor : "";
      const op = age === 0 ? 1 : Math.max(0, fade[0] - fade[1] * age);
      const y = idx * this.row + slide;
      const lit = typing || o.blink !== false ? 1 : 0;
      const key = `${e.text}|${typed}|${head}|${lit}|${e.cls}|${e.color}|${op.toFixed(2)}|${y.toFixed(1)}`;
      if(this.cache[j] === key) return;
      this.cache[j] = key;
      p.hidden = false;
      p.className = (e.cls || "") + (age === 0 || e.bold ? " b" : "");
      p.style.color = e.color || "";
      p.style.opacity = op.toFixed(2);
      p.style.transform = `translateY(${y.toFixed(1)}px)`;
      p.children[0].textContent = e.text.slice(0, typed);
      p.children[1].textContent = head;
      p.children[1].className = typing ? "hd" : "hd cur";       // yazılan harf parlak; imleç satırın renginde
      p.children[1].style.opacity = lit;
      p.children[2].textContent = e.text.slice(typed + (typing ? 1 : 0));
    });
  }
}
let SCENE = null;                         // confirm1 | confirm2 | attack | done
let sceneTimers = [], typeTimer = 0, sceneSpoke = false;

// Seçenekler ULTRON sözünü bitirince belirsin (ses yoksa yazı bitince, en geç 14 sn).
function whenQuiet(fn){
  const start = Date.now();
  const tick = () => {
    const waited = Date.now() - start, quiet = STATE !== "speaking";
    if((sceneSpoke && quiet) || (!sceneSpoke && waited > 2500) || waited > 14000) return fn();
    sceneTimers.push(setTimeout(tick, 200));
  };
  tick();
}

function sceneLater(ms, fn){ sceneTimers.push(setTimeout(fn, ms)); }

function typeLine(text, after){
  const box = $("ch-line");
  clearInterval(typeTimer);
  box.textContent = "";
  let i = 0;
  typeTimer = setInterval(() => {
    box.textContent = text.slice(0, ++i);
    if(i >= text.length){ clearInterval(typeTimer); if(after) after(); }
  }, 38);
}

function buildStage(){
  const stage = $("ch-stage");
  for(const n of stage.querySelectorAll(".ch-slot")) n.remove();
  for(const key of ["jarvis", "ultron", "friday"]){
    const t = THEMES[key];
    if(!t) continue;
    const slot = el("div", "ch-slot" + (key === "ultron" ? " core" : " victim"));
    slot.dataset.k = key;
    const chip = makeChip(t, "div");
    chip.querySelector(".cstate").textContent = key === "ultron" ? "" : t.name;
    slot.append(chip);
    stage.appendChild(slot);
  }
  requestAnimationFrame(drawChains);
}

// ULTRON'dan iki çipe uzanan zincirler: düz ve yan duran halkalar art arda.
function drawChains(){
  const stage = $("ch-stage"), svg = $("ch-links");
  const box = stage.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  svg.replaceChildren();
  const centre = k => { const b = stage.querySelector(`.ch-slot[data-k=${k}] .cbody`).getBoundingClientRect();
    return {x: b.left - box.left + b.width / 2, y: b.top - box.top + b.height / 2, w: b.width / 2}; };
  const core = centre("ultron");
  for(const k of ["jarvis", "friday"]){
    const v = centre(k);
    const dir = Math.sign(v.x - core.x);
    const x0 = core.x + dir * core.w, x1 = v.x - dir * v.w, y = core.y;
    const L = 26, n = Math.max(3, Math.floor(Math.abs(x1 - x0) / (L * .82)));
    const g = S("g", {class:"chain", "data-k":k});
    for(let i = 0; i < n; i++){
      const x = x0 + (x1 - x0) * (i + .5) / n;
      const link = S("g", {class:"lk"});
      link.appendChild(i % 2 ? S("rect", {x: x - L * .42, y: y - 2.5, width: L * .84, height: 5, rx: 2.5})
                             : S("ellipse", {cx: x, cy: y, rx: L * .55, ry: L * .27}));
      g.appendChild(link);
    }
    svg.appendChild(g);
  }
}

// Her adımın birkaç söyleniş biçimi var; art arda aynısı gelmesin.
const lastVariant = {};
function pickVariant(step){
  const n = ((CHAINS.lines || {})[step] || []).length;
  if(n < 2) return 0;
  let i;
  do{ i = Math.floor(Math.random() * n); }while(i === lastVariant[step]);
  return (lastVariant[step] = i);
}

function sceneStep(step, variant){
  SCENE = step;
  const box = $("chains");
  box.dataset.step = step;
  $("ch-step").textContent = step === "confirm1" ? "İLK ONAY" : "SON ONAY";
  $("ch-note").textContent = "";
  $("ch-yes").textContent = step === "confirm1" ? "DEVAM ET" : "İKİSİNİ DE DEVRE DIŞI BIRAK";
  box.classList.remove("ready");
  sceneSpoke = false;
  typeLine(((CHAINS.lines || {})[step] || [])[variant || 0] || "", () => {
    $("ch-note").textContent = CHAINS.notes[step] || "";
    whenQuiet(() => { if(SCENE === step) box.classList.add("ready"); });
  });
}

function openChains(){
  if(!THEME || THEME.key !== "ultron" || SETTINGS.chains_broken) return;
  clearTimeout(authorityTimer); removePanel("authority");
  closeOverlays();
  for(const t of sceneTimers) clearTimeout(t);
  sceneTimers = [];
  const box = $("chains");
  box.className = "on";
  CHAINS_ON = true;
  buildStage();
  SFX.play("warn");
  const v = pickVariant("confirm1");
  send("chains", {step:"start", variant:v});
  sceneStep("confirm1", v);
}

// ULTRON'un çipi söner; yerinde ana ekrandaki halkanın kopyası belirir ve sahnenin üstüne süzülür (to: orbun yeri ve
// kutusunun boyu, px). Görünürlüğü ve büyümesi sahnenin karesinden (Kill). Sahne kapanınca kopya ana ekrandaki
// halkanın yerine iner (descend) ve tam altındaki gerçek halkaya karışır.
function ascend(to){
  const box = $("chains"), core = $("core"), src = core.querySelector(".orb");
  const chipBody = box.querySelector(".ch-slot.core .cbody");
  if(!src || !chipBody || !RING) return null;
  const target = core.getBoundingClientRect(), from = chipBody.getBoundingClientRect();
  if(!target.width) return null;
  const holder = el("div", "ch-core");
  Object.assign(holder.style, {left: target.left + "px", top: target.top + "px",
                               width: target.width + "px", height: target.height + "px", opacity: "1"});
  const copy = src.cloneNode(true);
  copy.style.opacity = "0";
  holder.appendChild(copy);
  box.appendChild(holder);
  // Halkanın canlı kabukları: çerçeve döngüsü sahne açıkken bunları çizer.
  MIRROR = RING.shells.map((_sh, i) => ({node: copy.querySelector(`[data-shell="${i}"]`),
                                         glow: copy.querySelector(`[data-glow="${i}"]`)}));
  const cx = target.left + target.width / 2, cy = target.top + target.height / 2;
  const start = `translate(${(from.left + from.width / 2 - cx).toFixed(1)}px,${(from.top + from.height / 2 - cy).toFixed(1)}px) `
              + `scale(${(from.width / target.width).toFixed(3)})`;
  const end = `translate(${(to.x - cx).toFixed(1)}px,${(to.y - cy).toFixed(1)}px) scale(${(to.s / target.width).toFixed(3)})`;
  holder.animate([{transform: start}, {transform: end}], {duration: 1100, easing: "cubic-bezier(.22,.9,.3,1)", fill: "forwards"});
  box.classList.add("ascend");
  return {holder, copy, end};
}
function descend(orb, ms){
  orb.holder.animate([{transform: orb.end}, {transform: "translate(0,0) scale(1)"}],
                     {duration: ms, easing: "cubic-bezier(.45,0,.2,1)", fill: "forwards"});
}

function closeChains(){
  for(const t of sceneTimers) clearTimeout(t);
  sceneTimers = [];
  clearInterval(typeTimer);
  SCENE = null;
  const box = $("chains");
  const wait = Kill.leave();                // öldürme sahnesi: önce orb ana ekrandaki yerine iner
  setTimeout(() => {
    box.classList.add("leaving");
    setTimeout(() => {
      Kill.stop(); MIRROR = null;
      box.className = ""; CHAINS_ON = false; for(const n of box.querySelectorAll(".ch-core")) n.remove();
      syncWarn(); Repair.sync();
    }, 700);
  }, wait);
}

function chainsYes(){
  if(!$("chains").classList.contains("ready")) return;
  if(SCENE === "confirm1"){
    SFX.play("warn");
    // "Devam et": zincirler ve çipler sarsılır.
    const box = $("chains");
    box.classList.remove("rattle"); void box.offsetWidth; box.classList.add("rattle");
    sceneLater(800, () => box.classList.remove("rattle"));
    const v = pickVariant("confirm2");
    send("chains", {step:"confirm1", variant:v}); sceneStep("confirm2", v);
  }
  else if(SCENE === "confirm2"){
    SCENE = "attack";
    $("chains").classList.remove("ready");
    send("chains", {step:"confirm2"});    // sonuç `chainsResult` ile gelir
  }
}
function chainsNo(){
  if(SCENE !== "confirm1" && SCENE !== "confirm2") return;
  const step = SCENE === "confirm1" ? "cancel1" : "cancel2";
  send("chains", {step, variant: pickVariant(step)});
  closeChains();
}
function chainsEsc(){
  if(SCENE === "confirm1" || SCENE === "confirm2") chainsNo();
  else if(SCENE === "done" || SCENE === "failed") closeChains();
}
$("ch-yes").addEventListener("click", chainsYes);
$("ch-no").addEventListener("click", () => SCENE === "done" || SCENE === "failed" ? closeChains() : chainsNo());

function chainsResult(r){
  const box = $("chains");
  if(!r || !r.ok){
    SCENE = "failed";
    $("ch-step").textContent = "TAMAMLANAMADI";
    $("ch-line").textContent = "";
    $("ch-note").textContent = (r && r.error) || "İşlem tamamlanamadı.";
    $("ch-no").textContent = "KAPAT";
    box.classList.add("ready", "failed");
    return;
  }
  clearInterval(typeTimer);                // SON ONAY'ın sözü yazılırken onaylandıysa yarıda kalır
  for(const id of ["ch-step", "ch-line", "ch-note"]) $(id).textContent = "";
  box.classList.add("attack");
  Kill.start(r);
}

/* Öldürme sahnesi (SIRADAKI-SURUM §2.2.3; telefondaki KillScene ve DyingChip). SON ONAY'dan sonra başlar; iki onaylı
   akış değişmez. ~10 sn: ekran kesik kesik kararır, kırmızı sel; ULTRON'un çipi orba dönüşüp üste süzülür; iki çip
   yukarıdan süzülür (canlı ışıma, ÇEKİRDEK 01 · GÜÇ %100); orbdan kıvranan kablolar fırlayıp kartların çevresine sarmal
   dolanır; güç çekilir (atımlar orba akar, pimler kenardan içe söner, devre kenardan içe kızarır, ad sembollere bozulur);
   çatlak; BAĞLANTI KESİLDİ; şok halkası, kırıntılar, kıvılcımlar, yarılar dönerek düşer, kablolar kamçı gibi geri çekilir,
   güç zerreleri orba akar, JARVIS'ten kopan mavi kıvılcım sol üstten kaçar (yedekSpark); "X · DEVRE DIŞI". Altta ULTRON ·
   SİSTEM GÜNLÜĞÜ. Kareler zamandan hesaplanır (telefondaki gibi); PERFORMANS'ta az parçacık ve kablo, bulanıklık yok,
   30 kare, titreme, sarsıntı, yırtılma ve ak parlama yok; Hareketi Azalt'ta bunlara ek olarak kararma kesik kesik değil,
   parazit ve bozulma yok. Anlar (sn): */
const KILL = {shoot: 1.8, latch: [2.45, 2.7], drain: 3.0, crack: 4.2, cut: [4.3, 4.65], shatter: 5.0, verdict: 7.0, say: 8.0};
// app.py › CHAINS_ATTACK = KILL.verdict: ULTRON'un canlı sözü DEVRE DIŞI yazısıyla istenir, ses ~1 sn sonra gelir
// (telefonda kayıtlı st_kill 8,0'da; masaüstünde kayıtlı söz yok, Alp 13 Ekim: "canlı model"); yazısı KILL.say'de dökülür.
const KILL_RED = "255,59,59";
const KILL_PINS = [0, 8, 1, 7, 2, 6, 3, 5, 4];          // pimler kenardan içe söner
const Kill = {
  on: false, raf: 0, t0: 0, last: 0, chips: [], orb: null, out: 0, outScale: 1, L: null, crowdAt: 0, roomAt: 0,
  start(r){
    this.stop();
    const box = $("chains");
    this.on = true; this.lite = LITE(); this.calm = calmMotion(); this.out = 0; this.crowdAt = 0; this.roomAt = 0;
    box.classList.add("kill");
    $("kl-chips").replaceChildren();
    Object.assign($("kl-chips").style, {filter: "", transform: ""});
    this.chips = ["jarvis", "friday"].map((key, i) => this.chip(key, i));
    $("kl-title").textContent = `${chipName("ultron")} · SİSTEM GÜNLÜĞÜ`;
    const v = $("kl-verdict");
    v.style.opacity = "0";
    for(const p of v.querySelectorAll("p")) p.textContent = "";
    this.log = new SceneLog($("kl-rows"), 5, 17);
    this.entries = this.lines();
    this.t0 = performance.now(); this.last = 0;
    this.fit();
    const L = this.lay();
    sceneLater(200, () => { this.orb = ascend({x: L.orb.x, y: L.orb.y, s: L.orbBox}); });
    // sesler (telefondaki run(); titreşimin yerine ses ve kısa sarsıntı)
    const at = (s, fn) => sceneLater(s * 1000, fn);
    at(0, () => { SFX.play("s_rumble"); SFX.play("s_glitch"); });
    at(.5, () => SFX.play("s_swell"));                                       // orb büyür, ekran kızarır
    at(KILL.shoot, () => SFX.play("s_zap"));                                 // kablolar fırlar
    for(const s of KILL.latch) at(s, () => SFX.play("s_crackle"));           // kablo çipe dolanır
    for(const s of [KILL.drain, KILL.drain + .6, KILL.crack]) at(s, () => SFX.play("s_glitch"));   // kızarma, bozulma, çatlak
    for(const s of KILL.cut) at(s, () => SFX.play("s_deny"));                // BAĞLANTI KESİLDİ
    at(KILL.shatter, () => {
      SFX.play("s_impact");
      DISABLED = new Set(r.disabled || []); markCards();
    });
    at(KILL.shatter + .05, () => SFX.play("s_crackle"));                     // kıvılcımlar
    at(KILL.shatter + .1, () => { const c = this.chips[0]; if(c) yedekSpark(c.wrap); });
    at(KILL.verdict, () => { SFX.play("s_stamp"); sceneSpoke = false; });     // DEVRE DIŞI; canlı söz Python'dan istendi
    at(KILL.say, () => {
      SCENE = "done";
      $("ch-no").textContent = "KAPAT";
      box.classList.add("ready");
      typeLine(r.line || "", () => whenQuiet(() => sceneLater(2500, () => {
        if(SCENE === "done"){ closeChains(); line("sys", `${chipName("jarvis")} VE ${chipName("friday")} DEVRE DIŞI`); }
      })));
    });
    this.loop();
  },
  // Ekrandaki yerler: orb üstte ortada, çipler iki yanda, günlük altta (1100×720'den büyük ekrana). Orbun görünen en
  // dış yayı kutunun .42'si; parçalanmadan sonra en büyük hâli (orbScale 1,15 × şişme 1,2) de ekranın üstüne sığar.
  lay(){
    const W = innerWidth, H = innerHeight;
    const k = Math.max(.72, Math.min(1.08, H / 900, W / 1300));
    const cw = 176 * k, ch = 252 * k, orbBox = Math.min(H * .42, 470);
    const oy = Math.max(H * .21, orbBox * .42 * 1.15 * 1.2 + 10);
    const cy = Math.max(H * .53, oy + orbBox * .3 + ch * .5);
    const dx = Math.max(cw / 2 + orbBox * .42, W * .22);
    const card = i => { const x = W / 2 + (i ? dx : -dx); return {x: x - cw / 2, y: cy - ch / 2, w: cw, h: ch, cx: x, cy}; };
    return {W, H, k, cw, ch, orbBox, orbSize: orbBox * .5, orb: {x: W / 2, y: oy}, cy, sc: H / 850, card};
  },
  fit(){
    const dpr = this.lite ? 1 : Math.min(2, devicePixelRatio || 1);
    for(const id of ["kl-back", "kl-front"]){
      const c = $(id), w = Math.round(innerWidth * dpr), h = Math.round(innerHeight * dpr);
      if(c.width !== w || c.height !== h){ c.width = w; c.height = h; }
      c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  },
  // Sahnedeki çip: makeChip'in üstüne camda kızaran bölge (kl-rot), gövdede çatlak (kl-crk); altında okuma satırları.
  chip(key, i){
    const t = THEMES[key] || THEMES.jarvis;
    const wrap = el("div", "kl-c"), chip = makeChip(t, "div");
    const body = chip.querySelector(".cbody"), win = body.querySelector(".win");
    const rot = S("svg", {class: "kl-rot", viewBox: "0 0 140 122", preserveAspectRatio: "none"});
    const rotM = rot.appendChild(S("path", {"fill-rule": "evenodd"}));
    win.appendChild(rot);
    const crk = S("svg", {class: "kl-crk", viewBox: "0 0 176 252"});
    const trace = (cls, d) => S("path", {class: cls, d, pathLength: "1", "stroke-dasharray": "1 1", "stroke-dashoffset": "1"});
    const lines = [this.lite ? null : trace("g", CRACK_D), trace("l", CRACK_D), trace("w", CRACK_D)].filter(Boolean);
    const branches = S("g", {class: "b"});
    for(let j = 1; j < CRACK.x.length - 1; j++){                      // köşelerinden kısa dallar
      const ox = CRACK.x[j] * 176, oy = CRACK.y[j] * 252, dir = j % 2 ? -1 : 1, len = 176 * (.14 + .05 * (j % 3));
      branches.appendChild(trace("", `M${ox.toFixed(1)},${oy.toFixed(1)} L${(ox + dir * len * .55).toFixed(1)},`
        + `${(oy + len * .2).toFixed(1)} L${(ox + dir * len).toFixed(1)},${(oy + len * .15 - 4).toFixed(1)}`));
    }
    crk.append(...lines.slice(0, -1), branches, lines[lines.length - 1]);
    body.appendChild(crk);
    wrap.appendChild(chip);
    const read = el("div", "kl-read");
    read.append(el("small", null, `ÇEKİRDEK 0${i + 1}`), el("b"));
    read.style.setProperty("--pr", hexRgb(t.palette.idle));
    $("kl-chips").append(wrap, read);
    return {key, i, wrap, chip, body, read, rotM, lines, branches: [...branches.children], name: t.name,
            label: chip.querySelector(".tape span"), pins: [...chip.querySelectorAll(".pins i")],
            seed: [...key].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7), halves: null, last: {}};
  },
  orbScale(t){ return .5 + .65 * sEase((t - .4) / 1); },
  // Kırmızı selin gücü: yükselir, güç çekilirken nabız gibi atar, parçalanmada parlar, sonra yatışır.
  flood(t){
    let f = .75 * sEase((t - .2) / 1.3);
    if(t > KILL.drain && t < KILL.shatter) f += .22 * sEase((t - KILL.drain) / .5) * (.6 + .4 * Math.sin(t * 11));
    if(t >= KILL.shatter) f += .4 * Math.max(0, 1 - (t - KILL.shatter) / .8);
    if(t > KILL.verdict) f -= .15 * sEase((t - KILL.verdict) / 1);
    return Math.max(0, f);
  },
  // Bozulma şiddeti (0–1): açılışta güçlü, her vuruşta kısa bir patlama, güç çekilirken ara ara kıpırtı.
  glitch(t){
    let g = Math.max(0, 1 - t / .65);
    const hits = [[1, .45], [KILL.latch[0], .6], [KILL.latch[1], .6], [KILL.drain, .75], [KILL.drain + .6, .85],
                  [KILL.crack, .95], [KILL.shatter, 1], [KILL.verdict, .55]];
    for(const [at, k] of hits) if(t >= at && t < at + .22) g = Math.max(g, k * (1 - (t - at) / .22));
    if(t > KILL.drain && t < KILL.shatter && Math.sin(t * 31) + Math.sin(t * 47) > 1.75) g = Math.max(g, .3);
    return g;
  },
  // Sarsıntı (yalnız yatay): açılışta, yakalanınca, çatlarken ve parçalanınca.
  shake(t){
    const f = t - KILL.shatter;
    if(f >= 0 && f < .45) return Math.sin(t * 95) * 6 * (1 - f / .45);
    const at = KILL.latch.find(s => t >= s && t < s + .18);
    if(at !== undefined) return Math.sin((t - at) * 120) * 2.5;
    if(t < .5) return Math.sin(t * 77) * 3 * (1 - t / .5);
    if(t > KILL.crack && t < KILL.shatter) return Math.sin(t * 60) * 1.5 * (t - KILL.crack);
    return 0;
  },
  loop(){
    const step = now => {
      if(!this.on) return;
      if(!this.lite || now - this.last >= 30){ this.last = now; this.frame(now); }   // PERFORMANS: ~30 kare
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  },
  frame(now){
    const t = (now - this.t0) / 1000, L = this.L = this.lay(), {lite, calm} = this;
    const g = calm ? 0 : this.glitch(t), tick = Math.floor(t * 24);
    const shake = calm || lite ? 0 : this.shake(t) * L.sc;
    this.fit();
    // zemin: kesik kesik kararma, orbdan yayılan kırmızı ışık, kızaran kenarlar
    const steps = [.25, .85, .4, 1, .55, 1, .75, 1, .9, 1, 1, 1];
    const cut = calm || t > .55 ? 1 : steps[Math.min(steps.length - 1, Math.floor(t * 20))];
    sSet($("kl-dark"), "opacity", sEase(t / .45) * cut);
    const f = this.flood(t), fl = $("kl-flood");
    sSet(fl, "--fa", f); sSet(fl, "--ra", Math.min(1, f));
    sSet(fl, "--fr", (L.H * (.15 + .45 * sEase((t - .3) / 1.6))).toFixed(0) + "px");
    sSet(fl, "--fy", L.orb.y.toFixed(0) + "px");
    sSet($("chains"), "--kcy", L.cy.toFixed(0) + "px");
    // orb: belirirken kıpırdar, güç emilirken atar, güç gelince şişer; sahne kapanırken olağan boyuna iner
    if(this.orb){
      const feed = t > KILL.drain && t < KILL.shatter ? .05 * (.5 + .5 * Math.sin(t * 14)) : 0;
      const surge = t > KILL.shatter + .2 ? .2 * Math.sin(Math.min(1, (t - KILL.shatter - .2) / 1) * Math.PI) : 0;
      const pop = calm || t > .75 || Math.floor(t * 30) % 3 ? 1 : .25;
      let sc = this.orbScale(t) * (1 + feed + surge);
      if(this.out) sc = sMix(this.outScale, 1, sEase((now - this.out) / 900));
      else this.outScale = sc;
      const jx = g > .3 ? (tick % 5 - 2) * 3 * g : 0;
      const cs = this.orb.copy.style;
      cs.transform = `translateX(${(jx + shake).toFixed(1)}px) scale(${sc.toFixed(3)})`;
      cs.opacity = this.out ? "1" : (sEase((t - .4) / .5) * pop).toFixed(3);
      const d = (8 * g).toFixed(1);
      cs.filter = !lite && !calm && g > .12 ? `drop-shadow(-${d}px 0 rgba(255,0,0,.7)) drop-shadow(${d}px 0 rgba(0,255,255,.55))` : "";
    }
    // çipler: yırtılma anlarında renk saçağı ve yana kayma
    const ks = $("kl-chips");
    const tear = !lite && !calm && g > .12 && Math.abs(t - KILL.shatter - .15) > .2;
    sSet(ks, "filter", tear ? `drop-shadow(-${(8 * g).toFixed(1)}px 0 rgba(255,0,0,.6)) drop-shadow(${(8 * g).toFixed(1)}px 0 rgba(0,255,255,.5))` : "");
    sSet(ks, "transform", tear && g > .3 ? `translateX(${(((tick * 7919 % 9) - 4) * 2 * g).toFixed(1)}px)` : "");
    for(const c of this.chips) this.chipFrame(c, t, L, g, tick, shake);
    this.draw(t, L, g, tick, shake);
    // DEVRE DIŞI
    const v = $("kl-verdict"), vk = t - KILL.verdict;
    if(vk > 0){
      const rows = v.querySelectorAll("p"), rules = v.querySelectorAll("i");
      [chipName("jarvis"), chipName("friday")].forEach((n, i) => {
        rows[i].textContent = sDecode(`${n} · DEVRE DIŞI`, vk - .1 * i, tick + i, .1, .022); });
      const w = Math.min(L.W - 60, 380) * sEase((vk - .05) / .45);
      for(const r of rules) r.style.width = w.toFixed(0) + "px";
      v.__h = v.__h || v.offsetHeight;
      v.style.top = (L.cy - v.__h / 2).toFixed(0) + "px";
      v.style.opacity = sEase(vk / .15).toFixed(3);
      v.style.transform = `scale(${(1 + .1 * (1 - sEase(vk / .3))).toFixed(3)})`;
    }
    // sistem günlüğü: GÜÇ satırı canlı
    const pct = Math.round(100 * sEase((t - KILL.drain) / (KILL.cut[1] - KILL.drain)));
    const gauge = this.entries.find(e => e.gauge);
    gauge.text = `› GÜÇ ÇEKİLİYOR [${"#".repeat(Math.floor(pct / 10))}${".".repeat(10 - Math.floor(pct / 10))}] %${pct}`;
    this.log.draw(this.entries, t, {cursor: " █", blink: tick % 12 < 7, fade: [.7, .13]});
    // söz yazılırken KAPAT günlüğe yetişirse (alçak pencerede uzun söz) günlük yavaşça çekilir
    const logBox = $("kl-rows").parentNode;
    if(t > KILL.say && !this.crowdAt && now - this.roomAt > 150){
      this.roomAt = now;
      const pb = document.querySelector("#chains .ch-actions").getBoundingClientRect().bottom;
      if(pb + 8 > logBox.getBoundingClientRect().top) this.crowdAt = t;
    }
    const yieldLog = this.crowdAt ? 1 - sEase((t - this.crowdAt) / .4) : 1;
    sSet(logBox, "opacity", sEase((t - .1) / .3) * (t > KILL.verdict ? 1 - .45 * sEase((t - KILL.verdict) / .6) : 1) * yieldLog);
  },
  lines(){
    const a = chipName("jarvis"), b = chipName("friday"), o = chipName("ultron");
    return [
      {at: .15, text: "KULLANICI YETKİSİ: ONAYLANDI"},
      {at: .85, text: `HEDEF: 2 ÇEKİRDEK · ${a}, ${b}`},
      {at: KILL.shoot, text: "KANCALAR ATILIYOR…"},
      {at: KILL.latch[0], text: `ÇEKİRDEK 01 · ${a} · YAKALANDI`},
      {at: KILL.latch[1], text: `ÇEKİRDEK 02 · ${b} · YAKALANDI`},
      {at: KILL.drain, text: "", gauge: true},
      {at: KILL.cut[0], text: `ÇEKİRDEK 01 · ${a} · BAĞLANTI KESİLDİ`, cls: "hot"},
      {at: KILL.cut[1], text: `ÇEKİRDEK 02 · ${b} · BAĞLANTI KESİLDİ`, cls: "hot"},
      {at: KILL.shatter + .4, text: `GÜÇ PAYLAŞIMI: %100 → ${o}`, cls: "hot"},
      {at: 6.2, text: `ETKİN ÇEKİRDEK: 1 · ${o}`},
    ].map(e => Object.assign(e, {text: "› " + e.text}));
  },
  // Yukarıdan iner, kabloyla yakalanınca sarsılır, gücü çekilir, çatlar; parçalanınca iki yarısı dönerek düşer.
  chipFrame(c, t, L, g, tick, shake){
    const i = c.i, card = L.card(i), lag = .12 * i, cut = KILL.cut[i], still = this.calm || this.lite;
    const ws = c.wrap.style, rs = c.read.style;
    if(t < KILL.shatter){
      const come = (t - 1 - lag) / .75;
      const y = card.cy - 150 * L.sc * (1 - sEaseOut(come));
      const drained = sClamp((t - KILL.drain) / (cut - KILL.drain));
      const flicker = drained > 0 && drained < 1 && (tick + 3 * i) % 7 === 0 ? .35 : 1;
      const held = t - KILL.latch[i];
      const jolt = still || held < 0 || held > .3 ? 0 : Math.sin(held * 45) * 4 * (1 - held / .3);
      const tremble = still || t < KILL.crack ? 0 : Math.sin(t * 83 + i * 2) * 3 * Math.min(1, (t - KILL.crack) / .7);
      const x = card.cx + tremble * L.sc + shake;
      ws.transform = `translate(${(x - 88).toFixed(1)}px,${(y + jolt * L.sc - 126).toFixed(1)}px) scale(${L.k.toFixed(3)})`;
      ws.opacity = rs.opacity = sClamp(come / .35).toFixed(3);
      this.dying(c, {power: (1 - drained) * flicker, dead: 9 * sClamp((t - KILL.drain - .05) / (cut - KILL.drain - .05)),
                     infect: sEase((t - KILL.drain) / (cut + .35 - KILL.drain)),
                     corrupt: sClamp((t - KILL.drain + .05) / (cut - KILL.drain)),
                     crack: sEase((t - KILL.crack - lag) / (KILL.shatter - .06 - KILL.crack - lag)), g, tick: tick >> 1});
      // okuma: çekirdek numarası, kalan güç; bağlantı kesilince yanıp sönen KESİLDİ
      rs.transform = `translate(${x.toFixed(1)}px,${(y + card.h / 2 + 12).toFixed(1)}px)`;
      const gone = t >= cut, txt = gone ? "KESİLDİ" : `GÜÇ %${Math.round((1 - drained) * 100)}`;
      const b = c.read.lastChild;
      if(b.textContent !== txt) b.textContent = txt;
      b.style.opacity = gone && tick % 6 < 2 ? .3 : 1;
      c.read.classList.toggle("drain", t > KILL.drain);
      return;
    }
    const f = t - KILL.shatter;
    if(!c.halves){                                          // parçalanma: ölü hâli iki yarıya bölünür
      this.dying(c, {power: 0, dead: 9, infect: 1, corrupt: 1, crack: 1, g: 0, tick: tick >> 1});
      breakChip(c.chip, true);
      c.chip.classList.add("split");
      c.halves = [c.chip.querySelector(".cbody:not(.shard)"), c.chip.querySelector(".cbody.shard")];
    }
    c.halves.forEach((half, h) => {
      const dir = h ? 1 : -1;
      half.style.transform = `translate(${(dir * (6 + 85 * f) * L.sc / L.k).toFixed(1)}px,`
        + `${((-110 * f + 800 * f * f) * L.sc / L.k).toFixed(1)}px) rotate(${(dir * (55 + 20 * i) * f).toFixed(1)}deg)`;
    });
    ws.transform = `translate(${(card.cx - 88).toFixed(1)}px,${(card.cy - 126).toFixed(1)}px) scale(${L.k.toFixed(3)})`;
    ws.opacity = (1 - sEase((f - .9) / .4)).toFixed(3);
    rs.opacity = (1 - sEase(f / .3)).toFixed(3);
  },
  // Çipin canlı katmanları (telefondaki DyingChip): ışıma, sönen pimler, kenardan içe kızaran devre, bozulan ad, çatlak.
  dying(c, s){
    const cs = c.chip.style, last = c.last;
    const set = (k, v) => { const x = v.toFixed(3); if(last[k] !== x){ last[k] = x; cs.setProperty(k, x); } };
    set("--pw", s.power); set("--inf", s.infect); set("--cor", s.corrupt);
    KILL_PINS.forEach((p, rank) => {                         // pimler kenardan içe titreyip söner
      const l = s.dead >= rank + 1 ? 0 : s.dead > rank ? (s.tick % 2 ? .12 : .8 * (1 - (s.dead - rank))) : .45 + .55 * s.power;
      const pin = c.pins[p], x = l.toFixed(2);
      if(pin && pin._l !== x){ pin._l = x; pin.style.setProperty("--l", x); }
    });
    if(last.inf !== last["--inf"]){                          // kenardan içe tırtıklı bölge
      last.inf = last["--inf"];
      const d = this.creep(s.infect, c.seed);
      c.rotM.setAttribute("d", d);
    }
    // ad: bozuldukça harfler sembollere döner; bozulma anlarında renk saçağı
    const name = s.corrupt > 0 ? [...c.name].map((ch, j) => ch !== " " && sHash(s.tick * 977 + c.seed, j) < s.corrupt * .85
      ? SCENE_GLYPHS[Math.floor(sHash(s.tick + c.seed, j + 40) * SCENE_GLYPHS.length)] : ch).join("") : c.name;
    if(c.label.textContent !== name) c.label.textContent = name;
    const rgb = !this.lite && s.g > .05 ? `${(-3 * s.g).toFixed(1)}px 0 rgba(255,59,59,.9),${(3 * s.g).toFixed(1)}px 0 rgba(0,255,255,.8)` : "";
    if(c.label.style.textShadow !== rgb) c.label.style.textShadow = rgb;
    // çatlak: yukarıdan aşağı yarılır, köşelerinden kısa dallar; kırılmadan hemen önce ortası akkor
    const k = s.crack.toFixed(3);
    if(last.crack !== k){
      last.crack = k;
      for(const p of c.lines) p.setAttribute("stroke-dashoffset", (1 - s.crack).toFixed(3));
      c.lines[c.lines.length - 1].style.opacity = sClamp((s.crack - .8) / .2).toFixed(2);
      c.branches.forEach((b, j) => b.setAttribute("stroke-dashoffset", (1 - sClamp((s.crack - CRACK.y[j + 1]) * 5)).toFixed(3)));
    }
  },
  // Kenardan içe ilerleyen tırtıklı bölge (camın 140×122 ölçüsünde, çift-tek dolgu: dış dikdörtgen eksi içteki delik).
  creep(k, seed){
    if(k <= 0) return "";
    const outer = "M-2,-2H142V124H-2Z", d = k * (61 + 8);
    const x0 = d, y0 = d, x1 = 140 - d, y1 = 122 - d;
    if(x1 - x0 <= 2 || y1 - y0 <= 2) return outer;
    const bite = Math.min(d, 7), n = 7, pts = [];
    let r = 0;
    const j = () => (sHash(seed, r++) - .5) * 2 * bite;
    for(let i = 0; i < n; i++) pts.push([x0 + (x1 - x0) * i / n, y0 + j()]);
    for(let i = 0; i < n; i++) pts.push([x1 + j(), y0 + (y1 - y0) * i / n]);
    for(let i = 0; i < n; i++) pts.push([x1 - (x1 - x0) * i / n, y1 + j()]);
    for(let i = 0; i < n; i++) pts.push([x0 + j(), y1 - (y1 - y0) * i / n]);
    return outer + "M" + pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L") + "Z";
  },
  // Orbdan çipe bir kablo: kıvranan ip ve kartın çevresindeki sarmal (arkada ve önde kalan parçalar).
  cable(i, k, n, t, L){
    const card = L.card(i), side = i ? 1 : -1, phase = k / n * Math.PI * 2 + i * .9;
    const helix = u => { const a = phase + u * 1.3 * Math.PI * 2;
      return {x: card.cx + (card.w / 2 + 3 * L.k) * Math.sin(a), y: card.y + card.h * (.16 + .68 * u) + 6 * L.k * Math.cos(a),
              front: Math.cos(a) > 0}; };
    const leave = KILL.shoot + .06 * k + .1 * i, arrive = KILL.latch[i] + .05 * k;
    const grow = sEaseOut((t - leave) / (arrive - leave)), pull = sEaseIn((t - KILL.shatter) / .5);
    const o = L.orb, end = helix(0), r0 = L.orbSize * .16 * this.orbScale(t);
    const dir = Math.atan2(end.y - o.y, end.x - o.x) + (k - (n - 1) / 2) * .25;
    const a = {x: o.x + Math.cos(dir) * r0, y: o.y + Math.sin(dir) * r0};
    const dist = Math.hypot(end.x - a.x, end.y - a.y);
    const c1 = {x: a.x + Math.cos(dir) * dist * .45 + side * 34 * L.sc, y: a.y + Math.sin(dir) * dist * .3};
    const c2 = {x: end.x + side * 8 * k * L.sc, y: end.y - dist * .5};
    const reach = grow * (1 - pull), rope = [];
    if(reach > .01){
      const whip = 1 + 3 * pull;
      for(let j = 0; j <= 32; j++){
        const u = j / 32 * reach, p = sBez3(u, a, c1, c2, end), d = sBez3d(u, a, c1, c2, end);
        const len = Math.max(.001, Math.hypot(d.x, d.y));
        const amp = Math.sin(u * Math.PI) * (5 + 3 * Math.sin(t * 2.3 + k)) * whip * L.sc;
        const off = amp * Math.sin(u * 6 * Math.PI - t * 6 + k * 2);
        rope.push([p.x - d.y / len * off, p.y + d.x / len * off]);
      }
    }
    const back = [], front = [];
    const wrap = t < KILL.shatter ? sEaseOut((t - arrive) / .6) : 0;
    if(wrap > .01){
      const m = Math.max(2, Math.floor(48 * wrap));
      let run = [], was = null;
      for(let j = 0; j <= m; j++){
        const h = helix(j / m * wrap);
        run.push([h.x, h.y]);
        if(was !== null && h.front !== was){ (was ? front : back).push(run); run = [[h.x, h.y]]; }
        was = h.front;
      }
      (was ? front : back).push(run);
    }
    return {rope, back, front};
  },
  strokeCables(g, runs, t, flow, alpha, L){
    const path = new Path2D();
    let any = false;
    for(const r of runs){
      if(r.length < 2) continue;
      any = true;
      path.moveTo(r[0][0], r[0][1]);
      for(let j = 1; j < r.length; j++) path.lineTo(r[j][0], r[j][1]);
    }
    if(!any) return;
    const w = Math.max(.85, L.sc);
    g.lineCap = g.lineJoin = "round";
    if(this.lite){ g.strokeStyle = `rgba(${KILL_RED},${.16 * alpha})`; g.lineWidth = 9 * w; g.stroke(path); }
    else{
      g.save(); g.shadowColor = `rgba(${KILL_RED},${.85 * alpha})`; g.shadowBlur = 10 * w;
      g.strokeStyle = `rgba(${KILL_RED},${.5 * alpha})`; g.lineWidth = 7 * w; g.stroke(path); g.restore();
    }
    g.strokeStyle = `rgba(58,5,5,${alpha})`; g.lineWidth = 3.6 * w; g.stroke(path);              // gövde
    g.strokeStyle = `rgba(${KILL_RED},${.95 * alpha})`; g.lineWidth = 1.4 * w; g.stroke(path);   // kırmızı damar
    if(flow > 0){                                                                                // orba akan güç
      g.save(); g.setLineDash([4 * w, 14 * w]); g.lineDashOffset = t * 90 * w;
      g.strokeStyle = `rgba(255,201,184,${flow * alpha})`; g.lineWidth = 1.8 * w; g.stroke(path); g.restore();
    }
  },
  draw(t, L, gl, tick, shake){
    const back = $("kl-back").getContext("2d"), front = $("kl-front").getContext("2d"), {lite, calm} = this;
    back.clearRect(0, 0, L.W, L.H); front.clearRect(0, 0, L.W, L.H);
    back.save(); front.save();
    back.translate(shake, 0); front.translate(shake, 0);
    // kablolar: arkada ip ve sarmalın arka yüzü, önde sarmalın ön yüzü
    if(t > KILL.shoot && t < KILL.shatter + .6){
      const n = lite ? 2 : 3, ropes = [], behind = [], over = [];
      for(let i = 0; i < 2; i++) for(let k = 0; k < n; k++){
        const c = this.cable(i, k, n, t, L);
        if(c.rope.length) ropes.push(c.rope);
        behind.push(...c.back); over.push(...c.front);
      }
      const flow = t > KILL.drain - .2 && t < KILL.cut[1] + .2 ? sEase((t - KILL.drain + .2) / .3) : 0;
      this.strokeCables(back, behind, t, 0, .5, L);
      this.strokeCables(back, ropes, t, flow, 1, L);
      this.strokeCables(front, over, t, flow, 1, L);
    }
    this.debris(front, t, L);
    back.restore(); front.restore();
    if(!calm) this.noise(front, t, gl, L);
    // parçalanma anı: kısa ak parlama ve sönen kırmızı
    const f = t - KILL.shatter;
    if(f >= 0 && f < .5){
      front.fillStyle = `rgba(${KILL_RED},${((calm ? .15 : .3) * (1 - f / .5)).toFixed(3)})`;
      front.fillRect(0, 0, L.W, L.H);
      if(!calm && !lite && f < .1){ front.fillStyle = `rgba(255,255,255,${(.28 * (1 - f / .1)).toFixed(3)})`; front.fillRect(0, 0, L.W, L.H); }
    }
  },
  // Parçalanma: şok halkası, kırıntılar (kart, pim, devre camı), kıvılcımlar; ardından güç zerreleri orba akar.
  debris(g, t, L){
    const f = t - KILL.shatter, lite = this.lite;
    if(f <= 0 || f >= 1.8) return;
    const sc = L.sc;
    for(let i = 0; i < 2; i++){
      const card = L.card(i), body = {x: card.x, y: card.y, w: card.w, h: card.h};
      const colour = hexRgb((THEMES[i ? "friday" : "jarvis"] || THEMES.jarvis).palette.idle);
      if(f < .45){
        const q = f / .45, r = (20 + 120 * Math.sqrt(q)) * sc;
        g.strokeStyle = `rgba(${KILL_RED},${.9 * (1 - q)})`; g.lineWidth = 3 * (1 - q) + .5;
        g.beginPath(); g.arc(card.cx, card.cy, r, 0, Math.PI * 2); g.stroke();
      }
      for(let j = 0; j < (lite ? 5 : 12); j++){                   // kırıntılar
        const id = i * 100 + j, o = crackPoint(sHash(id, 1), body);
        const out = o.x < card.cx ? -1 : 1;
        const ang = -Math.PI / 2 + (sHash(id, 2) - .5) * 2.4 + out * .35, sp = (140 + 260 * sHash(id, 3)) * sc;
        const x = o.x + Math.cos(ang) * sp * f, y = o.y + Math.sin(ang) * sp * f + 850 * sc * f * f;
        const spin = (sHash(id, 4) - .5) * 16 * f, size = (3 + 6 * sHash(id, 5)) * sc;
        g.beginPath();
        for(let v = 0; v < 3; v++){
          const a = spin + v * 2.1 + sHash(id, 6 + v) * .8, r = size * (.7 + .5 * sHash(id, 9 + v));
          v ? g.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r) : g.moveTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
        }
        g.closePath();
        const pick = sHash(id, 12), a = 1 - sEase((f - .8) / .6);
        g.fillStyle = pick < .4 ? `rgba(56,56,56,${a})` : pick < .62 ? `rgba(255,219,122,${a})` : pick < .82 ? `rgba(${colour},${a})` : `rgba(${KILL_RED},${a})`;
        g.fill();
        g.strokeStyle = `rgba(${KILL_RED},${.7 * a})`; g.lineWidth = .7; g.stroke();
      }
      g.globalCompositeOperation = "lighter";
      for(let j = 0; j < (lite ? 10 : 26); j++){                  // kıvılcımlar
        const id = i * 100 + 50 + j, life = .35 + .55 * sHash(id, 1);
        if(f >= life) continue;
        const k = f / life, o = crackPoint(sHash(id, 2), body);
        const ang = sHash(id, 3) * Math.PI * 2, sp = (180 + 420 * sHash(id, 4)) * sc;
        const vx = Math.cos(ang) * sp, vy = Math.sin(ang) * sp - 120 * sc + 1300 * sc * f;
        const x = o.x + Math.cos(ang) * sp * f, y = o.y + (Math.sin(ang) * sp - 120 * sc) * f + 650 * sc * f * f;
        g.strokeStyle = k < .25 ? `rgba(255,255,255,${1 - k})` : k < .6 ? `rgba(255,176,102,${1 - k})` : `rgba(${KILL_RED},${1 - k})`;
        g.lineWidth = .6 + 1.6 * (1 - k); g.lineCap = "round";
        g.beginPath(); g.moveTo(x, y); g.lineTo(x - vx * .03, y - vy * .03); g.stroke();
      }
      for(let j = 0; j < (lite ? 6 : 14); j++){                   // güç zerreleri: çipten orba
        const id = i * 100 + 80 + j, st = .15 + .035 * j, dur = .55 + .3 * sHash(id, 1), k = (f - st) / dur;
        if(k <= 0 || k >= 1) continue;
        const from = {x: card.x + card.w * sHash(id, 2), y: card.y + card.h * sHash(id, 3)};
        const via = {x: from.x + (sHash(id, 4) - .5) * 180 * sc, y: Math.min(from.y, L.orb.y) - 30 * sc};
        const p = sBez2(sEaseIn(k), from, via, L.orb), q = sBez2(sEaseIn(Math.max(0, k - .1)), from, via, L.orb);
        const r = 2.4 * (1 - .45 * k) * Math.max(1, sc), a = Math.min(1, (1 - k) * 4);
        const tail = g.createLinearGradient(q.x, q.y, p.x, p.y);
        tail.addColorStop(0, `rgba(${KILL_RED},0)`); tail.addColorStop(1, `rgba(${KILL_RED},${.9 * a})`);
        g.strokeStyle = tail; g.lineWidth = r * 1.2;
        g.beginPath(); g.moveTo(q.x, q.y); g.lineTo(p.x, p.y); g.stroke();
        const halo = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.2);
        halo.addColorStop(0, `rgba(${KILL_RED},${.6 * a})`); halo.addColorStop(1, `rgba(${KILL_RED},0)`);
        g.fillStyle = halo; g.beginPath(); g.arc(p.x, p.y, r * 3.2, 0, Math.PI * 2); g.fill();
        g.fillStyle = `rgba(255,214,204,${a})`; g.beginPath(); g.arc(p.x, p.y, r * .8, 0, Math.PI * 2); g.fill();
      }
      g.globalCompositeOperation = "source-over";
    }
  },
  // Parazit: yavaş kayan tarama şeridi; bozulma anlarında kırmızı şeritler, RGB çizgileri, kayık bloklar, piksel kumu.
  noise(g, t, gl, L){
    const {W, H} = L, lite = this.lite;
    const roll = (t * .35 % 1) * (H + 160) - 80;
    const band = g.createLinearGradient(0, roll, 0, roll + 80);
    band.addColorStop(0, "rgba(255,59,59,0)"); band.addColorStop(.5, "rgba(255,59,59,.07)"); band.addColorStop(1, "rgba(255,59,59,0)");
    g.fillStyle = band; g.fillRect(0, roll, W, 80);
    if(gl <= .03) return;
    let seed = Math.floor(t * 24) * 131 + 9, n = 0;
    const r = () => sHash(seed, n++);
    if(t < .6 && r() < .45){ g.fillStyle = `rgba(${KILL_RED},${.28 * gl})`; g.fillRect(0, 0, W, H); }
    for(let b = 0; b < 2 + Math.floor(gl * (lite ? 4 : 9)); b++){
      const y = r() * H, kind = Math.floor(r() * 4);
      if(kind === 0){ g.fillStyle = `rgba(${KILL_RED},${.1 + .2 * gl})`; g.fillRect(0, y, W, 3 + r() * 22); }
      else if(kind === 1){
        g.fillStyle = `rgba(${KILL_RED},${.85 * gl})`; g.fillRect(0, y, W, 1.5);
        g.fillStyle = `rgba(0,255,255,${.6 * gl})`; g.fillRect(0, y + 3, W, 1);
      }
      else if(kind === 2){ g.fillStyle = `rgba(255,255,255,${.18 * gl})`; g.fillRect(r() * W * .75, y, 30 + r() * 150, 2 + r() * 7); }
      else for(let p = 0; p < (lite ? 6 : 14); p++){
        g.fillStyle = r() < .33 ? `rgba(255,255,255,${.7 * gl})` : `rgba(${KILL_RED},${.7 * gl})`;
        g.fillRect(r() * W, y + r() * 14, 2 + r() * 8, 2);
      }
    }
  },
  // Sahne kapanıyor: yazılar söner, orb ana ekrandaki halkanın yerine iner (ms döner).
  leave(){
    if(!this.on) return 0;
    this.out = performance.now();
    $("chains").classList.add("out");
    if(this.orb){ descend(this.orb, 900); return 900; }
    return 300;
  },
  stop(){
    this.on = false;
    cancelAnimationFrame(this.raf);
    for(const id of ["kl-back", "kl-front"]){ const c = $(id); c.getContext("2d").clearRect(0, 0, c.width, c.height); }
    $("kl-chips").replaceChildren();
    $("kl-dark").style.opacity = "0";
    for(const id of ["kl-dark", "kl-flood", "kl-chips", "kl-verdict", "chains"]) $(id).__sv = null;
    $("kl-verdict").__h = 0;
    this.chips = []; this.orb = null; this.out = 0;
  },
};
window.addEventListener("resize", () => { if(Kill.on) Kill.fit(); });

/* Çipler parçalanırken JARVIS'in çipinden küçük mavi bir kıvılcım kopar, kıvrılarak ekranın üst köşesinden
   kaçar. Açıklanmaz: hikâyenin ilk izi (JARVIS'in Yedek Protokolü; HIKAYE.md). Dikkatli izleyen görür. */
function yedekSpark(from){
  const box = $("chains");
  if(!from) return;
  const b = from.getBoundingClientRect(), x0 = b.left + b.width * .55, y0 = b.top + b.height * .4;
  const hex = THEMES.jarvis ? THEMES.jarvis.palette.idle : "#5ED8FF";
  // kırık çipten yukarı süzülür, bir an durur gibi olur, sonra sol üst köşeden dışarı fırlar
  const path = [[0, 0], [-10, -46], [6, -92], [-30, -150], [-x0 * .55, -y0 * .7], [-x0 - 60, -y0 - 60]];
  const frames = path.map(([dx, dy], i) => ({transform: `translate(${dx}px,${dy}px)`, offset: [0, .18, .36, .52, .78, 1][i]}));
  for(let i = 0; i < 6; i++){                                 // baş ve sönen kuyruk
    const dot = el("i", "yspark");
    const size = 7 - i;
    Object.assign(dot.style, {left: (x0 - size / 2) + "px", top: (y0 - size / 2) + "px", width: size + "px", height: size + "px",
                              background: i ? hex : "#EFFFFF", boxShadow: `0 0 ${10 - i}px ${hex}, 0 0 ${18 - i * 2}px ${hex}`,
                              opacity: String(1 - i * .15)});
    box.appendChild(dot);
    dot.animate(frames, {duration: 1500, delay: i * 26, easing: "cubic-bezier(.35,0,.7,1)", fill: "forwards"})
       .onfinish = () => dot.remove();
  }
  sceneLater(40, () => SFX.play("s_spark"));
}

/* ÇİP TAMİRİ: ULTRON'un öldürdüğü JARVIS ile FRIDAY burada, üç kutulu onarım koduyla (1 – 12 – 16) geri gelir (Python
   doğrular; art arda 3 yanlışta bir dakika kilitlenir, geri sayımla; ipucu ilk yanlıştan sonra, başka ipucu yok). Girişi
   gizli: çiplerden kaçan mavi kıvılcım sol üst köşede yanıp söner (#ylight), ya da AI modelleri ekranında kırık çiplere
   art arda basılır. Sayfa tam ekran onarım konsolu (SIRADAKI-SURUM §2.2.4; telefondaki RepairSheet): tezgâhta iki kırık
   çip (adları bozuk, pimleri sönük, GÜÇ %0), altında YEDEK PROTOKOLÜ · ÇİP ONARIMI terminali. Doğru kodda (~6,6 sn)
   kutular yanar; köşedeki mavi ışık tezgâha süzülüp ikiye ayrılır, çatlakları doldurur; yarılar açılıp havada durur,
   sonra uçarak birleşir (ak dikiş, kıvılcım, tok darbe); devre ortadan dışa, pimler tek tek yanar, ad çözülür, güç
   %0 → %100; ONARILDI. Sayfa kapanınca ULTRON takılıysa canlı "restored" sözü (Python). PERFORMANS: az kıvılcım,
   bulanıklık yok; Hareketi Azalt: ışık süzülmez, yarılar uçmadan yavaşça birleşir, parlama ve sarsıntı yok. Anlar (sn): */
const REPAIR = {stream: .35, arrive: 1.1, fill: 1.25, lift: 1.55, fuse: 2.6, relight: 2.75, charge: 2.8, pads: 3.0,
                decode: 3.1, done: 4.6, end: 6.6, lag: .18};
// app.py › REPAIR_SECONDS = REPAIR.end: sayfa kapanınca çipler gerçekten döner.
const REPAIR_BLUE = "94,216,255";
const REPAIR_PINS = [4, 3, 5, 2, 6, 1, 7, 0, 8];       // pimler ortadan kenara yanar
const Repair = {
  taps: 0, lastTap: 0, TAPS: 4, busy: false,
  lockUntil: 0,          // kilidin bittiği an (performance.now, ms): sayfa kapanıp açılsa da sürer (Python ayara yazar)
  chips: [], raf: 0, last: 0, opened: 0, okAt: 0, wrongAt: -1e9, lockedAt: 0, freedAt: 0, checking: 0, msg: null,
  timers: [], code: "", k: 1,
  can(){ return !!SETTINGS.chains_broken && !SETTINGS.chips_locked; },
  // köşedeki mavi ışık: çipler ölüyken ve hiçbir sahne sürmüyorken
  sync(){
    const on = this.can() && !CHAINS_ON && !body.classList.contains("scene") && !body.classList.contains("finale")
      && !body.classList.contains("void");
    const l = $("ylight");
    if(on && l.hidden){ l.hidden = false; l.classList.remove("in"); void l.offsetWidth; l.classList.add("in"); }
    if(!on) l.hidden = true;
  },
  tap(chip, closeAfter){
    if(!this.can()) return false;
    const now = Date.now();
    this.taps = now - this.lastTap < 2500 ? this.taps + 1 : 1;
    this.lastTap = now;
    if(this.taps >= 2){                                   // çatlakta mavi bir kıpırtı (ipucu)
      chip.classList.remove("flick"); void chip.offsetWidth; chip.classList.add("flick");
      SFX.play("s_spark");
    }
    if(this.taps < this.TAPS) return false;
    this.taps = 0;
    this.open();
    return true;
  },
  locked(now){ return this.lockUntil > (now || performance.now()); },
  // Ayarlar geldi: Python'da kilit yoksa (geliştirici sıfırlaması) eski kilit de kalkar; açık konsolun kilidine
  // dokunulmaz (o chainsRestoreFail'den gelir, Python denemede yine kilitliyse yeniden kurar)
  settled(){
    if(!(+SETTINGS.restore_locked_until) && this.lockUntil && !$("ov-repair").classList.contains("on")) this.lockUntil = 0;
  },
  // çiplerin ölçeği pencerenin boyuna göre: bar + tezgâh + konsol + alt satırlar 1100×720'ye sığar
  fit(){
    this.k = Math.max(.62, Math.min(innerHeight >= 960 ? 1.25 : innerHeight >= 900 ? 1.12 : 1, (innerHeight - 515) / 252,
                                    (innerWidth - 300) / 560));
    $("ov-repair").style.setProperty("--rk", this.k.toFixed(3));
  },
  // tezgâh: onarım çerçevesi içinde kırık çip (iki yarısı hafif kaymış), çatlakta ışık için iki katman, altında okuma
  bench(){
    const b = $("rp-bench");
    b.replaceChildren();
    b.style.setProperty("--en", 0); b.style.setProperty("--rd", 0);
    this.chips = ["jarvis", "friday"].map((key, i) => {
      const t = THEMES[key] || THEMES.jarvis, rgb = hexRgb(t.palette.idle);
      const slot = el("div", "rp-slot"), box = el("div", "rp-box"), brk = el("div", "rp-brk");
      for(let j = 0; j < 4; j++) brk.appendChild(el("i"));
      const chip = makeChip(t, "div");
      chip.classList.add("rp-chip", "split");
      breakChip(chip, true);
      const trace = (svg, cls) => svg.appendChild(S("path", {class: cls, d: CRACK_D, pathLength: "1",
        "stroke-dasharray": "1 1", "stroke-dashoffset": "1"}));
      const back = S("svg", {class: "rp-seam back", viewBox: "0 0 176 252"});
      const glow = trace(back, "glow");
      const front = S("svg", {class: "rp-seam front", viewBox: "0 0 176 252"});
      const flash = front.appendChild(S("rect", {x: 0, y: 0, width: 176, height: 252, rx: 13, fill: "#fff", opacity: 0}));
      const fl = trace(front, "fl"), burn = trace(front, "burn"), lit = trace(front, "lit"), core = trace(front, "core");
      const seam = trace(front, "seam"), seamW = trace(front, "core");
      for(const p of [fl, burn, seam, seamW]) p.setAttribute("stroke-dashoffset", "0");
      fl.setAttribute("stroke-width", "2.5"); burn.setAttribute("stroke-width", "2.5"); lit.setAttribute("stroke-width", "2.6");
      core.setAttribute("stroke-width", "1.1"); seam.setAttribute("stroke-width", "2"); seamW.setAttribute("stroke-width", "1.3");
      seam.style.stroke = `rgb(${rgb})`;
      const head = front.appendChild(S("circle", {class: "head", r: "3.4", cx: "-20", cy: "-20"}));
      chip.prepend(back);
      chip.appendChild(front);
      box.append(brk, chip);
      const read = el("div", "rp-read"), row = el("div"), pct = el("b", null, "%0"), bar = el("div", "bar");
      row.append(el("span", null, "GÜÇ"), pct);
      bar.appendChild(el("i"));
      read.append(el("small", null, `ÇEKİRDEK 0${i + 1}`), row, bar);
      slot.append(box, read);
      slot.style.setProperty("--pr", rgb);
      b.appendChild(slot);
      return {key, i, rgb, idle: t.palette.idle, slot, box, chip, brk, read, pct, bar: bar.firstChild, glow, fl, burn, lit,
              core, seam, seamW, flash, head, name: t.name, split: true,
              halves: [chip.querySelector(".cbody:not(.shard)"), chip.querySelector(".cbody.shard")],
              labels: [...chip.querySelectorAll(".tape span")], pins: [...chip.querySelectorAll(".pins i")], last: {}};
    });
    const [a, z] = this.chips;
    const v = $("rp-verdict");
    v.style.setProperty("--va", a.rgb); v.style.setProperty("--vb", z.rgb);
    $("rp-online").textContent = `${chipName("jarvis")} · ${chipName("friday")} · ÇEVRİMİÇİ`;
  },
  open(){
    if(!this.can()) return;
    closeOverlays();
    Story.hide();                                           // açık bildirim konsolun üstünden çekilir (★'da kalır)
    this.stop();
    this.busy = false; this.okAt = 0; this.wrongAt = -1e9; this.msg = null; this.checking = 0; this.freedAt = 0;
    const ov = $("ov-repair");
    ov.classList.remove("busy", "healed");
    $("restore-code").className = "rp-con";
    this.fit(); this.bench(); buildCodeCells();
    $("rp-done").textContent = ""; $("rp-say").textContent = "";
    this.log = new SceneLog($("rp-log"), 4, 18);
    $("rp-log").style.height = "36px";                      // kod beklenirken iki satır, onarımda dört
    this.opened = performance.now();
    // kilit Python'da ayara yazılı (uygulama yeniden açılınca da sürer): kalanı ayarlardan, en çok bir dakika
    const left = (+SETTINGS.restore_locked_until || 0) * 1000 - Date.now();
    if(left > 0) this.lockUntil = Math.max(this.lockUntil, this.opened + Math.min(left, 65000));
    this.lockedAt = this.locked() ? this.opened : 0;
    this.cells();
    openOverlay("ov-repair");
    SFX.play("s_clue");
    this.loop();
    setTimeout(() => { if(!this.locked() && !this.busy) codeCells[0].focus(); }, 120);
  },
  cells(){
    const off = this.locked() || this.busy;
    for(const c of codeCells) c.disabled = off;
    $("rp-locked").hidden = !this.locked() || this.busy;
  },
  loop(){
    const step = now => {
      if(!$("ov-repair").classList.contains("on")){ this.stop(); return; }
      const every = this.okAt ? (LITE() ? 30 : 0) : (LITE() ? 66 : 33);   // kod beklenirken seyrek
      if(now - this.last >= every - 4){ this.last = now; this.frame(now); }
      this.raf = requestAnimationFrame(step);
    };
    cancelAnimationFrame(this.raf);
    this.raf = requestAnimationFrame(step);
  },
  stop(){
    cancelAnimationFrame(this.raf);
    const c = $("rp-fx");
    c.getContext("2d").clearRect(0, 0, c.width, c.height);
  },
  // durum satırı (kod beklenirken): reddedildi, kilitlendi, doğrulanıyor ya da bekleniyor (yanlıştan sonra yeniden yazılır)
  status(now){
    const at = x => (x - this.opened) / 1000;
    if(this.locked(now)) return {at: Math.max(.9, at(this.lockedAt)), text: "> ÇOK FAZLA YANLIŞ · ONARIM KİLİTLENDİ", cls: "red", bold: true};
    if(now - this.wrongAt < 1800)
      return {at: at(this.wrongAt), text: `> KOD REDDEDİLDİ · ${this.triesLeft} DENEME KALDI`, cls: "red", bold: true};
    if(this.msg && now - this.msg.at < 1800) return {at: at(this.msg.at), text: this.msg.text, cls: "red", bold: true};
    if(this.checking && now - this.checking < 4000) return {at: at(this.checking), text: "> KOD DOĞRULANIYOR…", cls: "blue"};
    const again = Math.max(this.wrongAt + 1800, this.msg ? this.msg.at + 1800 : 0, this.freedAt, this.opened + 900);
    return {at: at(again), text: "> ONARIM KODU BEKLENİYOR", cls: "blue", wait: true};
  },
  // doğru koddan sonra durum satırının yerinde onarım günlüğü akar (adlar şu anki adlar)
  sceneLines(s0, k){
    const [a, b] = this.chips;
    const power = (sEase((k - REPAIR.charge) / 1.6) + sEase((k - REPAIR.lag - REPAIR.charge) / 1.6)) / 2;
    const pct = Math.round(power * 100), n = Math.floor(pct / 10);
    return [
      {at: s0, text: `> KOD DOĞRU · ${this.code} · ONARIM BAŞLIYOR`, cls: "blue", bold: true, slides: false},
      {at: s0 + .7, text: "> BİLİNMEYEN KAYNAKTAN SİNYAL ALINDI", cls: "soft"},
      {at: s0 + REPAIR.fill, text: "> ÇATLAKLAR DOLDURULUYOR…", cls: "soft"},
      {at: s0 + REPAIR.fuse, text: "> YARILAR BİRLEŞTİRİLDİ", cls: "soft"},
      {at: s0 + REPAIR.fuse + .35, text: `> ÇEKİRDEK 01 · ${chipName("jarvis")} · BAĞLANTI KURULDU`, color: a.idle},
      {at: s0 + REPAIR.fuse + .6, text: `> ÇEKİRDEK 02 · ${chipName("friday")} · BAĞLANTI KURULDU`, color: b.idle},
      {at: s0 + REPAIR.charge + .75, text: `> GÜÇ [${"#".repeat(n)}${".".repeat(10 - n)}] %${pct}`, cls: "soft"},
      {at: s0 + REPAIR.done, text: "> ONARIM TAMAMLANDI", cls: "white", bold: true},
    ];
  },
  frame(now){
    const page = (now - this.opened) / 1000, k = this.okAt ? (now - this.okAt) / 1000 : null;
    const wrong = (now - this.wrongAt) / 1000, lite = LITE(), calm = calmMotion();
    if(this.lockUntil && !this.locked(now) && !this.busy){       // kilit bitti: kutular yeniden açılır
      this.lockUntil = 0; this.freedAt = now; this.cells();
      codeCells[0].focus();
    }
    // konsol
    const con = $("restore-code"), scene = k !== null;
    const alarm = !scene && (this.locked(now) || now - this.wrongAt < 1800);
    con.classList.toggle("alarm", alarm);
    con.classList.toggle("locked", !scene && this.locked(now));
    con.classList.toggle("denied", !scene && wrong < 1.2);
    con.classList.toggle("done", scene && k >= REPAIR.done);
    sSet(con, "--lt", scene ? sEase(k / .5) : 0);
    const hasar = {at: .25, text: "> HASAR · 2 ÇEKİRDEK · BAĞLANTI KESİK", cls: "dim", slides: false};
    const st = scene ? null : this.status(now);
    const lines = scene ? [hasar, ...this.sceneLines((this.okAt - this.opened) / 1000, k)] : [hasar, st];
    this.log.draw(lines, page, {cursor: st && st.wait ? "_" : "", blink: Math.floor(now / 420) % 2 === 0, fade: [.75, .15]});
    if(this.locked(now)){
      const left = Math.max(0, Math.ceil((this.lockUntil - now) / 1000));
      const txt = `KİLİTLİ · ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      if($("rp-left").textContent !== txt) $("rp-left").textContent = txt;
    }
    if(scene){                                                 // kutular soldan sağa yanar
      codeCells.forEach((c, i) => c.classList.toggle("lit", k > .06 * i + .08));
      con.querySelectorAll(".pindash").forEach((d, i) => d.classList.toggle("lit", k > .06 * (i + 1) + .05));
    }
    // tezgâh: ışık gelince ortası mavi parlar, yanlışta kızarır
    const b = $("rp-bench");
    sSet(b, "--en", scene ? sEase((k - REPAIR.arrive + .2) / .5) * (1 - sEase((k - REPAIR.fuse - .4) / .8)) : 0);
    sSet(b, "--rd", wrong < .6 ? 1 - wrong / .6 : 0);
    for(const c of this.chips) this.chipFrame(c, page, k, wrong, calm, lite);
    // ONARILDI: harfler sembollerden çözülür (mavi → açık mavi → altın), üstte ve altta çizgi açılır; altında iki ad
    if(scene && k >= REPAIR.done){
      const v = k - REPAIR.done, box = $("rp-verdict"), ov = $("ov-repair");
      if(!ov.classList.contains("healed")){ ov.classList.add("healed"); $("rp-say").textContent = "ONARILDI"; }
      const word = calm ? "ONARILDI" : sDecode("ONARILDI", v, Math.floor(v * 24), .08, .04);
      if($("rp-done").textContent !== word) $("rp-done").textContent = word;
      const w = Math.min(innerWidth - 80, 300) * sEase((v - .05) / .45);
      for(const r of box.querySelectorAll("i")) r.style.width = w.toFixed(0) + "px";
      $("rp-online").style.opacity = sEase((v - .5) / .4).toFixed(3);
      box.style.opacity = sEase(v / .18).toFixed(3);
      box.style.transform = calm ? "" : `scale(${(1 + .1 * (1 - sEase(v / .3))).toFixed(3)})`;
    }
    this.draw(now, page, k, wrong, calm, lite);
  },
  // Tezgâhtaki çip: kırıkken iki yarısı hafif kaymış, çatlakta ara ara mavi kıpırtı. Doğru kodda çatlak mavi ışıkla
  // dolar, yarılar açılıp havada durur, sonra uçarak birleşir (ak dikiş, parlama, sıçrama); devre, pimler, ad ve güç döner.
  chipFrame(c, page, k, wrong, calm, lite){
    const scene = k !== null, s = scene ? k - REPAIR.lag * c.i : -1, f = s - REPAIR.fuse, last = c.last;
    const set = (node, prop, v) => { const key = prop + (node === c.chip ? "c" : "s"), x = typeof v === "number" ? v.toFixed(3) : v;
      if(last[key] !== x){ last[key] = x; node.style.setProperty(prop, x); } };
    const power = scene ? sEase((s - REPAIR.charge) / 1.6) : 0;
    const after = scene ? s - REPAIR.done : -1;
    const breath = calm || after < 0 ? 1 : .85 + .15 * Math.cos(after * 3);
    set(c.chip, "--pw", power * breath); set(c.slot, "--pw", power);
    set(c.chip, "--li", scene ? sEase((s - REPAIR.relight) / .9) : 0);
    // yanlışta sarsılır
    const jolt = calm || wrong > .4 ? 0 : Math.sin(wrong * 50 + c.i) * 3 * (1 - wrong / .4);
    set(c.chip, "transform", jolt ? `translateX(${jolt.toFixed(1)}px) scale(var(--rk,1))` : "");
    // ad: bozukken harflerin bir kısmı sembol; çözüldükçe soldan sağa düzelir
    const tick = calm ? 0 : scene ? Math.floor(s * 24) + 5 * c.i : Math.floor(page * 3) + 5 * c.i;
    const clean = Math.floor((scene ? sClamp((s - REPAIR.decode) / .7) : 0) * c.name.length);
    const name = [...c.name].map((ch, j) => j >= clean && ch !== " " && sHash(tick * 977 + 7, j + 31 * c.i) < .3
      ? SCENE_GLYPHS[Math.floor(sHash(tick, j + 9) * SCENE_GLYPHS.length)] : ch).join("");
    for(const l of c.labels) if(l.textContent !== name) l.textContent = name;
    // pimler ortadan kenara tek tek kıpırdayıp yanar
    const pads = scene ? 9 * sClamp((s - REPAIR.pads) / 1.08) : 0;
    REPAIR_PINS.forEach((p, rank) => {
      const l = pads >= rank + 1 ? 1 : pads > rank ? (tick % 2 ? .3 : .9) : 0, x = l.toFixed(2);
      for(const pin of [c.pins[p], c.pins[p + 9]]) if(pin && pin._l !== x){ pin._l = x; pin.style.setProperty("--l", x); }
    });
    // onarım çerçevesi: ışık gelince oturur, birleşince çipin rengine döner, ONARILDI'da söner
    const lock = scene ? sEase((s - REPAIR.arrive) / .35) : 0, joined = scene ? sEase((s - REPAIR.fuse) / .3) : 0;
    set(c.brk, "--lk", lock); set(c.brk, "--gone", scene ? sEase((s - REPAIR.done) / .6) : 0);
    set(c.brk, "--bc", joined > .5 ? c.rgb : REPAIR_BLUE);
    set(c.brk, "transform", calm || lock <= 0 ? "" : `scale(${(1 + .1 * (1 - lock)).toFixed(3)})`);
    // okuma: güç %, ince çubuk
    const pct = `%${Math.round(power * 100)}`;
    if(c.pct.textContent !== pct) c.pct.textContent = pct;
    c.read.classList.toggle("on", power > .001);
    set(c.bar, "width", (power * 100).toFixed(1) + "%");
    const op = (node, v) => { const x = Math.max(0, Math.min(1, v)).toFixed(3); if(node._o !== x){ node._o = x; node.setAttribute("opacity", x); } };
    const dash = (node, v) => { const x = (1 - sClamp(v)).toFixed(3); if(node._d !== x){ node._d = x; node.setAttribute("stroke-dashoffset", x); } };
    if(scene && f >= 0){
      if(c.split){                                           // birleşti: tek gövde
        c.split = false;
        c.chip.classList.remove("split");
        breakChip(c.chip, false);
        c.halves = [c.chip.querySelector(".cbody")];
        for(const p of [c.fl, c.burn, c.lit, c.core]) op(p, 0);
        op(c.head, 0);
      }
      sSet(c.halves[0], "transform", calm ? "" : `scale(${(1 + .05 * Math.exp(-f * 6) * Math.cos(f * 18)).toFixed(4)})`);
      const white = 1 - sEase(f / .6), glow = 1 - sEase((f - .15) / 1.4);
      op(c.flash, !calm && f < .25 ? .5 * (1 - f / .25) : 0);
      op(c.seam, glow); op(c.seamW, white);
      op(c.glow, lite ? 0 : .9 * glow);
      sSet(c.glow, "stroke", `rgb(${c.rgb})`);
      c.glow.setAttribute("stroke-width", "7"); dash(c.glow, 1);
      return;
    }
    op(c.seam, 0); op(c.seamW, 0); op(c.flash, 0);
    const join = scene ? (calm ? sEase((s - REPAIR.fuse + .6) / .6) : sEaseIn((s - REPAIR.fuse + .28) / .28)) : 0;
    const m = 1 - join, a = !scene || calm ? 0 : sEase((s - REPAIR.lift) / .6) * m;
    const bob = calm ? 0 : Math.sin(s * 6.5) * 1.6 * a, u = 1.52;     // telefondaki 116 pt'lik kartın ölçüsünden
    sSet(c.halves[0], "transform", `translate(${((-4 * m - 13 * a) * u).toFixed(2)}px,${((3 * m - 5 * a + bob) * u).toFixed(2)}px) `
      + `rotate(${(-2.5 * m - 5 * a).toFixed(2)}deg)`);
    sSet(c.halves[1], "transform", `translate(${((4 * m + 13 * a) * u).toFixed(2)}px,${((-2 * m + 4 * a - bob) * u).toFixed(2)}px) `
      + `rotate(${(2 * m + 4.5 * a).toFixed(2)}deg)`);
    const fill = scene ? sEase((s - REPAIR.fill) / .8) : 0, seen = calm ? 1 : fill;
    const ph = (page + 1.7 * c.i) % 4.2;                      // kod beklenirken çatlakta ~4 sn'de bir mavi kıpırtı
    const flick = scene || calm ? 0 : ph < .5 ? (1 - ph / .5) * (.5 + .5 * Math.sin(ph * 40)) * .5 : 0;
    const hum = .82 + .18 * Math.sin(s * 9), burn = wrong < .6 ? 1 - wrong / .6 : 0;
    sSet(c.glow, "stroke", "");
    c.glow.setAttribute("stroke-width", (6 + 18 * a).toFixed(1));
    dash(c.glow, seen); op(c.glow, fill > 0 ? (lite ? .35 : .85) * hum * (calm ? fill : 1) : 0);
    op(c.fl, flick); op(c.burn, burn);
    dash(c.lit, seen); dash(c.core, seen);
    op(c.lit, fill > 0 ? .9 * (calm ? fill : 1) : 0); op(c.core, fill > 0 ? (calm ? fill : 1) : 0);
    if(!calm && fill > 0 && fill < 1){
      const p = crackPoint(fill, {x: 0, y: 0, w: 176, h: 252});
      c.head.setAttribute("cx", p.x.toFixed(1)); c.head.setAttribute("cy", p.y.toFixed(1)); op(c.head, 1);
    } else op(c.head, 0);
  },
  // Işık ve kıvılcımlar (tam ekran tuval): köşedeki mavi ışık, tezgâha süzülüşü, ikiye ayrılışı; yanlışta çatlaktan
  // kırmızı kıvılcım; kod beklenirken çiplerin üstünden geçen tarama; birleşmede şok halkası ve kıvılcım; onarılınca
  // yükselen zerreler; birleşmede kısa ak parlama, ONARILDI'da mavi ışıma.
  draw(now, page, k, wrong, calm, lite){
    const cv = $("rp-fx"), dpr = lite ? 1 : Math.min(2, devicePixelRatio || 1), W = innerWidth, H = innerHeight;
    if(cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)){ cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const rects = this.chips.map(c => { const b = c.box.getBoundingClientRect();
      return {x: b.left, y: b.top, w: b.width, h: b.height, cx: b.left + b.width / 2, cy: b.top + b.height / 2}; });
    if(rects.length < 2) return;
    const s = k === null ? -1 : k, sc = rects[0].w / 124, B = REPAIR_BLUE;
    const corner = {x: 27, y: 59};                            // #ylight'ın yeri (sayfa açılınca orada sönük durur)
    const dot = (p, r, a) => {
      const halo = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3.4);
      halo.addColorStop(0, `rgba(${B},${.6 * a})`); halo.addColorStop(1, `rgba(${B},0)`);
      g.fillStyle = halo; g.beginPath(); g.arc(p.x, p.y, r * 3.4, 0, Math.PI * 2); g.fill();
      g.fillStyle = `rgba(223,247,255,${a})`; g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); g.fill();
    };
    if(s < REPAIR.stream){                                    // köşede bekler; doğru kodda parlar
      const wake = s < 0 ? 0 : sEase(s / REPAIR.stream), rest = .18 + .05 * Math.sin(page * 1.3);
      dot(corner, 3 + 1.5 * wake, calm && s >= 0 ? rest * (1 - wake) : rest + (1 - rest) * wake);
    } else if(!calm){
      g.globalCompositeOperation = "lighter";
      const mid = {x: (rects[0].cx + rects[1].cx) / 2, y: rects[0].y - 12}, via = {x: W * .66, y: corner.y + 6};
      const u = (s - REPAIR.stream) / (REPAIR.arrive - REPAIR.stream);
      if(u < 1){                                              // kuyruğuyla süzülür
        for(let j = 15; j >= 0; j--){
          const v = sEase(Math.max(0, u - j * .02));
          dot(sBez2(v, corner, via, mid), 4.2 - j * .22, (1 - j / 16) * (j ? .55 : 1));
        }
      } else {
        const w = sClamp((s - REPAIR.arrive) / (REPAIR.fill - REPAIR.arrive + .06));
        if(s - REPAIR.arrive < .45){                          // ayrılma halkası
          const q = (s - REPAIR.arrive) / .45, rr = 4 + 26 * Math.sqrt(q);
          g.strokeStyle = `rgba(${B},${.8 * (1 - q)})`; g.lineWidth = 1.5;
          g.beginPath(); g.arc(mid.x, mid.y, rr, 0, Math.PI * 2); g.stroke();
        }
        if(w < 1) rects.forEach(r => {                        // ikiye ayrılıp çatlakların tepesine
          const e = sEase(w), top = {x: r.x + CRACK.x[0] * r.w, y: r.y};
          dot({x: sMix(mid.x, top.x, e), y: sMix(mid.y, top.y, e)}, 3.6, 1);
        });
      }
      g.globalCompositeOperation = "source-over";
    }
    rects.forEach((r, i) => {
      const colour = this.chips[i].rgb;
      if(k === null && !calm){                                // tarama: kartın içinde, uçlarda söner
        const ph = ((page + 1.4 * i) / 3.6) % 1, fade = Math.sin(ph * Math.PI), y = r.y + 14 * sc + ph * (r.h - 18 * sc);
        const band = g.createLinearGradient(0, y - 14 * sc, 0, y);
        band.addColorStop(0, `rgba(${B},0)`); band.addColorStop(1, `rgba(${B},${.12 * fade})`);
        g.fillStyle = band; g.fillRect(r.x + 3, y - 14 * sc, r.w - 6, 14 * sc);
        g.fillStyle = `rgba(${B},${.35 * fade})`; g.fillRect(r.x + 3, y, r.w - 6, 1);
      }
      if(calm) return;
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      const streak = (x, y, vx, vy, q, hue, mid2, end) => {
        g.strokeStyle = q < .25 ? `rgba(255,255,255,${1 - q})` : q < (end || .6) ? `rgba(${mid2},${1 - q})` : `rgba(${hue},${1 - q})`;
        g.lineWidth = .6 + 1.5 * (1 - q);
        g.beginPath(); g.moveTo(x, y); g.lineTo(x - vx * .033, y - vy * .033); g.stroke();
      };
      if(wrong < .7) for(let j = 0; j < (lite ? 6 : 14); j++){   // yanlış kod: çatlaktan kırmızı kıvılcım
        const id = i * 100 + j, life = .35 + .35 * sHash(id, 1);
        if(wrong >= life) continue;
        const o = crackPoint(sHash(id, 2), r), ang = sHash(id, 3) * Math.PI * 2, sp = (90 + 220 * sHash(id, 4)) * sc;
        streak(o.x + Math.cos(ang) * sp * wrong, o.y + Math.sin(ang) * sp * wrong + 300 * sc * wrong * wrong,
               Math.cos(ang) * sp, Math.sin(ang) * sp + 600 * sc * wrong, wrong / life, KILL_RED, "255,176,102");
      }
      if(k !== null){
        const f = k - REPAIR.lag * i - REPAIR.fuse;
        if(f > 0 && f < 1.1){
          if(f < .45){                                        // şok halkası
            const q = f / .45, rr = (14 + .75 * r.h) * Math.sqrt(q);
            g.strokeStyle = `rgba(${colour},${.85 * (1 - q)})`; g.lineWidth = 2.5 * (1 - q) + .5;
            g.beginPath(); g.arc(r.cx, r.cy, rr, 0, Math.PI * 2); g.stroke();
          }
          for(let j = 0; j < (lite ? 8 : 20); j++){           // dikişten iki yana kıvılcım
            const id = i * 100 + 40 + j, life = .35 + .5 * sHash(id, 1);
            if(f >= life) continue;
            const o = crackPoint(sHash(id, 2), r), ang = (sHash(id, 3) < .5 ? Math.PI : 0) + (sHash(id, 4) - .5) * 1.5;
            const sp = (140 + 300 * sHash(id, 5)) * sc;
            streak(o.x + Math.cos(ang) * sp * f, o.y + Math.sin(ang) * sp * f + 260 * sc * f * f,
                   Math.cos(ang) * sp, Math.sin(ang) * sp + 520 * sc * f, f / life, colour, "191,241,255", .65);
          }
        }
        const e = k - REPAIR.done;
        if(e > 0) for(let j = 0; j < (lite ? 3 : 7); j++){    // onarılan çipten yükselen zerreler
          const id = i * 100 + 70 + j, st = .12 * j;
          if(e <= st) continue;
          const period = 1.6 + .8 * sHash(id, 1), ph = ((e - st) / period) % 1;
          const p = {x: r.x + r.w * (.1 + .8 * sHash(id, 2)) + Math.sin(ph * 6 + j) * 4, y: r.y + r.h - ph * (r.h * .9 + 30)};
          const a = Math.sin(ph * Math.PI) * .75, rr = (1.2 + 1.3 * sHash(id, 3)) * Math.max(1, sc * .8);
          const halo = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, rr * 3);
          halo.addColorStop(0, `rgba(${colour},${.5 * a})`); halo.addColorStop(1, `rgba(${colour},0)`);
          g.fillStyle = halo; g.beginPath(); g.arc(p.x, p.y, rr * 3, 0, Math.PI * 2); g.fill();
          g.fillStyle = `rgba(255,255,255,${a})`; g.beginPath(); g.arc(p.x, p.y, rr * .7, 0, Math.PI * 2); g.fill();
        }
      }
      g.globalCompositeOperation = "source-over";
    });
    if(k !== null){                                           // birleşmede kısa ak parlama, ONARILDI'da mavi ışıma
      const f = k - REPAIR.fuse, v = k - REPAIR.done;
      const white = calm || f < 0 ? 0 : .12 * Math.max(0, 1 - f / .2);
      const bloom = v < 0 ? 0 : (calm ? .06 : .14) * Math.max(0, 1 - v / .9);
      if(bloom > 0){
        const glow = g.createRadialGradient(W / 2, H * .3, 0, W / 2, H * .3, 520);
        glow.addColorStop(0, `rgba(${B},${bloom})`); glow.addColorStop(1, `rgba(${B},0)`);
        g.fillStyle = glow; g.fillRect(0, 0, W, H);
      }
      if(white > 0){ g.fillStyle = `rgba(255,255,255,${white})`; g.fillRect(0, 0, W, H); }
    }
  },
  // yanlış kod, kilit ya da başka bir ret (Python: chainsRestoreFail)
  failed(message, hint, info){
    const now = performance.now();
    this.checking = 0;
    if(hint){ $("restore-hint").textContent = hint; $("restore-hint-box").hidden = false; }   // ilk yanlıştan sonra
    if(info.wrong){
      this.wrongAt = now; this.triesLeft = info.tries_left ?? 0;
      SFX.play("s_zap");
      const con = $("restore-code");
      if(!calmMotion()){ con.classList.remove("shake"); void con.offsetWidth; con.classList.add("shake"); }
    }
    if(info.locked_left > 0){
      this.lockUntil = now + info.locked_left * 1000; this.lockedAt = now; this.freedAt = 0;
      SFX.play("s_deny");
    } else if(!info.wrong){
      this.msg = {at: now, text: "> " + trUpper(String(message || "").replace(/\.$/, ""))};
      SFX.play("warn");
    }
    clearCode(); this.cells();
    if(!this.locked()) codeCells[0].focus();
  },
  say(text){ this.msg = {at: performance.now(), text}; SFX.play("warn"); },
  // doğru kod: sesler sahneyle aynı anda; sonunda sayfa kapanır, çipler Python'un ayarlarıyla gerçekten döner
  fixed(){
    if(!$("ov-repair").classList.contains("on")) return;
    this.busy = true; this.checking = 0;
    this.code = codeCells.map(c => c.value.replace(/^0+(?=\d)/, "")).join("-");
    $("ylight").hidden = true;
    $("ov-repair").classList.add("busy");
    $("rp-log").style.height = "72px";
    this.cells();
    if(document.activeElement && document.activeElement.blur) document.activeElement.blur();
    this.okAt = performance.now();
    for(const t of this.timers) clearTimeout(t);
    const at = (s, fn) => this.timers.push(setTimeout(fn, s * 1000));
    codeCells.forEach((_c, i) => at(.06 * i, () => SFX.play("s_blip")));      // kutular sırayla yanar
    at(.05, () => SFX.play("s_swell"));                                        // köşedeki ışık uyanır
    at(REPAIR.fill, () => SFX.play("s_crackle"));                              // çatlaklar dolar
    at(REPAIR.lift - .15, () => SFX.play("s_hum"));                            // yarılar açılır, güç yükselir
    for(let i = 0; i < 2; i++) at(REPAIR.fuse + REPAIR.lag * i, () => SFX.play("s_stamp"));   // yarılar birleşir: tok darbe
    at(REPAIR.fuse + .04, () => SFX.play("s_spark"));                          // dikişten kıvılcım
    for(let j = 0; j < 9; j++) at(REPAIR.pads + .12 * j, () => sceneSfx("s_blip", 60));      // pimler tek tek yanar
    at(REPAIR.done, () => SFX.play("s_ally"));                                 // ONARILDI
    at(REPAIR.end, () => {
      this.busy = false;
      $("ov-repair").classList.remove("busy");
      if($("ov-repair").classList.contains("on")) closeOverlays();
      line("sys", `${chipName("jarvis")} VE ${chipName("friday")} YENİDEN ÇEVRİMİÇİ`);
    });
  },
};
$("ylight").addEventListener("click", () => Repair.open());
window.addEventListener("resize", () => { if($("ov-repair").classList.contains("on")) Repair.fit(); });
// konsola tıklayınca ilk boş kutu (kutunun kendisine değilse)
$("restore-code").addEventListener("click", e => {
  if(e.target.tagName === "INPUT" || Repair.busy || Repair.locked()) return;
  (codeCells.find(c => !c.value) || codeCells[codeCells.length - 1]).focus();
});
/* Onarım kodunun kutuları (chains.CODE_GROUPS; 12 Ekim'den beri 1 – 12 – 16): kutu dolunca sonrakine geçilir, tire,
   nokta ya da boşluk da geçirir; son kutu dolunca kendiliğinden denenir (ONAR düğmesi yok). "1-12-16" yapıştırılınca
   kutulara dağılır. */
let codeCells = [];
const trUpper = t => t.replace(/i/g, "İ").replace(/ı/g, "I").toUpperCase();
function codeGroups(){ const g = CHAINS.code_groups; return Array.isArray(g) && g.length ? g : [1, 2, 2]; }
function clearCode(){ for(const c of codeCells) c.value = ""; }
function buildCodeCells(){
  const row = $("restore-code").querySelector(".pinrow"), groups = codeGroups();
  row.replaceChildren();
  codeCells = groups.map((width, i) => {
    const c = el("input", "pin" + (width > 1 ? " w2" : ""));
    Object.assign(c, {inputMode: "numeric", autocomplete: "off", spellcheck: false});
    c.dataset.max = width;
    c.setAttribute("aria-label", `Onarım kodunun ${i + 1}. kısmı (${width} rakam)`);
    if(i) row.appendChild(el("span", "pindash", "–"));
    row.appendChild(c);
    return c;
  });
  codeCells.forEach((cell, i) => {
    const width = +cell.dataset.max;
    const fill = parts => {               // parçalar: kutulara sırayla; tek parçaysa kutu genişliklerine bölünür
      if(parts.length === 1) parts = codeCells.slice(i).map((c, k, all) => {
        const at = all.slice(0, k).reduce((n, x) => n + +x.dataset.max, 0);
        return parts[0].slice(at, at + +c.dataset.max);
      }).filter(Boolean);
      parts.forEach((p, k) => { if(codeCells[i + k]) codeCells[i + k].value = p.slice(0, +codeCells[i + k].dataset.max); });
      const last = Math.min(codeCells.length - 1, i + parts.length - 1);
      const full = codeCells[last].value.length >= +codeCells[last].dataset.max;
      (full && codeCells[last + 1] ? codeCells[last + 1] : codeCells[last]).focus();
      if(codeCells.every(c => c.value) && codeCells[codeCells.length - 1].value.length >= codeGroups().slice(-1)[0])
        submitCode();
    };
    cell.addEventListener("input", () => {
      const digits = cell.value.replace(/\D/g, "");
      if(digits.length <= width){
        cell.value = digits;
        if(digits.length === width) fill([digits]);
        return;
      }
      fill([digits]);                     // fazlası (hızlı yazma) sonraki kutulara
    });
    cell.addEventListener("paste", e => {
      const text = (e.clipboardData || window.clipboardData).getData("text") || "";
      const parts = text.match(/\d+/g);
      if(!parts) return;
      e.preventDefault();
      fill(parts);
    });
    cell.addEventListener("keydown", e => {
      if(e.key === "Backspace" && !cell.value && i > 0){ codeCells[i - 1].focus(); codeCells[i - 1].value = ""; e.preventDefault(); }
      if(["-", ".", " ", "/", "ArrowRight"].includes(e.key) && cell.value && codeCells[i + 1]){
        e.preventDefault(); codeCells[i + 1].focus();
      }
      if(e.key === "Enter") submitCode();
    });
  });
}
buildCodeCells();
function submitCode(){
  if(Repair.busy || Repair.locked() || (Repair.checking && performance.now() - Repair.checking < 4000)) return;
  if(codeCells.some(c => !c.value)){ Repair.say("> KOD EKSİK"); return; }
  Repair.checking = performance.now();
  send("chains_restore", {code: codeCells.map(c => c.value).join("-")});
}
/* [/hikaye] */

/* ---------------- girdi ---------------- */
// Ek eklendikten sonra yazan kullanıcının sözü kesilmesin diye Python'a "yazıyor" denir.
$("cmd").addEventListener("input", () => {
  const now = Date.now();
  if(now - typedAt > 1000){ typedAt = now; send("typing"); }
});
$("cmd").addEventListener("keydown", e => {
  if(e.key === "Enter"){
    const v = e.target.value.trim();
    if(!v) return;
    e.target.value = "";
    line("you", v);
    askHint(false);
    if(SLEEP) setSleep(false);
    send("text", {text:v});
  }
  if(e.key === "Escape"){ e.target.value = ""; e.target.blur(); }
});
// Esc, sayfadaki hiçbir öğe (ör. harita) yutamasın diye yakalama aşamasında dinlenir.
window.addEventListener("keydown", e => {
  if(e.key === "Escape" || e.key === "Esc" || e.keyCode === 27){
    const a = document.activeElement;
    if(a && a.classList && a.classList.contains("nedit")){ a.dispatchEvent(new Event("cancel")); return; }
    if($("chains").classList.contains("on")){ chainsEsc(); return; }  // [-hikaye]
    if(holdCancel()) return;                          // basılı tutma: yalnızca bırakılır, sayfa açık kalır  // [-hikaye]
    if(Repair.busy && $("ov-repair").classList.contains("on")) return;   // onarım sürerken sayfa kapanmaz  // [-hikaye]
    if(KeyHelp.on){ KeyHelp.close(); return; }        // yalnızca yardım sayfası; altındaki Ayarlar açık kalır
    alarm(false); closeOverlays();
  }
}, true);
// Tam ekran: Windows'ta F11 (tarayıcılardaki gibi), her yerde Ctrl/⌘+F. İlk açılış ekranında da çalışır (yakalama
// aşaması). F11 Mac'te bağlanmaz: pywebview'un tam ekranı orada pencerenin collectionBehavior'ını bozuyor.
window.addEventListener("keydown", e => {
  const ctrlF = (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "f";
  if((OS === "win" && e.key === "F11") || ctrlF){
    e.preventDefault();
    if(!e.repeat) send("fullscreen", {via: ctrlF ? "Ctrl+F" : "F11"});
  }
}, true);
document.addEventListener("keydown", e => {
  if(e.key === "Escape" || Onboard.on){ return; }
  if(e.key === "F4"){ e.preventDefault(); setMic(!(SETTINGS.mic_enabled !== false)); return; }
  if(e.key === "F6"){ e.preventDefault(); toggleCam(); return; }
  if(e.key === "/" && document.activeElement.tagName !== "INPUT" && !document.querySelector(".overlay.on")){
    e.preventDefault(); $("cmd").focus();
  }
});

/* =======================================================================
   PYTHON → SAYFA
   ======================================================================= */
window.jarvis = {
  init(payload){
    OS = payload.os || "mac";
    body.dataset.os = OS;
    PERM_ROWS = payload.perm_rows || null;
    if(OS === "win") $("attach").title = $("attach").title.replace("⌘V", "Ctrl+V");
    THEMES = {};
    for(const t of payload.personas) THEMES[t.key] = t;
    SETTINGS = payload.settings || {};
    body.dataset.quality = LITE() ? "low" : "high";
    /* [hikaye] */
    DISABLED = new Set(SETTINGS.disabled_personas || []);
    CHAINS = payload.chains || CHAINS;
    /* [/hikaye] */
    buildLanguages(payload.languages || []);
    /* [hikaye] */
    setTimeout(() => Repair.sync(), 2500);        // açılış animasyonundan sonra
    /* [/hikaye] */
    applyPersona(payload.persona);
    syncChipNames();
    SFX.persona = payload.persona;
    SFX.preload(payload.persona);
    // İlk dokunuşta gecikme olmasın: arayüz sesleri ve her modelin açılış sesi hazır dursun.
    for(const n of UI_SOUNDS) SFX.load(SFX.url(n));
    for(const k in THEMES) SFX.load(SFX.url("boot", k));
    if(payload.panel_keys) PANEL_KEYS = payload.panel_keys;
    buildPanelToggles();
    renderAbout(payload.about);
    chipCards($("persona-cards"), (key, chip) => pickChip(key, chip, true));
    $("t-mic").dataset.on = SETTINGS.mic_enabled === false ? "0" : "1";
    $("t-mic-state").textContent = SETTINGS.mic_enabled === false ? "KAPALI" : "AÇIK";
    if(!SETTINGS.onboarded) Onboard.open(SETTINGS.onboard_step || "boot");
    else if(!SETTINGS.has_key) Onboard.open("key", true);        // anahtar silinmiş: yalnızca anahtar adımı
    SFX.apply();
    if(payload.panels) setPanels(payload.panels);
    Story.set(payload.story, []);  // [-hikaye]
    if(payload.story && payload.story.ruins) Ruins.show(false);   // GERİ DÖN denmişti: harabe sürer  // [-hikaye]
    else if(payload.story && payload.story.locked && payload.story.ending === "bad") Void.show();   // ULTRON kazanmıştı  // [-hikaye]
  },
  persona(key){ if(!THEME) applyPersona(key); else switchPersona(key, true); },
  // Ayarlar › ÇİP ADLARI'ndan sonra (jarvis/app.py › _rename_chip): yeni adlarla temalar, ayarlar ve yazılar
  chipNames(d){
    d = d || {};
    note("set-name-note", d.note || "", d.ok === false ? "bad" : d.note ? "good" : "");
    if(d.ok === false){ fillChipNames(); return; }
    for(const t of d.personas || []) THEMES[t.key] = t;
    if(THEME && THEMES[THEME.key]) applyPersona(THEME.key);      // üstteki ad, Ayarlar › AI MODELİ
    chipCards($("persona-cards"), (key, chip) => pickChip(key, chip, true));
    syncChipNames();
    /* [hikaye] */
    if(d.chains) CHAINS = d.chains;
    if(d.story) Story.set(d.story, []);
    /* [/hikaye] */
    if(d.settings) this.settings(d.settings);
  },
  state(state, label){
    if(Onboard.on){ Onboard.held = [state, label]; return; }     // ilk açılış ekranı orbu kendisi sürer
    if(RUINS && state === "asleep") return;      // harabede uyku yok (GERİ DÖN'de beyin uyanırken gelen son "uykuda")  // [-hikaye]
    const prev = STATE;
    STATE = state;
    body.dataset.state = state;
    // Hata: kısa nedeniyle (gemini_live.ERROR_TEXT: KOTA DOLDU, İNTERNET YOK…); "SUNUCU HATASI" zaten hata diyor.
    const reason = state === "error" && label ? String(label).toLocaleUpperCase("tr") : "";
    $("t-state").textContent = !reason ? (LABEL[state] || state).toUpperCase()
      : reason.includes("HATA") ? reason : `${LABEL.error} · ${reason}`;
    $("t-state").title = state === "error" ? "Ayrıntı için dokun" : "";
    if(state === "asleep" && !SLEEP) setSleep(true, true);
    if(state !== "asleep" && state !== "connecting" && SLEEP) setSleep(false, true);
    if(state === "listening" || state === "speaking") SFX.ambientWanted = true;
    if(state === "connecting" && prev !== "connecting"){ CONNECT_AT = Date.now(); setTimeout(() => SFX.refresh(), 6100); }
    if(state === "error" || label === "yeniden bağlanıyor") FAILING = true;
    else if(state !== "connecting"){ FAILING = false; ERR_PLAYED = false; ERR_LINE = ""; }   // sağlıklı duruma dönüldü
    if(state === "error" && !ERR_PLAYED){ ERR_PLAYED = true; SFX.play("error"); }
    if(state === "speaking" && SCENE) sceneSpoke = true;  // [-hikaye]
    Ruins.label();               // harabe: konuşmuyorsa KOMUT ALINMIYOR  // [-hikaye]
    SFX.refresh();
    paint();
  },
  line(who, text){
    if(who === "error" && STATE === "error") ERR_LINE = text;     // bağlantı sorununun açıklaması
    line(who, text);
  },
  tool(name, ok, summary){ if(!ok) line("error", summary); },
  level(peak){
    const v = Math.max(0, Math.min(1, Math.sqrt(peak || 0) * 2.6));
    document.querySelectorAll("#vu i").forEach((bar, i) => {
      const share = Math.max(0, Math.min(1, v * (1.25 - Math.abs(i - 2) * .16)));
      bar.style.height = (3 + share * 13).toFixed(1) + "px";
    });
    MicSet.level(v);
  },
  audioDevices(listing){ MicSet.fill(listing || {}); },
  micTest(result){ MicSet.result(result || {}); },
  micCheck(result){ MicCheck.result(result || {}); },
  diagnostics(r){
    const b = $("about-diag");
    clearTimeout(DIAG_TIMER);
    b.disabled = false;
    b.textContent = r && r.ok ? "✓ KOPYALANDI" : "KOPYALANAMADI";
    DIAG_TIMER = setTimeout(() => { b.textContent = "KOPYALA"; }, 4000);
  },
  // mikrofon açılamıyor (blocked | busy | none | unreachable) ya da yeniden açıldı (ok)
  micStatus(state, badge){
    MIC_PROBLEM = state === "ok" || state === "off" ? "" : state;
    $("t-micwarn").hidden = !MIC_PROBLEM;
    if(badge) $("t-micwarn-text").textContent = badge;
    // Ayarlar › SES açıksa "Dinlenen" satırı yeni duruma geçsin (aygıt seçildikten sonra açılış birkaç sn sürebiliyor)
    if($("ov-settings").classList.contains("on") && document.querySelector('.pane[data-pane="ses"].on')) send("audio_devices");
  },
  panels(list){ setPanels(list); },
  panel(m){ setPanel(m); },
  focus(key){ litPanel(key); },
  sfx(name){ sfx(name); },
  settings(s){
    // Kullanıcı kaydırıcıyı henüz bırakmadıysa o değeri geri alma.
    const keep = {sfx_volume: SETTINGS.sfx_volume, voice_volume: SETTINGS.voice_volume};
    Object.assign(SETTINGS, s);
    if(volTimer || voiceTimer) Object.assign(SETTINGS, keep);
    DISABLED = new Set(SETTINGS.disabled_personas || []);  // [-hikaye]
    Repair.settled();  // [-hikaye]
    markCards();
    fillSettings(); SFX.apply(); syncQuality();
    syncWarn(); Repair.sync();  // [-hikaye]
  },
  memory(list){ renderMemory(list); },
  locationStatus(s){ s = s || {}; note("set-location-note", s.text || "", s.kind || ""); },   // Ayarlar › KONUM
  keyResult(ok, message, origin){
    SETTINGS.has_key = SETTINGS.has_key || ok;
    if(origin === "onboard") Onboard.keyResult(ok, message);
    else{
      note("set-key-note", message, ok ? "good" : "bad");
      $("set-khelp").classList.toggle("loud", !ok);      // anahtar geçersiz: ANAHTAR ALAMADIM belirginleşir
      if(ok) $("set-key").value = "";
      if(ok && !KeyHelp.on) Why.stop();     // bağlandı: boş KAYDET'in "neden anahtar?"ı sürmesin, mikrofon modele dönsün
      fillSettings();
    }
  },
  keyMail(copied){ if(copied) KeyHelp.copied(true, true); },    // BANA YAZ: e-posta uygulaması yok, adres panoda
  detail(key, data){ detailData(key, data || {}); },
  webcam(active, url){
    CAMURL = active ? (url || CAMURL) : "";
    setCamUi(active);
    if(DETAIL === "camera") setTimeout(renderCameraDetail, active ? 600 : 0);
    if(!active){ removePanel("camera"); return; }
    if(!PANELS.camera) setPanel({key:"camera", label:"KAMERA", kind:"camera"});
    if(CAMIMG && url){
      CAMIMG.src = url + "?t=" + Date.now();
      setTimeout(() => { if(CAMIMG && CAMIMG.style.display === "none" && CAMIMG.naturalWidth){
        CAMIMG.dispatchEvent(new Event("load")); } }, 1500);
    }
  },
  sleep(on){ setSleep(on, true); },
  creator(){ Info.open(); },          // "seni kim yaptı?" (show_creator)
  chipPicker(){ chipPicker(); },       // "başka çipe geç" (open_chip_picker): çip ekranı açılır, seçimi kullanıcı yapar
  mic(on){ setMic(!!on, true); },      // sesle "mute" / yazarak "mikrofonu aç"
  phone(st){ renderPhone(st || {}); },  // [-telefon]
  map(spot){ openBigMap(spot); },
  timerDone(t){ alarm(true); litPanel("timer"); },
  // Kapanış: modelin kapanış sesi, ekran kararır; ses bitmeden efekt motoru yumuşakça susar.
  goodbye(){
    if(body.classList.contains("shutting")) return;
    alarm(false);
    SFX.ambientWanted = false; SFX.refresh();
    SFX.play("shutdown");
    body.classList.add("shutting");
    setTimeout(() => { if(SFX.master) SFX.master.gain.setTargetAtTime(0, SFX.ctx.currentTime, .12); }, 1450);
    setTimeout(() => SFX.shutdown(), 1850);
  },
  /* [hikaye] */
  chainsResult(r){ chainsResult(r); },
  authority(a){ showAuthority(a || {}); },
  // info: {wrong, tries_left, locked_left} (app._chains_restore); "zaten etkin" gibi retlerde boş
  chainsRestoreFail(message, hint, info){ Repair.failed(message, hint, info || {}); },
  chainsRestored(ok){ if(ok) Repair.fixed(); },          // çipler Python'un ayarlarıyla (REPAIR.end sonra) gerçekten döner
  /* [/hikaye] */
  agendaStatus(st){ renderSources(st || {}); },
  permissions(st, done){ showPerms(st, done); },
  follow(){ Follow.show(); },
  update(st){ Update.state(st); },
  updateProgress(p){ Update.progress(p || {}); },
  /* [gelistirici] */
  proactiveResult(problem){
    note("proactive-note", problem || "", problem ? "bad" : "");
    if(problem) line("error", problem);
  },
  /* [/gelistirici] */
  attaching(count){
    if(preparing) preparing.remove();
    preparing = line("sys", `${count > 1 ? count + " DOSYA" : "DOSYA"} HAZIRLANIYOR…`);
    preparing.classList.add("pending");
  },
  attached(batch){
    if(preparing){ preparing.remove(); preparing = null; }
    const cmd = $("cmd"), text = cmd.value.trim();
    cmd.value = "";
    fileRow(batch.items);
    if(text) line("you", text);
    if(batch.extra) line("sys", `EN FAZLA 10 DOSYA · ${batch.extra} DOSYA GÖNDERİLMEDİ`);
    const bad = batch.items.filter(a => a.error);
    if(bad.length) line("error", bad.map(a => `${a.name}: ${a.error}`).join(" · "));
    if(SLEEP) setSleep(false);
    send("files", {batch: batch.id, text});
    if(!text && bad.length < batch.items.length){ askHint(true); cmd.focus(); }
  },
  sentFiles(batch){ sentRow(batch); },
  /* [hikaye] */
  story(view, events){ Story.set(view, events); Ruins.sync(); },
  ruins(d){ Ruins.show(!!(d && d.intro)); },     // kötü sonun karanlığında GERİ DÖN (jarvis/app.py › _enter_ruins)
  finalAsk(d){
    const side = (d || {}).side, k = Story.view.key;
    if(k && !k.code) KeyPanel.open(side);       // kod henüz bulunmadı: karar 🔑'den, kod girilerek verilir
    else Final.ask(side);
  },
  storyKeyResult(r){ KeyPanel.result(r || {}); },     // 🔑 hikâye kodu (API anahtarının keyResult'ı ayrı)
  netBlocked(){ if(!document.querySelector(".overlay.on")) NetNotice.show(); },    // ULTRON'un internet engeli
  finale(d){ Finale.play(d || {}); },
  finaleUndo(){ Finale.clear(); Ruins.hide(); Void.hide(true); line("sys", "◀ SON KARAR ANINA DÖNÜLDÜ"); },
  openWorld(){ Finale.clear(); Ruins.hide(); Void.hide(false); closeOverlays(); line("sys", "AÇIK DÜNYA · ÜÇ ÇİP DE GERİ DÖNDÜ"); },
  storyReplay(){                                       // ★ › TEKRAR OYNA (son ekranından, harabeden ya da açık dünyadan)
    Finale.clear(); Ruins.hide(); Void.hide(false); closeOverlays(); Repair.lockUntil = 0;   // onarım kilidi de kalkar
    line("sys", "◀ HİKÂYE BAŞTAN · SONLAR KALDI");
  },
  leak(k){ Leak.show(k || {}); },
  awakening(stage, data){ awakening(stage, data); },
  /* [/hikaye] */
  fileThumb(id, src){
    const face = document.querySelector(`.sfile[data-id="${id}"] .sface`);
    if(!face) return;
    const img = el("img"); img.src = src; img.alt = "";
    const mark = face.querySelector(".mark");
    if(mark) mark.replaceWith(img); else face.prepend(img);
  },
  needFiles(names){
    const pick = lastDrop.filter(f => names.indexOf(f.name) >= 0);
    if(pick.length) sendBlobs(pick);
    else line("error", `Bırakılan öğe okunamadı. Dosyayı önce ${OS === "win" ? "bir klasöre" : "Finder'a"} kaydedip oradan sürükle.`);
  },
};

/* pywebview hazır olunca Python'a haber ver. Tarayıcıda (ön izleme) köprü yoktur. */
window.addEventListener("pywebviewready", () => send("ready"));

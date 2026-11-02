/* JARVIS — telefon (jarvis/phone.py).
   Mac'teki JARVIS'e bağlanır: sesin buradan çıkar, mikrofon buradan dinler, yazılan oraya gider.

   V3'teki sorunlar ve buradaki karşılıkları:
   - iPhone'da ses bazen hiç çıkmıyordu: ses motoru dokunuşsuz açılıyordu. Artık BAŞLAT'a
     dokununca açılır; kilitlenip açılınca uyanmazsa yeniden dokunmak istenir.
   - Mikrofon sesi süzgeçsiz 16 kHz'e iniyordu: önce iki alçak geçiren süzgeç (worklet.js).
   - JARVIS kendi sesini duyup sözünü kesiyordu: ses çalarken mikrofon gönderilmez.
   - Bağlantı koptuğunda sayfa yenilenmeden dönmüyordu: kendiliğinden yeniden bağlanır.
   - Erişim kodu adres çubuğunda duruyordu: # kısmından okunur, saklanır ve adresten silinir. */
"use strict";
const $ = id => document.getElementById(id);
const body = document.body;
const P = {ws: null, token: "", ctx: null, gain: null, next: 0, sources: [], started: false, micOn: false,
           stream: null, node: null, graph: [], backoff: 1000, stop: false, wake: null, state: "connecting",
           workletReady: false};
const LABEL = {connecting: "BAĞLANIYOR", listening: "DİNLİYOR", thinking: "DÜŞÜNÜYOR", speaking: "KONUŞUYOR",
               idle: "HAZIR", paused: "HAZIR", asleep: "UYKUDA · UYANDIRMAK İÇİN DOKUN", error: "BAĞLANTI SORUNU"};

/* ---- erişim kodu: QR'daki adresin # kısmından; saklanır, adresten silinir ---- */
function readCode(text){
  const m = String(text || "").match(/[#&?]t=([^&\s]+)/);
  return decodeURIComponent(m ? m[1] : String(text || "").trim());
}
(function(){
  if(/[#&]t=/.test(location.hash)){
    try{ localStorage.setItem("jarvis_phone", readCode(location.hash)); }catch(e){}
    history.replaceState(null, "", location.pathname);
  }
  try{ P.token = localStorage.getItem("jarvis_phone") || ""; }catch(e){ P.token = ""; }
})();

/* ---- görünüm ---- */
function hexRgb(h){ const n = parseInt(String(h).slice(1), 16); return `${n >> 16 & 255},${n >> 8 & 255},${n & 255}`; }
function theme(t){
  if(!t) return;
  const p = t.palette || {};
  document.documentElement.style.setProperty("--c", p.idle || "#5ED8FF");
  document.documentElement.style.setProperty("--rgb", hexRgb(p.idle || "#5ED8FF"));
  if(p.ink) document.documentElement.style.setProperty("--ink", p.ink);
  if(p.dim) document.documentElement.style.setProperty("--dim", p.dim);
  $("name").textContent = t.name || "JARVIS";
  $("gate-name").textContent = t.name || "JARVIS";
  document.title = t.name || "JARVIS";
}
function setState(s){
  P.state = s;
  body.dataset.state = s;
  $("state").textContent = LABEL[s] || String(s || "").toUpperCase();
}
function link(text, kind){ $("link-text").textContent = text; $("link").dataset.kind = kind; }
function addLine(who, text){
  if(!text) return;
  const p = document.createElement("p");
  p.className = who;
  p.textContent = text;
  const subs = $("subs");
  subs.appendChild(p);
  while(subs.children.length > 6) subs.firstChild.remove();
}
function gate(text, askCode){
  $("gate-text").textContent = text;
  $("code-row").hidden = !askCode;
  $("gate").classList.add("on");
}

/* ---- bağlantı ---- */
function send(obj){ if(P.ws && P.ws.readyState === 1) P.ws.send(JSON.stringify(obj)); }
function connect(){
  if(P.stop || P.ws) return;
  if(!P.token){ gate("Mac'teki JARVIS'te Ayarlar › Telefon'daki QR kodu okut ya da kodu buraya yapıştır.", true); return; }
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  P.ws = ws;
  link("BAĞLANIYOR", "wait");
  ws.onopen = () => ws.send(JSON.stringify({type: "hello", token: P.token, device: navigator.userAgent}));
  ws.onmessage = e => { if(typeof e.data === "string") onJson(JSON.parse(e.data)); else onAudio(e.data); };
  ws.onclose = e => {
    if(P.ws === ws) P.ws = null;
    cut();
    if(e.code === 4001 || e.code === 4003){ P.stop = true; return; }     // kod yanlış / çok deneme: bekle
    if(e.code === 4002){ P.stop = true; return; }                         // başka cihaz bağlandı
    link("YENİDEN BAĞLANIYOR", "bad");
    setState("connecting");
    setTimeout(connect, P.backoff);
    P.backoff = Math.min(P.backoff * 1.6, 10000);
  };
}
function onJson(m){
  switch(m.type){
    case "welcome":
      P.backoff = 1000;
      theme(m.theme);
      setState(m.state || "listening");
      link("MAC · BAĞLI", "ok");
      if(P.started) syncAudio();
      break;
    case "state": setState(m.state); break;
    case "line": if(m.who !== "you" || !P.typed || P.typed !== m.text) addLine(m.who === "ai" ? "ai" : m.who, m.text);
                 P.typed = ""; break;
    case "persona": theme(m.theme); break;
    case "cut": cut(); break;
    case "denied":
      try{ localStorage.removeItem("jarvis_phone"); }catch(e){}
      P.token = "";
      link("KOD GEÇERSİZ", "bad");
      gate(m.text || "Erişim kodu geçersiz. Mac'teki QR kodu yeniden okut.", true);
      break;
    case "replaced":
      link("BAŞKA CİHAZDA", "bad");
      gate(m.text + " Buradan sürdürmek için dokun.", false);
      break;
    case "bye": link("MAC KAPANDI", "bad"); setState("connecting"); break;
  }
}

/* ---- ses: dokunuşla açılır (iPhone) ---- */
async function start(){
  if(!P.token){
    const code = readCode($("code").value);
    if(!code){ gate("Erişim kodunu yapıştır.", true); return; }
    P.token = code;
    try{ localStorage.setItem("jarvis_phone", code); }catch(e){}
  }
  try{
    P.ctx = P.ctx || new (window.AudioContext || window.webkitAudioContext)();
    await P.ctx.resume();
    if(!P.gain){ P.gain = P.ctx.createGain(); P.gain.connect(P.ctx.destination); }
    // iPhone'un ses kilidini aç: kısa, sessiz bir tampon
    const s = P.ctx.createBufferSource(); s.buffer = P.ctx.createBuffer(1, 1, 22050); s.connect(P.gain); s.start();
  }catch(e){ addLine("error", "Ses açılamadı: " + e.message); }
  P.started = true;
  P.stop = false;
  $("gate").classList.remove("on");
  keepAwake();
  if(P.ws) syncAudio(); else connect();
}
function syncAudio(){
  send({type: "audio", on: P.started && document.visibilityState === "visible"});
  send({type: "mic", on: P.micOn});
}
function onAudio(buf){
  if(!P.started || !P.ctx || P.ctx.state !== "running") return;
  const bytes = new Uint8Array(buf);
  if(bytes[0] !== 2 || bytes.length < 3) return;
  const pcm = new Int16Array(buf.slice(1, 1 + ((bytes.length - 1) & ~1)));
  const f = new Float32Array(pcm.length);
  for(let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 32768;
  const ab = P.ctx.createBuffer(1, f.length, 24000);
  ab.copyToChannel(f, 0);
  const src = P.ctx.createBufferSource();
  src.buffer = ab;
  src.connect(P.gain);
  const now = P.ctx.currentTime;
  if(P.next < now + 0.03) P.next = now + 0.12;          // yeni söz: ağ dalgalanmasına küçük bir pay
  src.start(P.next);
  P.next += ab.duration;
  P.sources.push(src);
  src.onended = () => { P.sources = P.sources.filter(x => x !== src); };
}
function cut(){
  for(const s of P.sources){ try{ s.stop(); }catch(e){} }
  P.sources = [];
  P.next = 0;
}
const playing = () => !!P.ctx && P.next > P.ctx.currentTime - 0.3;

/* ---- mikrofon ---- */
async function micOn(){
  if(!P.started){ await start(); }
  try{
    P.stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true,
                                                                  autoGainControl: true, channelCount: 1}});
  }catch(e){
    addLine("error", "Mikrofon izni yok. Tarayıcının ayarlarından bu siteye mikrofon izni ver.");
    return;
  }
  if(!P.workletReady){ await P.ctx.audioWorklet.addModule("/worklet.js"); P.workletReady = true; }
  const src = P.ctx.createMediaStreamSource(P.stream);
  const lp1 = new BiquadFilterNode(P.ctx, {type: "lowpass", frequency: 7000, Q: .7071});
  const lp2 = new BiquadFilterNode(P.ctx, {type: "lowpass", frequency: 7000, Q: .7071});
  P.node = new AudioWorkletNode(P.ctx, "jarvis-mic");
  const mute = P.ctx.createGain(); mute.gain.value = 0;              // işlesin diye bağlı, ama duyulmaz
  src.connect(lp1).connect(lp2).connect(P.node).connect(mute).connect(P.ctx.destination);
  P.graph = [src, lp1, lp2, P.node, mute];
  P.node.port.onmessage = ev => {
    if(!P.micOn || playing() || !P.ws || P.ws.readyState !== 1) return;     // JARVIS konuşurken gönderme
    const pcm = ev.data, frame = new Uint8Array(1 + pcm.byteLength);
    frame[0] = 1;
    frame.set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength), 1);
    P.ws.send(frame);
    let peak = 0;
    for(let i = 0; i < pcm.length; i += 8) peak = Math.max(peak, Math.abs(pcm[i]));
    document.documentElement.style.setProperty("--lv", (1 + Math.min(.35, peak / 32768 * 1.6)).toFixed(3));
  };
  P.micOn = true;
  micUi();
  send({type: "mic", on: true});
}
function micOff(){
  P.micOn = false;
  for(const n of P.graph){ try{ n.disconnect(); }catch(e){} }
  P.graph = []; P.node = null;
  if(P.stream){ for(const t of P.stream.getTracks()) t.stop(); P.stream = null; }
  document.documentElement.style.setProperty("--lv", "1");
  micUi();
  send({type: "mic", on: false});
}
function micUi(){
  $("mic").setAttribute("aria-pressed", String(P.micOn));
  $("mic-text").textContent = P.micOn ? "DİNLİYOR · KAPATMAK İÇİN DOKUN" : "MİKROFON KAPALI";
  body.classList.toggle("mic-on", P.micOn);
}
function toggleMic(){ if(P.micOn) micOff(); else micOn(); }

/* ---- ekran açık kalsın; arka plana geçince ses Mac'e döner ---- */
async function keepAwake(){
  try{ if("wakeLock" in navigator && document.visibilityState === "visible") P.wake = await navigator.wakeLock.request("screen"); }catch(e){}
}
document.addEventListener("visibilitychange", async () => {
  if(!P.started) return;
  if(document.visibilityState === "hidden"){
    if(P.micOn) micOff();
    cut();
    send({type: "audio", on: false});
    return;
  }
  try{ await P.ctx.resume(); }catch(e){}
  if(!P.ctx || P.ctx.state !== "running"){ P.started = false; gate("Devam etmek için dokun.", false); return; }
  keepAwake();
  syncAudio();
});

/* ---- dokunuşlar ---- */
$("go").addEventListener("click", start);
$("mic").addEventListener("click", toggleMic);
$("orb").addEventListener("click", () => {
  if(P.state === "asleep"){ send({type: "wake"}); return; }
  toggleMic();
});
$("form").addEventListener("submit", e => {
  e.preventDefault();
  const t = $("text").value.trim();
  if(!t) return;
  $("text").value = "";
  addLine("you", t);
  P.typed = t;
  send({type: "text", text: t});
  $("text").blur();
});

setState("connecting");
if(P.token) connect();
else gate("Mac'teki JARVIS'te Ayarlar › Telefon'daki QR kodu okut ya da kodu buraya yapıştır.", true);

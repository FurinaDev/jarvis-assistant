/* Telefonun mikrofonu → 16 kHz, 16 bit (Gemini Live'ın beklediği).
   Önünde iki alçak geçiren süzgeç var (phone.js: 7 kHz); burada her çıkış örneği, düşen
   aralıktaki giriş örneklerinin ortalamasıdır. V3'te süzgeçsiz örnek atlanıyordu: yüksek
   sesler katlanıp konuşmayı bozuyor, JARVIS sözleri yanlış anlıyordu. 40 ms'lik bloklar. */
class JarvisMic extends AudioWorkletProcessor {
  constructor(){
    super();
    this.step = sampleRate / 16000;          // ör. 48000 → 3, 44100 → 2.756
    this.pos = 0; this.sum = 0; this.n = 0;
    this.out = new Int16Array(640);
    this.len = 0;
  }
  process(inputs){
    const ch = inputs[0] && inputs[0][0];
    if(!ch) return true;
    for(let i = 0; i < ch.length; i++){
      this.sum += ch[i]; this.n++; this.pos += 1;
      if(this.pos >= this.step){
        this.pos -= this.step;
        const v = Math.max(-1, Math.min(1, this.sum / this.n));
        this.out[this.len++] = v < 0 ? v * 32768 : v * 32767;
        this.sum = 0; this.n = 0;
        if(this.len === this.out.length){ this.port.postMessage(this.out.slice(0)); this.len = 0; }
      }
    }
    return true;
  }
}
registerProcessor("jarvis-mic", JarvisMic);

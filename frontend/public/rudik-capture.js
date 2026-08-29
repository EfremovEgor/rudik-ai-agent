/**
 * Захват микрофона для Рудика.
 *
 * Отдаёт ровные кадры моно PCM16 с частотой 16 кГц — ровно то, что ждут
 * Vosk и GigaAM на сервере. Если браузер не смог открыть контекст на 16 кГц,
 * пересчитываем частоту сами линейной интерполяцией.
 */

const TARGET_RATE = 16000
const FRAME_SAMPLES = 1024 // 64 мс

class RudikCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.ratio = sampleRate / TARGET_RATE
    this.buffer = new Float32Array(FRAME_SAMPLES)
    this.filled = 0
    this.position = 0
  }

  /** Берёт следующий отсчёт целевой частоты из входного кадра. */
  resample(input) {
    const out = []
    while (this.position < input.length) {
      const index = Math.floor(this.position)
      const frac = this.position - index
      const current = input[index]
      const next = index + 1 < input.length ? input[index + 1] : current
      out.push(current + (next - current) * frac)
      this.position += this.ratio
    }
    this.position -= input.length
    return out
  }

  process(inputs) {
    const input = inputs[0]?.[0]
    if (!input) return true

    const samples = this.ratio === 1 ? input : this.resample(input)

    for (let i = 0; i < samples.length; i += 1) {
      this.buffer[this.filled] = samples[i]
      this.filled += 1
      if (this.filled === FRAME_SAMPLES) {
        const pcm = new Int16Array(FRAME_SAMPLES)
        let peak = 0
        for (let j = 0; j < FRAME_SAMPLES; j += 1) {
          const value = Math.max(-1, Math.min(1, this.buffer[j]))
          pcm[j] = value < 0 ? value * 0x8000 : value * 0x7fff
          const magnitude = Math.abs(value)
          if (magnitude > peak) peak = magnitude
        }
        // Пик отдаём вместе с кадром: по нему живёт эквалайзер на экране.
        this.port.postMessage({ pcm, peak }, [pcm.buffer])
        this.filled = 0
      }
    }
    return true
  }
}

registerProcessor('rudik-capture', RudikCapture)

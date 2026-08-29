/**
 * Голосовая сессия: микрофон, определение конца фразы и отправка на бэкенд.
 *
 * Схема работы режима «всегда слушаю»:
 *   тишина -> первый громкий кадр -> сразу пишем (иначе теряется начало
 *   обращения) -> 1.1 с тишины -> если речи набралось меньше полусекунды,
 *   выбрасываем как шум, иначе отправляем фрагмент -> бэкенд распознаёт,
 *   ищет обращение «Рудик» и отвечает голосом.
 * Пока Рудик говорит, запись стоит на паузе, чтобы он не услышал сам себя.
 */

import { useCallback, useEffect, useRef } from 'react'
import { askByVoice, base64ToBlob } from '#/lib/api'
import {
  addMessage,
  rudikStore,
  setError,
  setHeard,
  setLevel,
  setPhase,
  updateMessage,
} from '#/lib/rudik-store'

// Пауза, после которой считаем фразу законченной. Короче 1 секунды нельзя:
// обычные паузы внутри предложения обрезали бы реплику на полуслове.
const SILENCE_MS = 1100
// Меньше этого — не речь, а шум: такой фрагмент не отправляем вовсе.
const MIN_SPEECH_MS = 500
const MAX_UTTERANCE_MS = 15000
const TICK_MS = 50
const FLOOR = 0.012

function pickMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  for (const type of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) {
      return type
    }
  }
  return ''
}

export function useVoiceSession() {
  const streamRef = useRef<MediaStream | null>(null)
  const contextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Array<Blob>>([])
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speechMsRef = useRef(0)
  const silenceMsRef = useRef(0)
  const baselineRef = useRef(FLOOR)
  const manualRef = useRef(false)
  const pausedRef = useRef(false)
  const guardRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Фрагмент оказался шумом — не отправляем его на бэкенд.
  const discardRef = useRef(false)
  // Кнопку успевают отпустить, пока браузер спрашивает доступ к микрофону.
  const releasedRef = useRef(false)
  // Чтение через функцию: иначе TypeScript считает, что значение не менялось.
  const wasReleased = () => releasedRef.current

  const stopPlayback = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
  }, [])

  const play = useCallback(
    (blob: Blob) =>
      new Promise<void>((resolve) => {
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audioRef.current = audio
        const finish = () => {
          URL.revokeObjectURL(url)
          if (audioRef.current === audio) audioRef.current = null
          resolve()
        }
        audio.onended = finish
        audio.onerror = finish
        void audio.play().catch(finish)
      }),
    [],
  )

  /** Отправляет записанный фрагмент и проигрывает ответ. */
  const send = useCallback(
    async (blob: Blob, requireWakeWord: boolean) => {
      const { sessionId, voiceReplies } = rudikStore.state
      setPhase('thinking')
      try {
        const result = await askByVoice(blob, {
          sessionId,
          requireWakeWord,
          speak: voiceReplies,
        })

        setHeard(result.question)

        // Обращения не было — молча продолжаем слушать.
        if (requireWakeWord && !result.wake.detected) {
          setPhase(rudikStore.state.hotword ? 'listening' : 'idle')
          return
        }

        addMessage({ role: 'user', text: result.question, sources: [] })
        const id = addMessage({
          role: 'assistant',
          text: result.answer,
          sources: result.sources,
        })

        if (voiceReplies && result.audio) {
          setPhase('speaking')
          pausedRef.current = true
          await play(base64ToBlob(result.audio, result.audio_format))
          pausedRef.current = false
        } else if (voiceReplies && !result.audio && result.spoken) {
          // Бэкенд не смог синтезировать речь — озвучиваем средствами браузера.
          speakInBrowser(result.spoken)
        }
        updateMessage(id, { pending: false })
      } catch (error) {
        setError(error instanceof Error ? error.message : String(error))
      } finally {
        pausedRef.current = false
        speechMsRef.current = 0
        silenceMsRef.current = 0
        setPhase(rudikStore.state.hotword ? 'listening' : 'idle')
      }
    },
    [play],
  )

  const stopRecorder = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    recorderRef.current = null
    if (guardRef.current) {
      clearTimeout(guardRef.current)
      guardRef.current = null
    }
  }, [])

  const startRecorder = useCallback(
    (requireWakeWord: boolean) => {
      const stream = streamRef.current
      if (!stream) return
      // Запись могла остаться от прошлого раза в состоянии inactive —
      // такую ссылку просто выбрасываем, иначе кнопка залипает навсегда.
      if (recorderRef.current) {
        if (recorderRef.current.state !== 'inactive') return
        recorderRef.current = null
      }

      const mimeType = pickMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
        chunksRef.current = []

        // Фрагмент оказался шумом, а не речью — молча выбрасываем.
        if (discardRef.current) {
          discardRef.current = false
          setPhase(rudikStore.state.hotword ? 'listening' : 'idle')
          return
        }
        if (blob.size > 2000) {
          void send(blob, requireWakeWord)
        } else {
          setError('Запись слишком короткая — подержите кнопку и говорите чуть дольше.')
          setPhase(rudikStore.state.hotword ? 'listening' : 'idle')
        }
      }
      recorder.start()
      recorderRef.current = recorder
      setPhase('recording')

      // Страховка: если отпускание кнопки почему-то потерялось, запись
      // всё равно завершится сама, а не повиснет навсегда.
      if (guardRef.current) clearTimeout(guardRef.current)
      guardRef.current = setTimeout(() => {
        if (recorderRef.current) stopRecorder()
      }, MAX_UTTERANCE_MS)
    },
    [send, stopRecorder],
  )

  /** Тик анализатора: считаем громкость и решаем, когда фраза началась и кончилась. */
  const tick = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return

    const buffer = new Uint8Array(analyser.fftSize)
    analyser.getByteTimeDomainData(buffer)
    let sum = 0
    for (const sample of buffer) {
      const value = (sample - 128) / 128
      sum += value * value
    }
    const rms = Math.sqrt(sum / buffer.length)
    setLevel(Math.min(1, rms * 6))

    if (pausedRef.current) return

    const threshold = Math.max(FLOOR, baselineRef.current * 2.5)
    const speaking = rms > threshold
    // Уровень шума подстраиваем только в тишине: иначе собственная речь
    // поднимает порог, и середина фразы начинает считаться паузой.
    if (!speaking) {
      baselineRef.current = baselineRef.current * 0.99 + rms * 0.01
    }

    if (manualRef.current) {
      // В режиме кнопки границы фразы задаёт пользователь.
      return
    }
    if (!rudikStore.state.hotword) return

    if (!recorderRef.current) {
      // Пишем с первого же громкого кадра, иначе теряется начало обращения —
      // а там как раз «Рудик». Шум отсеем при остановке.
      if (speaking) {
        speechMsRef.current = TICK_MS
        silenceMsRef.current = 0
        startRecorder(true)
      }
      return
    }

    if (speaking) {
      speechMsRef.current += TICK_MS
      silenceMsRef.current = 0
    } else {
      silenceMsRef.current += TICK_MS
    }

    const elapsed = speechMsRef.current + silenceMsRef.current
    if (silenceMsRef.current >= SILENCE_MS || elapsed > MAX_UTTERANCE_MS) {
      discardRef.current = speechMsRef.current < MIN_SPEECH_MS
      speechMsRef.current = 0
      silenceMsRef.current = 0
      stopRecorder()
    }
  }, [startRecorder, stopRecorder])

  const openMicrophone = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) return true

    // Браузер отдаёт микрофон только в защищённом контексте: в обычном http
    // по IP свойство mediaDevices вообще отсутствует, хотя типы обещают обратное.
    const media = navigator.mediaDevices as MediaDevices | undefined
    if (!media?.getUserMedia) {
      setError(
        window.isSecureContext
          ? 'Браузер не поддерживает запись с микрофона.'
          : `Микрофон доступен только по https или на localhost. Сейчас страница открыта по ${window.location.protocol}//${window.location.host} — откройте её по https или через localhost.`,
      )
      return false
    }

    try {
      const stream = await media.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      streamRef.current = stream

      const context = new AudioContext()
      // Мобильные браузеры создают контекст приостановленным: без resume
      // анализатор читает тишину и режим «всегда слушаю» никогда не сработает.
      if (context.state === 'suspended') await context.resume()
      const source = context.createMediaStreamSource(stream)
      const analyser = context.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.6
      source.connect(analyser)
      contextRef.current = context
      analyserRef.current = analyser

      timerRef.current = setInterval(tick, TICK_MS)
      setError(null)
      return true
    } catch (error) {
      setError(
        error instanceof Error
          ? `Нет доступа к микрофону: ${error.message}`
          : 'Нет доступа к микрофону',
      )
      return false
    }
  }, [tick])

  const closeMicrophone = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = null
    stopRecorder()
    stopPlayback()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    void contextRef.current?.close()
    contextRef.current = null
    analyserRef.current = null
    setLevel(0)
    setPhase('idle')
  }, [stopPlayback, stopRecorder])

  /** Кнопка «нажми и говори»: обращение по имени не обязательно. */
  const pushToTalkStart = useCallback(async () => {
    releasedRef.current = false
    // Первое нажатие открывает диалог разрешения браузера, и кнопку успевают
    // отпустить до того, как микрофон откроется. Без этой проверки запись
    // стартовала бы уже после отпускания и не останавливалась никогда.
    if (!(await openMicrophone()) || wasReleased()) return
    stopPlayback()
    manualRef.current = true
    startRecorder(false)
  }, [openMicrophone, startRecorder, stopPlayback])

  const pushToTalkStop = useCallback(() => {
    releasedRef.current = true
    manualRef.current = false
    stopRecorder()
  }, [stopRecorder])

  useEffect(() => closeMicrophone, [closeMicrophone])

  return {
    openMicrophone,
    closeMicrophone,
    pushToTalkStart,
    pushToTalkStop,
    stopPlayback,
  }
}

/** Запасная озвучка средствами браузера, если бэкенд не синтезировал mp3. */
export function speakInBrowser(text: string): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ru-RU'
  utterance.rate = 1.05
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(utterance)
}

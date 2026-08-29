/**
 * Голосовая сессия киоска: микрофон, границы фразы и переходы экрана.
 *
 *   тишина -> первый громкий кадр -> пишем (иначе теряется начало обращения)
 *   -> 1.1 с тишины -> если речи меньше полусекунды, выбрасываем как шум,
 *   иначе отправляем фрагмент -> бэкенд распознаёт, ищет «Рудик» и отвечает.
 *
 * Пока Рудик говорит, анализ звука на паузе — он не реагирует на себя.
 */

import { useCallback, useEffect, useRef } from 'react'
import { askByVoice, base64ToBlob } from '#/lib/api'
import {
  resetScreen,
  rudikStore,
  setLevel,
  setMicReady,
  showAnswer,
  showError,
  showNoMic,
  startListening,
  startThinking,
} from '#/lib/rudik-store'

const SILENCE_MS = 1100
const MIN_SPEECH_MS = 500
const MAX_UTTERANCE_MS = 15000
const TICK_MS = 50
const FLOOR = 0.012
/** Сколько ответ висит на экране, прежде чем киоск вернётся к ожиданию. */
const ANSWER_HOLD_MS = 7000
const ERROR_HOLD_MS = 5000

function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const type of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type
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
  const holdRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const guardRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const speechMsRef = useRef(0)
  const silenceMsRef = useRef(0)
  const baselineRef = useRef(FLOOR)
  const manualRef = useRef(false)
  const pausedRef = useRef(false)
  const discardRef = useRef(false)
  const releasedRef = useRef(false)
  // Чтение через функцию: иначе TypeScript считает, что значение не менялось.
  const wasReleased = () => releasedRef.current

  const scheduleReset = useCallback((delay: number) => {
    if (holdRef.current) clearTimeout(holdRef.current)
    holdRef.current = setTimeout(resetScreen, delay)
  }, [])

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

  /** Отправляет записанный фрагмент и показывает ответ. */
  const send = useCallback(
    async (blob: Blob, requireWakeWord: boolean) => {
      const { sessionId, voiceReplies } = rudikStore.state
      startThinking()
      try {
        const result = await askByVoice(blob, {
          sessionId,
          requireWakeWord,
          speak: voiceReplies,
        })

        // Обращения не было — тихо возвращаемся к ожиданию.
        if (requireWakeWord && !result.wake.detected) {
          resetScreen()
          return
        }
        if (!result.answer) {
          showError('Не удалось разобрать вопрос.', result.question)
          scheduleReset(ERROR_HOLD_MS)
          return
        }

        showAnswer(result.question, result.answer, result.sources)

        if (voiceReplies && result.audio) {
          pausedRef.current = true
          await play(base64ToBlob(result.audio, result.audio_format))
          pausedRef.current = false
        } else if (voiceReplies && result.spoken) {
          // Бэкенд не смог синтезировать речь — озвучиваем средствами браузера.
          speakInBrowser(result.spoken)
        }
        scheduleReset(ANSWER_HOLD_MS)
      } catch (error) {
        showError(error instanceof Error ? error.message : String(error))
        scheduleReset(ERROR_HOLD_MS)
      } finally {
        pausedRef.current = false
        speechMsRef.current = 0
        silenceMsRef.current = 0
      }
    },
    [play, scheduleReset],
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
      // такую ссылку выбрасываем, иначе микрофон залипает навсегда.
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

        if (discardRef.current) {
          discardRef.current = false
          resetScreen()
          return
        }
        if (blob.size > 2000) {
          void send(blob, requireWakeWord)
        } else {
          resetScreen()
        }
      }
      recorder.start()
      recorderRef.current = recorder

      // Страховка: если границу фразы почему-то потеряли, запись всё равно
      // завершится сама, а не повиснет навсегда.
      if (guardRef.current) clearTimeout(guardRef.current)
      guardRef.current = setTimeout(() => {
        if (recorderRef.current) stopRecorder()
      }, MAX_UTTERANCE_MS)
    },
    [send, stopRecorder],
  )

  /** Тик анализатора: громкость, начало и конец фразы. */
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
    if (!speaking) baselineRef.current = baselineRef.current * 0.99 + rms * 0.01

    // В ручном режиме границы фразы задаёт пользователь.
    if (manualRef.current) return
    // Пока показываем ответ, новые реплики не ловим.
    if (rudikStore.state.screen !== 'listening') return

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
    // по IP свойства mediaDevices вообще нет, хотя типы обещают обратное.
    const media = navigator.mediaDevices as MediaDevices | undefined
    if (!media?.getUserMedia) {
      showNoMic(
        window.isSecureContext
          ? 'Браузер не поддерживает запись с микрофона.'
          : `Микрофон работает только по https или на localhost, а страница открыта по ${window.location.protocol}//${window.location.host}.`,
      )
      return false
    }

    try {
      const stream = await media.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream

      const context = new AudioContext()
      // Мобильные браузеры создают контекст приостановленным: без resume
      // анализатор читает тишину и фраза никогда не начнётся.
      if (context.state === 'suspended') await context.resume()
      const source = context.createMediaStreamSource(stream)
      const analyser = context.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.6
      source.connect(analyser)
      contextRef.current = context
      analyserRef.current = analyser

      timerRef.current = setInterval(tick, TICK_MS)
      setMicReady(true)
      return true
    } catch (error) {
      showNoMic(
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
    if (holdRef.current) clearTimeout(holdRef.current)
    holdRef.current = null
    stopRecorder()
    stopPlayback()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    void contextRef.current?.close()
    contextRef.current = null
    analyserRef.current = null
    setLevel(0)
    setMicReady(false)
  }, [stopPlayback, stopRecorder])

  /** Кнопка на экране ожидания: выдать доступ и начать слушать зал. */
  const startSession = useCallback(async () => {
    if (await openMicrophone()) startListening()
  }, [openMicrophone])

  /** Демо-режим: спросить без обращения по имени (пробел). */
  const pushToTalkStart = useCallback(async () => {
    releasedRef.current = false
    // Первое нажатие открывает диалог разрешения браузера, и кнопку успевают
    // отпустить до того, как микрофон откроется.
    if (!(await openMicrophone()) || wasReleased()) return
    stopPlayback()
    if (holdRef.current) clearTimeout(holdRef.current)
    manualRef.current = true
    startListening()
    startRecorder(false)
  }, [openMicrophone, startRecorder, stopPlayback])

  const pushToTalkStop = useCallback(() => {
    releasedRef.current = true
    manualRef.current = false
    stopRecorder()
  }, [stopRecorder])

  useEffect(() => closeMicrophone, [closeMicrophone])

  return { startSession, closeMicrophone, pushToTalkStart, pushToTalkStop, stopPlayback }
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

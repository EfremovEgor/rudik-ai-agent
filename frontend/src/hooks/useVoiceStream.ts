/**
 * Постоянный голосовой канал.
 *
 * Микрофон льётся на сервер без остановки кадрами PCM16 16 кГц. Там маленькая
 * модель всё время слушает обращение «Рудик», а тяжёлая GigaAM включается
 * только на саму реплику — поэтому реакция мгновенная, а точность высокая.
 *
 * Границы фразы и распознавание теперь целиком на сервере: браузеру остаётся
 * гнать звук и показывать события.
 */

import { useCallback, useEffect, useRef } from 'react'
import { base64ToBlob, streamUrl } from '#/lib/api'
import {
  resetScreen,
  rudikStore,
  setLevel,
  setMicReady,
  setPartial,
  setQuestion,
  showAnswer,
  showError,
  showNoMic,
  startListening,
  startThinking,
} from '#/lib/rudik-store'

/** Сколько ответ висит на экране, прежде чем киоск вернётся к ожиданию. */
const ANSWER_HOLD_MS = 7000
const ERROR_HOLD_MS = 5000
const RECONNECT_MS = 2000
const PING_MS = 20000

interface ServerEvent {
  type: 'ready' | 'wake' | 'partial' | 'thinking' | 'question' | 'answer' | 'listening' | 'error' | 'pong'
  text?: string
  message?: string
  question?: string
  answer?: string
  spoken?: string
  sources?: Array<string>
  audio?: string | null
  audio_format?: string
  hotword?: boolean
  asr?: boolean
}

export function useVoiceStream() {
  const streamRef = useRef<MediaStream | null>(null)
  const contextRef = useRef<AudioContext | null>(null)
  const nodeRef = useRef<AudioWorkletNode | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const holdRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closingRef = useRef(false)
  // Пока Рудик говорит, микрофон на сервер не льём — иначе услышит сам себя.
  const mutedRef = useRef(false)

  const scheduleReset = useCallback((delay: number) => {
    if (holdRef.current) clearTimeout(holdRef.current)
    holdRef.current = setTimeout(resetScreen, delay)
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

  const handleEvent = useCallback(
    async (event: ServerEvent) => {
      switch (event.type) {
        case 'ready':
          if (!event.hotword) {
            showError('Детектор обращения не загрузился на сервере.')
          }
          break
        case 'wake':
          if (holdRef.current) clearTimeout(holdRef.current)
          startListening()
          break
        case 'partial':
          setPartial(event.text ?? '')
          break
        case 'thinking':
          startThinking()
          break
        case 'question':
          setQuestion(event.text ?? '')
          break
        case 'answer': {
          showAnswer(event.question ?? '', event.answer ?? '', event.sources ?? [])
          if (rudikStore.state.voiceReplies && event.audio) {
            mutedRef.current = true
            await play(base64ToBlob(event.audio, event.audio_format ?? 'audio/mpeg'))
            mutedRef.current = false
          } else if (rudikStore.state.voiceReplies && event.spoken) {
            speakInBrowser(event.spoken)
          }
          scheduleReset(ANSWER_HOLD_MS)
          break
        }
        case 'listening':
          // Сервер снова слушает зал; экран переключится сам после паузы.
          break
        case 'error':
          showError(event.message ?? 'Что-то пошло не так')
          scheduleReset(ERROR_HOLD_MS)
          break
        default:
          break
      }
    },
    [play, scheduleReset],
  )

  const connect = useCallback(() => {
    if (socketRef.current) return
    const socket = new WebSocket(streamUrl(rudikStore.state.sessionId))
    socket.binaryType = 'arraybuffer'
    socketRef.current = socket

    socket.onmessage = (message) => {
      try {
        void handleEvent(JSON.parse(message.data as string) as ServerEvent)
      } catch {
        // битый кадр — не наша забота
      }
    }
    socket.onclose = () => {
      socketRef.current = null
      if (closingRef.current) return
      // Киоск работает сутками: молча восстанавливаем связь.
      reconnectRef.current = setTimeout(connect, RECONNECT_MS)
    }
    socket.onerror = () => socket.close()

    if (pingRef.current) clearInterval(pingRef.current)
    pingRef.current = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ping' }))
      }
    }, PING_MS)
  }, [handleEvent])

  const startSession = useCallback(async () => {
    if (streamRef.current) return

    const media = navigator.mediaDevices as MediaDevices | undefined
    if (!media?.getUserMedia) {
      showNoMic(
        window.isSecureContext
          ? 'Браузер не поддерживает запись с микрофона.'
          : `Микрофон работает только по https или на localhost, а страница открыта по ${window.location.protocol}//${window.location.host}.`,
      )
      return
    }

    try {
      const stream = await media.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
      streamRef.current = stream

      // Просим сразу 16 кГц: тогда пересчёт частоты сделает сам браузер.
      const context = new AudioContext({ sampleRate: 16000 })
      if (context.state === 'suspended') await context.resume()
      await context.audioWorklet.addModule('/rudik-capture.js')

      const source = context.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(context, 'rudik-capture')
      node.port.onmessage = (message) => {
        const { pcm, peak } = message.data as { pcm: Int16Array; peak: number }
        setLevel(Math.min(1, peak * 2.4))
        const socket = socketRef.current
        if (!mutedRef.current && socket?.readyState === WebSocket.OPEN) {
          socket.send(pcm.buffer)
        }
      }
      source.connect(node)
      // Узел должен быть подключён к графу, но звук в колонки не отдаём.
      node.connect(context.destination)

      contextRef.current = context
      nodeRef.current = node

      closingRef.current = false
      connect()
      setMicReady(true)
      startListening()
    } catch (error) {
      showNoMic(
        error instanceof Error
          ? `Нет доступа к микрофону: ${error.message}`
          : 'Нет доступа к микрофону',
      )
    }
  }, [connect])

  const stopSession = useCallback(() => {
    closingRef.current = true
    if (holdRef.current) clearTimeout(holdRef.current)
    if (pingRef.current) clearInterval(pingRef.current)
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    holdRef.current = null
    pingRef.current = null
    reconnectRef.current = null

    socketRef.current?.close()
    socketRef.current = null
    nodeRef.current?.disconnect()
    nodeRef.current = null
    void contextRef.current?.close()
    contextRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null

    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setLevel(0)
    setMicReady(false)
  }, [])

  useEffect(() => stopSession, [stopSession])

  return { startSession, stopSession }
}

/** Запасная озвучка средствами браузера, если сервер не синтезировал mp3. */
export function speakInBrowser(text: string): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ru-RU'
  utterance.rate = 1.05
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(utterance)
}

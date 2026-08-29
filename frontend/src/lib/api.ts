/**
 * Клиент бэкенда Рудика (FastAPI + LangGraph).
 *
 * В dev-режиме запросы идут через прокси Vite на http://localhost:8000,
 * поэтому базовый адрес обычно пустой. Переопределяется через VITE_RUDIK_API.
 */

/**
 * Абсолютный адрес API имеет смысл, только если он доступен с устройства
 * пользователя. Два случая ломаются всегда, поэтому мы их отбрасываем и
 * возвращаемся к запросам на свой origin (их проксирует Vite):
 *  - в адресе localhost, а страницу открыли по сети — это localhost телефона;
 *  - страница по https, а адрес по http — браузер блокирует смешанный контент.
 */
function resolveApiBase(): string {
  const configured = import.meta.env.VITE_RUDIK_API
  if (!configured || typeof window === 'undefined') return configured ?? ''

  let url: URL
  try {
    url = new URL(configured)
  } catch {
    console.warn(`VITE_RUDIK_API=${configured} — не похоже на адрес, использую /api того же origin.`)
    return ''
  }

  const localHosts = ['localhost', '127.0.0.1', '::1']
  const pageIsLocal = localHosts.includes(window.location.hostname)
  if (localHosts.includes(url.hostname) && !pageIsLocal) {
    console.warn(
      `VITE_RUDIK_API указывает на ${configured}, но страница открыта по сети — ` +
        'запросы пойдут на /api того же origin.',
    )
    return ''
  }
  if (window.location.protocol === 'https:' && url.protocol === 'http:') {
    console.warn(
      `VITE_RUDIK_API=${configured} по http, а страница по https — браузер это заблокирует. ` +
        'Запросы пойдут на /api того же origin.',
    )
    return ''
  }
  return configured
}

export const API_BASE = resolveApiBase()

/** Адрес постоянного голосового канала: тот же origin, но по ws/wss. */
export function streamUrl(sessionId: string): string {
  const base = API_BASE || window.location.origin
  const url = new URL('/api/voice/stream', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('session_id', sessionId)
  return url.toString()
}

export interface WakeInfo {
  detected: boolean
  command: string
  matched: string
  score: number
}

export interface Health {
  status: string
  wake_word: string
  llm: {
    base_url: string
    model: string
    reachable: boolean
    models: Array<string>
    error: string | null
  }
  knowledge_base: {
    chunks?: number
    by_kind?: Record<string, number>
    dense?: boolean
    built_at?: string
    embedder?: string | null
  }
  stt: { available: boolean; model: string; loaded: boolean; error: string | null }
  hotword: { available: boolean; model: string; loaded: boolean; downloaded: boolean }
  tts: { available: boolean; backend: string; voice: string }
}

export interface VoiceAnswer {
  question: string
  answer: string
  spoken: string
  sources: Array<string>
  wake: WakeInfo
  audio: string | null
  audio_format: string
  session_id: string
}

export type ChatEvent =
  | { type: 'token'; text: string }
  | { type: 'tool'; name: string; args: Record<string, unknown> }
  | { type: 'done'; text: string; sources: Array<string> }
  | { type: 'error'; message: string }

async function ensureOk(response: Response): Promise<Response> {
  if (response.ok) return response
  let detail = `${response.status} ${response.statusText}`
  try {
    const body = (await response.json()) as { detail?: string }
    if (body.detail) detail = body.detail
  } catch {
    // тело не JSON — оставляем статус
  }
  throw new Error(detail)
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await ensureOk(await fetch(`${API_BASE}/api/health`, { signal }))
  return (await response.json()) as Health
}

/** Потоковый текстовый ответ: колбэк вызывается на каждое событие SSE. */
export async function streamChat(
  message: string,
  sessionId: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await ensureOk(
    await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal,
    }),
  )

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Бэкенд не вернул поток ответа')

  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data:')) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent)
      } catch {
        // недописанный кадр — пропускаем
      }
    }
  }
}

/** Полный голосовой цикл: запись -> расшифровка -> ответ -> озвучка. */
export async function askByVoice(
  audio: Blob,
  options: { sessionId: string; requireWakeWord: boolean; speak: boolean },
  signal?: AbortSignal,
): Promise<VoiceAnswer> {
  const form = new FormData()
  form.append('audio', new File([audio], 'utterance.webm', { type: audio.type || 'audio/webm' }))
  form.append('session_id', options.sessionId)
  form.append('require_wake_word', String(options.requireWakeWord))
  form.append('speak', String(options.speak))

  const response = await ensureOk(
    await fetch(`${API_BASE}/api/voice/ask`, { method: 'POST', body: form, signal }),
  )
  return (await response.json()) as VoiceAnswer
}

/** Озвучка произвольного текста — используется для повтора реплики. */
export async function speak(text: string, signal?: AbortSignal): Promise<Blob> {
  const response = await ensureOk(
    await fetch(`${API_BASE}/api/voice/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal,
    }),
  )
  return await response.blob()
}

export function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

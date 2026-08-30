/** Состояние экрана Рудика на TanStack Store.

Экран — киоск: одно состояние на весь холст, как в макете.
*/

import { Store } from '@tanstack/store'

export type Screen =
  /** Ждём обращения, показываем приветствие. */
  | 'idle'
  /** Микрофон открыт, слушаем зал. */
  | 'listening'
  /** Распознаём речь и ищем ответ. */
  | 'thinking'
  /** Показываем и озвучиваем ответ. */
  | 'answer'
  /** Не расслышали вопрос или запрос не прошёл. */
  | 'error'
  /** Микрофона нет или доступ не выдан. */
  | 'nomic'

export interface RudikState {
  screen: Screen
  /** Микрофон открыт и слушает. */
  micReady: boolean
  /** Громкость с микрофона (0..1) — по ней живёт эквалайзер. */
  level: number
  /** Живая расшифровка от быстрой модели, пока человек говорит. */
  partial: string
  /** Что распознали в последней реплике. */
  question: string
  /** Ответ Рудика целиком. */
  answer: string
  /** Ссылки на страницы сайта, на которые опирался ответ. */
  sources: Array<string>
  /** Текст ошибки для состояния error. */
  errorText: string
  /** Озвучивать ответы. */
  voiceReplies: boolean
  sessionId: string
}

const SESSION_KEY = 'rudik.session'

function initialSession(): string {
  if (typeof window === 'undefined') return 'server'
  try {
    const stored = window.localStorage.getItem(SESSION_KEY)
    if (stored) return stored
    const fresh = `kiosk-${Math.random().toString(36).slice(2, 10)}`
    window.localStorage.setItem(SESSION_KEY, fresh)
    return fresh
  } catch {
    return `kiosk-${Math.random().toString(36).slice(2, 10)}`
  }
}

export const rudikStore = new Store<RudikState>({
  screen: 'idle',
  micReady: false,
  level: 0,
  partial: '',
  question: '',
  answer: '',
  sources: [],
  errorText: '',
  voiceReplies: true,
  sessionId: initialSession(),
})

function patch(values: Partial<RudikState>): void {
  rudikStore.setState((state) => ({ ...state, ...values }))
}

export function setScreen(screen: Screen): void {
  patch({ screen })
}

export function setLevel(level: number): void {
  patch({ level })
}

export function setMicReady(micReady: boolean): void {
  patch({ micReady })
}

export function toggleVoiceReplies(value?: boolean): void {
  rudikStore.setState((state) => ({
    ...state,
    voiceReplies: value ?? !state.voiceReplies,
  }))
}

/** Начали слушать зал: старый диалог со сцены убираем. */
export function startListening(): void {
  patch({ screen: 'listening', partial: '', question: '', answer: '', sources: [], errorText: '' })
}

/** Услышали обращение — дальше показываем расшифровку на лету. */
export function setPartial(partial: string): void {
  patch({ screen: 'listening', partial })
}

export function startThinking(question = ''): void {
  patch({ screen: 'thinking', question, answer: '', sources: [], errorText: '' })
}

export function setQuestion(question: string): void {
  patch({ question })
}

/** Кусочек ответа из потока: экран переключается на первом же токене. */
export function appendAnswer(chunk: string): void {
  rudikStore.setState((state) => ({
    ...state,
    screen: 'answer',
    answer: state.screen === 'answer' ? state.answer + chunk : chunk,
    partial: '',
    errorText: '',
  }))
}

export function showAnswer(question: string, answer: string, sources: Array<string>): void {
  patch({ screen: 'answer', question, answer, sources, errorText: '', partial: '' })
}

export function showError(errorText: string, question = ''): void {
  patch({ screen: 'error', errorText, question, answer: '', sources: [] })
}

export function showNoMic(errorText: string): void {
  patch({ screen: 'nomic', errorText, micReady: false })
}

/** Возврат в дежурный режим: слушаем дальше или ждём нажатия. */
export function resetScreen(): void {
  rudikStore.setState((state) => ({
    ...state,
    screen: state.micReady ? 'listening' : 'idle',
    partial: '',
    question: '',
    answer: '',
    sources: [],
    errorText: '',
  }))
}

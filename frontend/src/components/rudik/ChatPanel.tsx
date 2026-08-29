import { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '@tanstack/react-store'
import { Loader2, Send, Trash2, Volume2, Wrench } from 'lucide-react'
import { Button } from '#/components/ui/button'
import { Input } from '#/components/ui/input'
import { Badge } from '#/components/ui/badge'
import { cn } from '#/lib/utils'
import { speak, streamChat } from '#/lib/api'
import {
  addMessage,
  appendToMessage,
  clearDialog,
  rudikStore,
  setError,
  setPhase,
  updateMessage,
} from '#/lib/rudik-store'
import type { Message } from '#/lib/rudik-store'

const TOOL_LABELS: Record<string, string> = {
  search_academy: 'ищу в базе академии',
  find_person: 'ищу сотрудника',
  latest_news: 'смотрю новости',
  list_departments: 'смотрю кафедры',
  list_programs: 'смотрю направления',
  open_page: 'открываю страницу сайта',
}

const SUGGESTIONS = [
  'Рудик, где кабинет Салтыковой?',
  'Какие кафедры есть в академии?',
  'Что нового в академии?',
  'Какие направления бакалавриата?',
]

/** Убираем строку со ссылкой — она показывается отдельной плашкой. */
function displayText(text: string): string {
  return text.replace(/\/\/\s*https?:\/\/\S+/g, '').trim()
}

function MessageBubble({ message }: { message: Message }) {
  const [speaking, setSpeaking] = useState(false)
  const isUser = message.role === 'user'

  const onSpeak = useCallback(async () => {
    setSpeaking(true)
    try {
      const blob = await speak(displayText(message.text))
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        setSpeaking(false)
      }
      await audio.play()
    } catch {
      setSpeaking(false)
    }
  }, [message.text])

  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm',
          isUser
            ? 'bg-[var(--rudn-blue)] text-white'
            : 'border border-[var(--line)] bg-[var(--surface-strong)] text-[var(--sea-ink)]',
        )}
      >
        {message.tools && message.tools.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1">
            {message.tools.map((tool) => (
              <Badge key={tool} variant="secondary" className="gap-1 text-[11px] font-normal">
                <Wrench className="size-3" />
                {TOOL_LABELS[tool] ?? tool}
              </Badge>
            ))}
          </div>
        )}

        <p className="m-0 whitespace-pre-wrap">
          {displayText(message.text)}
          {message.pending && !message.text && (
            <Loader2 className="inline size-4 animate-spin opacity-60" />
          )}
        </p>

        {!isUser && message.sources.length > 0 && (
          <div className="mt-2 flex flex-col gap-1 border-t border-[var(--line)] pt-2">
            {message.sources.map((source) => (
              <a
                key={source}
                href={source}
                target="_blank"
                rel="noreferrer"
                className="truncate text-xs text-[var(--rudn-blue)] underline-offset-2 hover:underline"
              >
                {source}
              </a>
            ))}
          </div>
        )}

        {!isUser && !message.pending && message.text && (
          <button
            type="button"
            onClick={() => void onSpeak()}
            className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--sea-ink-soft)] transition hover:text-[var(--rudn-blue)]"
          >
            <Volume2 className={cn('size-3.5', speaking && 'animate-pulse')} />
            Озвучить
          </button>
        )}
      </div>
    </div>
  )
}

export function ChatPanel({ className }: { className?: string }) {
  const messages = useStore(rudikStore, (state) => state.messages)
  const error = useStore(rudikStore, (state) => state.error)
  const phase = useStore(rudikStore, (state) => state.phase)
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const ask = useCallback(async (question: string) => {
    const text = question.trim()
    if (!text || rudikStore.state.phase === 'thinking') return

    setDraft('')
    setError(null)
    addMessage({ role: 'user', text, sources: [] })
    const id = addMessage({ role: 'assistant', text: '', sources: [], pending: true, tools: [] })
    setPhase('thinking')

    const tools: Array<string> = []
    try {
      await streamChat(text, rudikStore.state.sessionId, (event) => {
        if (event.type === 'token') {
          appendToMessage(id, event.text)
        } else if (event.type === 'tool') {
          if (!tools.includes(event.name)) {
            tools.push(event.name)
            updateMessage(id, { tools: [...tools] })
          }
        } else if (event.type === 'done') {
          updateMessage(id, { pending: false, sources: event.sources })
        } else {
          setError(event.message)
          updateMessage(id, { pending: false })
        }
      })
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception))
      updateMessage(id, { pending: false })
    } finally {
      setPhase('idle')
    }
  }, [])

  return (
    <section
      className={cn(
        'flex min-h-0 flex-col rounded-3xl border border-[var(--line)] bg-[var(--surface)] p-4 shadow-sm',
        className,
      )}
    >
      <header className="mb-3 flex items-center justify-between">
        <h2 className="m-0 text-sm font-semibold tracking-wide text-[var(--sea-ink-soft)] uppercase">
          Диалог
        </h2>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearDialog} className="text-xs">
            <Trash2 className="mr-1 size-3.5" />
            Очистить
          </Button>
        )}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 ? (
          <div className="flex flex-col gap-3 py-6">
            <p className="m-0 text-sm text-[var(--sea-ink-soft)]">
              Спросите голосом или текстом — например:
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void ask(suggestion)}
                  className="rounded-full border border-[var(--chip-line)] bg-[var(--chip-bg)] px-3 py-1.5 text-xs text-[var(--sea-ink)] transition hover:border-[var(--rudn-blue)] hover:text-[var(--rudn-blue)]"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <p className="mt-3 mb-0 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void ask(draft)
        }}
      >
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Напишите вопрос Рудику..."
          className="h-11 rounded-full bg-[var(--surface-strong)]"
        />
        <Button
          type="submit"
          size="icon"
          disabled={!draft.trim() || phase === 'thinking'}
          className="size-11 shrink-0 rounded-full bg-[var(--rudn-blue)] hover:bg-[var(--rudn-blue-deep)]"
        >
          {phase === 'thinking' ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Send className="size-4" />
          )}
        </Button>
      </form>
    </section>
  )
}

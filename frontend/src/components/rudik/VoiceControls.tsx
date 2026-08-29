import { useCallback, useEffect } from 'react'
import { useStore } from '@tanstack/react-store'
import { Mic, MicOff, Radio, Volume2, VolumeX } from 'lucide-react'
import { Button } from '#/components/ui/button'
import { Switch } from '#/components/ui/switch'
import { cn } from '#/lib/utils'
import {
  rudikStore,
  setPhase,
  toggleHotword,
  toggleVoiceReplies,
} from '#/lib/rudik-store'
import { useVoiceSession } from '#/hooks/useVoiceSession'

/** Микрофон: режим «всегда слушаю» и кнопка «нажми и говори». */
export function VoiceControls() {
  const phase = useStore(rudikStore, (state) => state.phase)
  const hotword = useStore(rudikStore, (state) => state.hotword)
  const voiceReplies = useStore(rudikStore, (state) => state.voiceReplies)
  const lastHeard = useStore(rudikStore, (state) => state.lastHeard)

  const { openMicrophone, closeMicrophone, pushToTalkStart, pushToTalkStop } =
    useVoiceSession()

  const onHotwordChange = useCallback(
    async (value: boolean) => {
      if (value) {
        const ok = await openMicrophone()
        if (!ok) return
        toggleHotword(true)
        setPhase('listening')
      } else {
        toggleHotword(false)
        closeMicrophone()
      }
    },
    [closeMicrophone, openMicrophone],
  )

  // Пробел — «нажми и говори», как рация.
  useEffect(() => {
    const isTyping = (target: EventTarget | null) =>
      target instanceof HTMLElement &&
      (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)

    const down = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || event.repeat || isTyping(event.target)) return
      event.preventDefault()
      void pushToTalkStart()
    }
    const up = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || isTyping(event.target)) return
      event.preventDefault()
      pushToTalkStop()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [pushToTalkStart, pushToTalkStop])

  const recording = phase === 'recording'

  return (
    <div className="flex w-full flex-col items-center gap-4">
      <Button
        type="button"
        size="lg"
        onPointerDown={(event) => {
          // Держим указатель за кнопкой: на телефоне палец легко уезжает
          // за её границы, и pointerup прилетел бы уже другому элементу.
          event.currentTarget.setPointerCapture(event.pointerId)
          void pushToTalkStart()
        }}
        onPointerUp={pushToTalkStop}
        onPointerCancel={pushToTalkStop}
        onContextMenu={(event) => event.preventDefault()}
        className={cn(
          'h-16 w-full max-w-sm touch-none select-none rounded-full text-base font-semibold shadow-lg transition',
          recording
            ? 'bg-[var(--rudn-accent)] text-white hover:bg-[var(--rudn-accent)]'
            : 'bg-[var(--rudn-blue)] text-white hover:bg-[var(--rudn-blue-deep)]',
        )}
      >
        {recording ? <MicOff className="mr-2 size-5" /> : <Mic className="mr-2 size-5" />}
        {recording ? 'Говорите — отпустите, чтобы отправить' : 'Нажмите и говорите (пробел)'}
      </Button>

      <div className="flex w-full max-w-sm flex-col gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-4">
        <label className="flex items-center justify-between gap-3 text-sm">
          <span className="flex items-center gap-2 font-medium">
            <Radio className="size-4 text-[var(--rudn-blue)]" />
            Всегда слушать «Рудик»
          </span>
          <Switch checked={hotword} onCheckedChange={(value) => void onHotwordChange(value)} />
        </label>

        <label className="flex items-center justify-between gap-3 text-sm">
          <span className="flex items-center gap-2 font-medium">
            {voiceReplies ? (
              <Volume2 className="size-4 text-[var(--rudn-blue)]" />
            ) : (
              <VolumeX className="size-4 text-zinc-400" />
            )}
            Отвечать голосом
          </span>
          <Switch checked={voiceReplies} onCheckedChange={(value) => toggleVoiceReplies(value)} />
        </label>

        {hotword && (
          <p className="m-0 text-xs text-[var(--sea-ink-soft)]">
            Скажите «Рудик» и задайте вопрос — например: «Рудик, где кабинет Салтыковой?»
          </p>
        )}
        {lastHeard && (
          <p className="m-0 truncate text-xs text-[var(--sea-ink-soft)]">
            Услышал: «{lastHeard}»
          </p>
        )}
      </div>
    </div>
  )
}

import { useStore } from '@tanstack/react-store'
import { cn } from '#/lib/utils'
import { rudikStore } from '#/lib/rudik-store'

// Готовый арт положите в public/rudik/ и пропишите путь здесь,
// например '/rudik/avatar.png'. По умолчанию используется векторный Рудик.
const AVATAR_SRC = '/rudik/avatar.svg'

const PHASE_LABEL: Record<string, string> = {
  idle: 'Готов помочь',
  listening: 'Слушаю',
  recording: 'Записываю',
  thinking: 'Думаю',
  speaking: 'Отвечаю',
}

/**
 * Аватар Рудика. Кольца вокруг реагируют на громкость микрофона,
 * поэтому по нему сразу видно, слышит ли ассистент собеседника.
 */
export function RudikAvatar({ className }: { className?: string }) {
  const phase = useStore(rudikStore, (state) => state.phase)
  const level = useStore(rudikStore, (state) => state.level)

  const active = phase === 'listening' || phase === 'recording'
  const ring = active ? 1 + level * 0.35 : 1

  return (
    <div className={cn('relative flex flex-col items-center', className)}>
      <div className="relative flex h-64 w-64 items-center justify-center sm:h-80 sm:w-80">
        <div
          aria-hidden
          className={cn(
            'absolute inset-6 rounded-full transition-transform duration-100',
            'bg-[radial-gradient(circle,var(--rudn-glow)_0%,transparent_70%)]',
            phase === 'thinking' && 'animate-pulse',
          )}
          style={{ transform: `scale(${ring})` }}
        />
        <div
          aria-hidden
          className={cn(
            'absolute inset-0 rounded-full border-2 transition-colors',
            active ? 'border-[var(--rudn-accent)]' : 'border-transparent',
            phase === 'speaking' && 'border-[var(--rudn-blue)] animate-pulse',
          )}
        />
        <img
          src={AVATAR_SRC}
          alt="Рудик — виртуальный помощник Инженерной академии РУДН"
          className="relative z-10 h-full w-full object-contain drop-shadow-[0_18px_40px_rgba(26,69,196,0.28)]"
        />
      </div>

      <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-[var(--rudn-blue)]">
        <span
          className={cn(
            'h-2 w-2 rounded-full',
            phase === 'idle' ? 'bg-zinc-400' : 'bg-[var(--rudn-accent)] animate-pulse',
          )}
        />
        {PHASE_LABEL[phase] ?? phase}
      </div>
    </div>
  )
}

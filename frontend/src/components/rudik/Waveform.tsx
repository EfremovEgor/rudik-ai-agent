import { useStore } from '@tanstack/react-store'
import { rudikStore } from '#/lib/rudik-store'

/** Множители высоты столбиков — рисунок эквалайзера из макета. */
const BARS = [0.62, 0.46, 0.88, 0.34, 0.72, 0.55, 0.95, 0.4, 0.78, 0.5, 0.85, 0.36, 0.68]

interface Props {
  /** Слушаем зал (синий) или озвучиваем ответ (зелёный). */
  tone: 'listen' | 'speak'
  /** Столбики живут от громкости микрофона; при озвучке — своим ритмом. */
  reactive?: boolean
}

export function Waveform({ tone, reactive = true }: Props) {
  const level = useStore(rudikStore, (state) => state.level)
  const bars = tone === 'listen' ? BARS : BARS.slice(0, 8)
  const accent = tone === 'listen' ? 'var(--rd-blue)' : 'var(--rd-green)'
  const accentDeep = tone === 'listen' ? 'var(--rd-blue-deep)' : 'var(--rd-green-deep)'

  return (
    <div
      className="flex items-end justify-center gap-[0.6vw]"
      style={{ height: tone === 'listen' ? 'clamp(38px, 5.4vh, 104px)' : 'clamp(30px, 4.4vh, 84px)' }}
      aria-hidden
    >
      {bars.map((weight, index) => {
        // Без микрофона столбики всё равно дышат, чтобы экран не выглядел мёртвым.
        const amplitude = reactive ? 0.22 + level * 1.15 * weight : weight
        return (
          <span
            key={index}
            className="block w-[0.55vw] min-w-[6px] origin-bottom rounded-full transition-transform duration-100 ease-out"
            style={{
              height: '100%',
              background: index % 3 === 2 ? accentDeep : accent,
              transform: `scaleY(${Math.max(0.14, Math.min(1, amplitude))})`,
              transitionDelay: `${index * 8}ms`,
            }}
          />
        )
      })}
    </div>
  )
}

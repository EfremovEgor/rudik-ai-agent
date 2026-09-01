import { useStore } from '@tanstack/react-store'
import { Waveform } from './Waveform'
import { rudikStore } from '#/lib/rudik-store'
import type { Screen } from '#/lib/rudik-store'

/** Своя поза Рудика на каждое состояние экрана. */
const POSE: Record<Screen, { src: string; alt: string; height: string }> = {
  idle: { src: '/rudik/pose-1.png', alt: 'Патрис приветствует', height: '74vh' },
  listening: { src: '/rudik/pose-6.png', alt: 'Патрис слушает', height: '65vh' },
  thinking: { src: '/rudik/pose-7.png', alt: 'Патрис думает', height: '68vh' },
  answer: { src: '/rudik/pose-4.png', alt: 'Патрис отвечает', height: '65vh' },
  error: { src: '/rudik/pose-8.png', alt: 'Патрис не расслышал', height: '72vh' },
  nomic: { src: '/rudik/pose-5.png', alt: 'Патрис недоступен', height: '70vh' },
}

export function AvatarStage() {
  const screen = useStore(rudikStore, (state) => state.screen)
  const pose = POSE[screen]

  return (
    <div className="relative flex w-[34%] max-w-[660px] min-w-[260px] flex-none flex-col items-center justify-end">
      {screen === 'listening' && (
        <>
          <span
            aria-hidden
            className="rud-ring absolute bottom-[12%] left-1/2 aspect-square w-[70%] -translate-x-1/2 rounded-full bg-[rgba(0,121,193,.16)]"
          />
          <span
            aria-hidden
            className="rud-ring absolute bottom-[12%] left-1/2 aspect-square w-[70%] -translate-x-1/2 rounded-full bg-[rgba(0,121,193,.16)]"
            style={{ animationDelay: '1.3s' }}
          />
        </>
      )}

      <img
        src={pose.src}
        alt={pose.alt}
        className={`rud-shadow relative object-contain ${screen === 'idle' ? 'rud-float' : ''} ${
          screen === 'nomic' ? 'opacity-75 grayscale-[.35]' : ''
        }`}
        style={{ height: pose.height }}
      />

      {screen === 'listening' && (
        <div className="relative mt-[1.6vh]">
          <Waveform tone="listen" />
        </div>
      )}

      {screen === 'thinking' && (
        <div className="mt-[2.4vh] flex items-center gap-[1.1vw]" aria-hidden>
          <span className="rud-dot block size-[clamp(10px,1vw,20px)] rounded-full bg-[var(--rd-blue)]" />
          <span
            className="rud-dot block size-[clamp(10px,1vw,20px)] rounded-full bg-[var(--rd-green)]"
            style={{ animationDelay: '.18s' }}
          />
          <span
            className="rud-dot block size-[clamp(10px,1vw,20px)] rounded-full bg-[var(--rd-blue-deep)]"
            style={{ animationDelay: '.36s' }}
          />
        </div>
      )}

      {screen === 'answer' && (
        <div className="mt-[1.4vh] flex flex-col items-center gap-[1.6vh]">
          <Waveform tone="speak" reactive={false} />
          <div className="flex items-center gap-[0.7vw]">
            <span className="block size-[clamp(8px,0.75vw,14px)] rounded-full bg-[var(--rd-green)]" />
            <span className="rd-kicker text-[var(--rd-green-deep)]">Отвечаю голосом</span>
          </div>
        </div>
      )}
    </div>
  )
}

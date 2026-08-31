import { useStore } from '@tanstack/react-store'
import { rudikStore } from '#/lib/rudik-store'
import type { Screen } from '#/lib/rudik-store'

const LABEL: Record<Screen, string> = {
  idle: 'Ожидание',
  listening: 'Слушаю',
  thinking: 'Думаю',
  answer: 'Отвечаю',
  error: 'Не расслышал',
  nomic: 'Нет микрофона',
}

const DOT: Record<Screen, string> = {
  idle: 'var(--rd-blue)',
  listening: 'var(--rd-blue)',
  thinking: 'var(--rd-blue-deep)',
  answer: 'var(--rd-green)',
  error: 'var(--rd-blue)',
  nomic: 'var(--rd-red)',
}

/** Шапка: логотип академии и текущее состояние ассистента. */
export function KioskHeader() {
  const screen = useStore(rudikStore, (state) => state.screen)

  return (
    <header className="relative flex items-center justify-between px-[3.75vw] pt-[4vh]">
      <div className="flex items-center gap-[1.15vw]">
        <span className="text-[clamp(1.6rem,2.4vw,46px)] leading-none font-extrabold tracking-[0.04em] text-[var(--rd-blue)]">
          РУДН
        </span>
        <span className="h-[clamp(28px,4.6vh,50px)] w-[2px] bg-[rgba(0,121,193,.35)]" />
        <span className="text-[clamp(0.7rem,1.1vw,21px)] leading-[1.35] font-semibold tracking-[0.16em] text-[var(--rd-ink)] uppercase">
          Инженерная
          <br />
          академия
        </span>
      </div>

      <div className="flex items-center gap-[0.75vw] rounded-full bg-white px-[1.35vw] py-[1.3vh] shadow-[0_6px_24px_rgba(11,43,64,.08)]">
        <span
          className="block size-[clamp(9px,0.7vw,13px)] rounded-full"
          style={{ background: DOT[screen] }}
        />
        <span className="text-[clamp(0.8rem,1.15vw,22px)] font-semibold tracking-[0.04em] text-[var(--rd-ink)]">
          {LABEL[screen]}
        </span>
      </div>
    </header>
  )
}

/** Подвал: индикатор микрофона и фирменная триколорная полоса. */
export function KioskFooter() {
  const screen = useStore(rudikStore, (state) => state.screen)
  const micReady = useStore(rudikStore, (state) => state.micReady)
  const connected = useStore(rudikStore, (state) => state.connected)

  // Обрыв канала показываем честно: микрофон включён, но Рудик сейчас не слышит.
  const lostLink = micReady && !connected
  const hint =
    screen === 'nomic'
      ? 'Микрофон недоступен'
      : lostLink
        ? 'Нет связи с сервером — восстанавливаю соединение'
        : micReady
          ? 'Микрофон включён — скажите «Рудик»'
          : 'Микрофон выключен'

  return (
    <>
      <div className="relative flex items-center justify-center gap-[0.8vw] px-[3.75vw] pb-[2.4vh]">
        <span
          className="rud-mic block size-[clamp(9px,0.7vw,13px)] rounded-full"
          style={{
            background:
              screen === 'nomic' || lostLink ? 'var(--rd-red)' : 'var(--rd-blue)',
          }}
        />
        <span className="text-[clamp(0.7rem,1vw,19px)] font-medium text-[var(--rd-muted)]">
          {hint}
        </span>
      </div>
      <div className="relative flex h-[clamp(6px,1.1vh,12px)] flex-none">
        <span className="flex-2 bg-[var(--rd-blue)]" />
        <span className="flex-1 bg-[var(--rd-green)]" />
        <span className="flex-1 bg-[var(--rd-red)]" />
      </div>
    </>
  )
}

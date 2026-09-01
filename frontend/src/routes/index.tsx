import { useEffect } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { AvatarStage } from '#/components/rudik/AvatarStage'
import { KioskFooter, KioskHeader } from '#/components/rudik/KioskChrome'
import { StatePanel } from '#/components/rudik/StatePanel'
import { useVoiceStream } from '#/hooks/useVoiceStream'
import { rudikStore } from '#/lib/rudik-store'
import type { Screen } from '#/lib/rudik-store'

/** Демо-режим из макета: ?screen=answer показывает состояние без микрофона. */
const DEMO_SCREENS: Array<Screen> = ['idle', 'listening', 'thinking', 'answer', 'error', 'nomic']
const DEMO_QUESTION = 'Патрис, скажи где кабинет Салтыковой?'
const DEMO_ANSWER =
  'Кабинет Салтыковой Ольги Александровны находится в здании Инженерной академии, 204 и 404.'

export const Route = createFileRoute('/')({
  component: RudikKiosk,
  validateSearch: (search: Record<string, unknown>): { screen?: Screen } => {
    const value = String(search.screen ?? '')
    return DEMO_SCREENS.includes(value as Screen) ? { screen: value as Screen } : {}
  },
  head: () => ({
    meta: [
      { title: 'Патрис — голосовой помощник Инженерной академии РУДН' },
      {
        name: 'description',
        content:
          'Голосовой помощник Инженерной академии РУДН: кабинеты сотрудников, кафедры, направления подготовки и новости.',
      },
    ],
  }),
})

function useDemoScreen(screen: Screen | undefined): void {
  useEffect(() => {
    if (!screen) return
    rudikStore.setState((state) => ({
      ...state,
      screen,
      question: screen === 'idle' || screen === 'listening' ? '' : DEMO_QUESTION,
      answer: screen === 'answer' ? DEMO_ANSWER : '',
      sources: screen === 'answer' ? ['https://academy.rudn.ru/academy/administration'] : [],
      errorText: '',
    }))
  }, [screen])
}

function RudikKiosk() {
  const { startSession } = useVoiceStream()
  useDemoScreen(Route.useSearch().screen)

  return (
    <main className="relative flex h-dvh flex-col overflow-hidden bg-[var(--rd-bg)]">
      {/* Декоративные окружности из макета. */}
      <span
        aria-hidden
        className="pointer-events-none absolute -top-[35vh] -right-[14vw] aspect-square w-[52vw] rounded-full border-2 border-[rgba(0,121,193,.14)]"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute -top-[24vh] -right-[22vw] aspect-square w-[52vw] rounded-full border-2 border-[rgba(0,169,79,.12)]"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute -bottom-[42vh] -left-[13vw] aspect-square w-[43vw] rounded-full border-2 border-[rgba(0,121,193,.12)]"
      />

      <KioskHeader />

      <div className="relative flex min-h-0 flex-1 items-stretch gap-[2.9vw] px-[3.75vw] pt-[1vh]">
        <AvatarStage />
        <StatePanel onStart={() => void startSession()} />
      </div>

      <KioskFooter />
    </main>
  )
}

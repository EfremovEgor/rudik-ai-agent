import { createFileRoute } from '@tanstack/react-router'
import { ChatPanel } from '#/components/rudik/ChatPanel'
import { RudikAvatar } from '#/components/rudik/RudikAvatar'
import { StatusBar } from '#/components/rudik/StatusBar'
import { VoiceControls } from '#/components/rudik/VoiceControls'

export const Route = createFileRoute('/')({
  component: RudikPage,
  head: () => ({
    meta: [
      { title: 'Рудик — помощник Инженерной академии РУДН' },
      {
        name: 'description',
        content:
          'Голосовой ассистент Инженерной академии РУДН: кабинеты сотрудников, кафедры, направления подготовки и новости.',
      },
    ],
  }),
})

function RudikPage() {
  return (
    <main className="page-wrap px-4 pb-10 pt-8">
      <section className="mb-6 flex flex-col gap-3">
        <p className="island-kicker m-0">Инженерная академия РУДН</p>
        <h1 className="display-title m-0 text-3xl leading-tight font-bold tracking-tight text-[var(--sea-ink)] sm:text-5xl">
          Привет! Я Рудик
        </h1>
        <p className="m-0 max-w-2xl text-base text-[var(--sea-ink-soft)]">
          Помогу найти кабинет сотрудника, разобраться в кафедрах и направлениях
          подготовки, расскажу новости академии. Скажите «Рудик» и задайте вопрос
          — или напишите его текстом.
        </p>
        <StatusBar />
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="flex flex-col items-center gap-6 rounded-3xl border border-[var(--line)] bg-[var(--surface)] p-6">
          <RudikAvatar />
          <VoiceControls />
        </div>

        <ChatPanel className="min-h-[520px] lg:h-[calc(100vh-16rem)]" />
      </div>
    </main>
  )
}

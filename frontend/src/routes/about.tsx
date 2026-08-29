import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/about')({
  component: About,
  head: () => ({ meta: [{ title: 'О проекте — Рудик' }] }),
})

const STEPS: Array<[string, string]> = [
  [
    'Сбор данных',
    'Скрипты обходят academy.rudn.ru: дирекцию, кафедры, направления подготовки, приёмную комиссию и новости — и раскладывают страницы на структурированные карточки.',
  ],
  [
    'База знаний',
    'Карточки нарезаются на фрагменты и индексируются гибридно: BM25 по словам плюс мультиязычные векторы. Поиск понимает и точные фамилии, и общие формулировки.',
  ],
  [
    'Агент',
    'LangGraph-агент на Claude выбирает инструмент: найти сотрудника, посмотреть новости, перечислить кафедры или дозагрузить страницу сайта. Ответ всегда со ссылкой на источник.',
  ],
  [
    'Голос',
    'Речь распознаётся локально через faster-whisper, ответ озвучивается синтезом речи. Обращение «Рудик» ищется в расшифровке с поправкой на ошибки распознавания.',
  ],
]

function About() {
  return (
    <main className="page-wrap px-4 pb-10 pt-10">
      <h1 className="display-title m-0 mb-4 text-3xl font-bold tracking-tight text-[var(--sea-ink)] sm:text-4xl">
        Как устроен Рудик
      </h1>
      <p className="mb-8 max-w-2xl text-base text-[var(--sea-ink-soft)]">
        Рудик — виртуальный помощник Инженерной академии РУДН. Он отвечает
        голосом и текстом, опираясь только на данные официального сайта академии.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        {STEPS.map(([title, text], index) => (
          <article
            key={title}
            className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5"
          >
            <p className="island-kicker m-0 mb-2">Шаг {index + 1}</p>
            <h2 className="m-0 mb-2 text-lg font-semibold text-[var(--sea-ink)]">{title}</h2>
            <p className="m-0 text-sm text-[var(--sea-ink-soft)]">{text}</p>
          </article>
        ))}
      </div>

      <section className="mt-8 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <h2 className="m-0 mb-2 text-lg font-semibold text-[var(--sea-ink)]">Стек</h2>
        <p className="m-0 text-sm text-[var(--sea-ink-soft)]">
          Бэкенд: Python, uv, FastAPI, LangChain, LangGraph, Claude API,
          faster-whisper, edge-tts. Фронтенд: React 19, TanStack Start, Router,
          Query и Store, shadcn/ui, Tailwind CSS.
        </p>
      </section>
    </main>
  )
}

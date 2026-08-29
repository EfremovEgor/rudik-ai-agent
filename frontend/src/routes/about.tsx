import { Link, createFileRoute } from '@tanstack/react-router'

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
    'LangGraph-агент на self-hosted Qwen выбирает инструмент: найти сотрудника, посмотреть новости, перечислить кафедры или дозагрузить страницу сайта. Ответ всегда со ссылкой на источник.',
  ],
  [
    'Голос',
    'Речь распознаётся локально через faster-whisper со словарём фамилий академии, ответ озвучивается синтезом речи. Обращение «Рудик» ищется с поправкой на ошибки распознавания.',
  ],
]

function About() {
  return (
    <main className="h-dvh overflow-y-auto bg-[var(--rd-bg)] px-[6vw] py-[6vh]">
      <Link to="/" className="rd-kicker text-[var(--rd-blue)] no-underline">
        ← К ассистенту
      </Link>

      <h1 className="mt-[3vh] mb-[2vh] text-[clamp(1.8rem,3.2vw,58px)] font-extrabold text-[var(--rd-ink)]">
        Как устроен Рудик
      </h1>
      <p className="rd-lead m-0 max-w-[70ch] text-[var(--rd-ink-soft)]">
        Виртуальный помощник Инженерной академии РУДН. Отвечает голосом и
        текстом, опираясь только на данные официального сайта академии.
      </p>

      <div className="mt-[5vh] grid gap-[1.6vw] sm:grid-cols-2">
        {STEPS.map(([title, text], index) => (
          <article
            key={title}
            className="rounded-[24px] bg-white p-[2vw] shadow-[0_10px_30px_rgba(11,43,64,.08)]"
          >
            <p className="rd-kicker m-0 text-[var(--rd-muted)]">Шаг {index + 1}</p>
            <h2 className="mt-[1vh] mb-[1.2vh] text-[clamp(1.05rem,1.6vw,30px)] font-bold text-[var(--rd-ink)]">
              {title}
            </h2>
            <p className="m-0 text-[clamp(0.85rem,1.15vw,22px)] text-[var(--rd-ink-soft)]">{text}</p>
          </article>
        ))}
      </div>

      <section className="mt-[3vh] rounded-[24px] bg-white p-[2vw] shadow-[0_10px_30px_rgba(11,43,64,.08)]">
        <h2 className="m-0 mb-[1.2vh] text-[clamp(1.05rem,1.6vw,30px)] font-bold text-[var(--rd-ink)]">
          Стек
        </h2>
        <p className="m-0 text-[clamp(0.85rem,1.15vw,22px)] text-[var(--rd-ink-soft)]">
          Бэкенд: Python, uv, FastAPI, LangChain, LangGraph, self-hosted Qwen на
          vLLM, faster-whisper, edge-tts. Фронтенд: React 19, TanStack Start,
          Router, Query и Store, shadcn/ui, Tailwind CSS.
        </p>
      </section>
    </main>
  )
}

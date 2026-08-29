import { useEffect, useState } from 'react'
import { useStore } from '@tanstack/react-store'
import { Button } from '#/components/ui/button'
import { rudikStore } from '#/lib/rudik-store'

const EXAMPLES = [
  'Рудик, где кабинет Салтыковой?',
  'Рудик, какие есть кафедры?',
  'Рудик, что нового в академии?',
]

/** Печатает текст по буквам — ответ появляется в такт озвучке. */
function useTypewriter(text: string, msPerChar = 22): string {
  const [shown, setShown] = useState('')

  useEffect(() => {
    if (!text) {
      setShown('')
      return
    }
    setShown(text.slice(0, 1))
    let index = 1
    const timer = setInterval(() => {
      index += 1
      setShown(text.slice(0, index))
      if (index >= text.length) clearInterval(timer)
    }, msPerChar)
    return () => clearInterval(timer)
  }, [text, msPerChar])

  return shown
}

/** Ссылку в конце ответа показываем отдельно, а не читаем вслух. */
function withoutSources(text: string): string {
  return text.replace(/\/\/\s*https?:\/\/\S+/g, '').trim()
}

export function StatePanel({ onStart }: { onStart: () => void }) {
  const screen = useStore(rudikStore, (state) => state.screen)
  const partial = useStore(rudikStore, (state) => state.partial)
  const question = useStore(rudikStore, (state) => state.question)
  const answer = useStore(rudikStore, (state) => state.answer)
  const sources = useStore(rudikStore, (state) => state.sources)
  const errorText = useStore(rudikStore, (state) => state.errorText)
  const typed = useTypewriter(screen === 'answer' ? withoutSources(answer) : '')

  return (
    <section className="flex min-w-0 flex-1 flex-col justify-center pb-[4vh]">
      {screen === 'idle' && (
        <>
          <h1 className="rd-hero m-0 text-[var(--rd-ink)]">
            Привет!
            <br />Я Рудик
          </h1>
          <p className="rd-lead mt-[2.6vh] mb-0 text-[var(--rd-ink-soft)] text-pretty">
            Голосовой помощник Инженерной академии.
            <br />
            Просто скажите «Рудик» и задайте вопрос.
          </p>
          <div className="mt-[4vh] flex flex-col items-start gap-[2vh]">
            <Button
              onClick={onStart}
              className="h-auto rounded-full bg-[var(--rd-blue)] px-[2.4vw] py-[1.8vh] text-[clamp(0.95rem,1.5vw,30px)] font-semibold text-white shadow-[0_14px_40px_rgba(0,121,193,.28)] hover:bg-[var(--rd-blue-deep)]"
            >
              Включить микрофон
            </Button>
            <ul className="m-0 flex list-none flex-col gap-[1.2vh] p-0">
              {EXAMPLES.map((example) => (
                <li
                  key={example}
                  className="rd-note rounded-full bg-white/70 px-[1.4vw] py-[1vh] text-[var(--rd-ink-soft)]"
                >
                  {example}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}

      {screen === 'listening' && (
        <>
          <p className="rd-kicker m-0 text-[var(--rd-blue)]">Слушаю вас</p>
          <div className="mt-[2.8vh] flex min-h-[26vh] items-center rounded-[28px] bg-white px-[2.9vw] py-[5vh] shadow-[0_14px_44px_rgba(11,43,64,.1)]">
            {/* Пока человек говорит, показываем расшифровку на лету. */}
            <p
              className={`rd-answer m-0 text-pretty ${
                partial ? 'text-[var(--rd-ink)]' : 'text-[var(--rd-muted)]'
              }`}
            >
              {partial || 'Скажите «Рудик» и задайте вопрос'}
              <span className="rud-blink ml-[0.4vw] inline-block h-[clamp(20px,2.9vw,54px)] w-[5px] translate-y-[0.12em] bg-[var(--rd-blue)] align-middle" />
            </p>
          </div>
          <p className="rd-note mt-[2.8vh] mb-0 text-[var(--rd-muted)]">
            Говорите обычным голосом — я слышу вас целиком
          </p>
        </>
      )}

      {screen === 'thinking' && (
        <>
          <div className="flex items-center gap-[1.15vw]">
            <span className="rud-spin block size-[clamp(20px,1.9vw,36px)] flex-none rounded-full border-4 border-[rgba(0,121,193,.25)] border-t-[var(--rd-blue)]" />
            <p className="m-0 text-[clamp(1.5rem,3.35vw,64px)] font-extrabold text-[var(--rd-ink)]">
              Ищу ответ…
            </p>
          </div>
          <div className="mt-[3.6vh] rounded-[28px] bg-white/70 px-[2.7vw] py-[4.4vh]">
            <p className="rd-kicker m-0 text-[var(--rd-muted)]">
              {question ? 'Ваш вопрос' : 'Распознаю речь'}
            </p>
            <p className="rd-question mt-[1.8vh] mb-0 text-[var(--rd-ink-soft)] text-pretty">
              {question || 'Секунду — разбираю, что вы сказали…'}
            </p>
          </div>
        </>
      )}

      {screen === 'answer' && (
        <>
          <div className="flex items-center gap-[0.9vw]">
            <span className="rd-kicker text-[var(--rd-muted)]">Ваш вопрос</span>
            <span className="h-[2px] flex-1 bg-[rgba(11,43,64,.1)]" />
          </div>
          <p className="rd-question mt-[1.6vh] mb-0 text-[var(--rd-ink-soft)] text-pretty">
            {question}
          </p>
          <div className="rud-in mt-[3.2vh] rounded-[30px] border-t-[10px] border-[var(--rd-blue)] bg-white px-[2.9vw] py-[5vh] shadow-[0_18px_52px_rgba(11,43,64,.12)]">
            <p className="rd-answer m-0 text-[var(--rd-ink)] text-pretty">{typed}</p>
            {sources.length > 0 && (
              <p className="mt-[2.4vh] mb-0 text-[clamp(0.7rem,1vw,20px)] font-medium text-[var(--rd-muted)] break-all">
                {sources[0]}
              </p>
            )}
          </div>
          <p className="rd-note mt-[3vh] mb-0 text-[var(--rd-muted)]">
            Скажите «Рудик» ещё раз, чтобы задать новый вопрос
          </p>
        </>
      )}

      {screen === 'error' && (
        <>
          <h2 className="m-0 text-[clamp(1.9rem,3.75vw,72px)] leading-[1.1] font-extrabold text-[var(--rd-ink)]">
            Не расслышал
            <br />
            вопрос
          </h2>
          <p className="rd-lead mt-[2.6vh] mb-0 text-[var(--rd-ink-soft)] text-pretty">
            {errorText || 'В холле шумно. Подойдите ближе к экрану и повторите вопрос чуть громче.'}
          </p>
          <div className="mt-[4.2vh] flex items-center gap-[1vw] self-start rounded-[22px] bg-white px-[2.1vw] py-[2.8vh] shadow-[0_10px_30px_rgba(11,43,64,.08)]">
            <span className="rud-mic block size-[clamp(11px,0.85vw,16px)] rounded-full bg-[var(--rd-blue)]" />
            <span className="text-[clamp(0.9rem,1.55vw,30px)] font-semibold text-[var(--rd-blue)]">
              Микрофон включён — говорите
            </span>
          </div>
        </>
      )}

      {screen === 'nomic' && (
        <>
          <div className="flex items-center gap-[0.85vw] self-start rounded-full bg-[#fdeceb] px-[1.6vw] py-[1.8vh]">
            <span className="block size-[clamp(10px,0.8vw,15px)] rounded-full bg-[var(--rd-red)]" />
            <span className="rd-kicker text-[#b32017]">Микрофон недоступен</span>
          </div>
          <h2 className="mt-[2.8vh] text-[clamp(1.8rem,3.55vw,68px)] leading-[1.1] font-extrabold text-[var(--rd-ink)]">
            Сейчас не слышу вас
          </h2>
          <p className="rd-lead mt-[2.4vh] mb-0 text-[var(--rd-ink-soft)] text-pretty">
            {errorText || 'Голосовой ввод временно недоступен.'}
          </p>
          <div className="mt-[4.2vh] flex items-center justify-between gap-[1.25vw] rounded-[22px] bg-white px-[2.1vw] py-[3vh] shadow-[0_10px_30px_rgba(11,43,64,.08)]">
            <span className="text-[clamp(0.9rem,1.55vw,30px)] font-medium text-[var(--rd-ink-soft)]">
              Стойка информации
            </span>
            <span className="text-[clamp(0.9rem,1.55vw,30px)] font-bold text-[var(--rd-ink)]">
              1 этаж, холл
            </span>
          </div>
          <Button
            onClick={onStart}
            variant="outline"
            className="mt-[3vh] h-auto self-start rounded-full px-[2vw] py-[1.5vh] text-[clamp(0.85rem,1.3vw,26px)]"
          >
            Попробовать ещё раз
          </Button>
        </>
      )}
    </section>
  )
}

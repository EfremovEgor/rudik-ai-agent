export default function Footer() {
  const year = new Date().getFullYear()

  return (
    <footer className="mt-12 border-t border-[var(--line)] px-4 pb-10 pt-6 text-[var(--sea-ink-soft)]">
      <div className="page-wrap flex flex-col items-center justify-between gap-2 text-center sm:flex-row sm:text-left">
        <p className="m-0 text-sm">
          &copy; {year} Инженерная академия РУДН. Рудик — учебный проект.
        </p>
        <p className="m-0 text-sm">
          Данные с{' '}
          <a
            href="https://academy.rudn.ru/"
            target="_blank"
            rel="noreferrer"
            className="text-[var(--rudn-blue)] hover:underline"
          >
            academy.rudn.ru
          </a>
        </p>
      </div>
    </footer>
  )
}

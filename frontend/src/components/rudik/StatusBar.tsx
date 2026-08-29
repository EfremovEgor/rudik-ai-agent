import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Brain, Database, Mic, Volume2 } from 'lucide-react'
import { Badge } from '#/components/ui/badge'
import { fetchHealth } from '#/lib/api'

/** Плашка состояния: видно, поднят ли бэкенд, собрана ли база и готов ли голос. */
export function StatusBar() {
  const { data, error, isLoading } = useQuery({
    queryKey: ['rudik', 'health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 30_000,
    retry: 1,
  })

  if (isLoading) {
    return <p className="m-0 text-xs text-[var(--sea-ink-soft)]">Проверяю бэкенд...</p>
  }

  if (error || !data) {
    return (
      <Badge variant="destructive" className="gap-1">
        <AlertTriangle className="size-3" />
        Бэкенд недоступен — запустите uv run rudik-serve
      </Badge>
    )
  }

  const chunks = data.knowledge_base.chunks ?? 0

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Badge variant={data.model_key_configured ? 'secondary' : 'destructive'} className="gap-1">
        <Brain className="size-3" />
        {data.model_key_configured ? data.model : 'нет ANTHROPIC_API_KEY'}
      </Badge>

      <Badge variant={chunks > 0 ? 'secondary' : 'destructive'} className="gap-1">
        <Database className="size-3" />
        {chunks > 0
          ? `база: ${chunks} фрагментов${data.knowledge_base.dense ? ' + векторы' : ''}`
          : 'база пуста'}
      </Badge>

      <Badge variant={data.stt.available ? 'secondary' : 'outline'} className="gap-1">
        <Mic className="size-3" />
        {data.stt.available ? `whisper ${data.stt.model}` : 'распознавание выключено'}
      </Badge>

      <Badge variant={data.tts.available ? 'secondary' : 'outline'} className="gap-1">
        <Volume2 className="size-3" />
        {data.tts.available ? data.tts.voice : 'синтез выключен'}
      </Badge>
    </div>
  )
}

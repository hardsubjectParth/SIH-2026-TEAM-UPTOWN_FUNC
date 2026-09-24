import { useEffect, useRef, useState } from 'react'

// Counts from wherever it currently sits to `value` over 500ms. Interpolates from the
// *previous* displayed value, not from 0, on every change -- a naive version that always
// restarts from 0 would replay the "count up from zero" effect on every SWR poll once a
// stat's true value settles and polling just re-confirms it unchanged (harmless there,
// value === lastValue.current is a no-op) but especially wrong if the real value ticks
// up incrementally over time (e.g. Active Protocols going 3 -> 4): it should count the
// one-unit delta, not visibly drop back to 0 and race back up past the old value.
function useCountUp(value: number, durationMs = 500) {
  const [display, setDisplay] = useState(value)
  const lastValue = useRef(value)
  const mounted = useRef(false)

  useEffect(() => {
    const from = mounted.current ? lastValue.current : 0
    mounted.current = true
    lastValue.current = value
    if (from === value) { setDisplay(value); return }

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setDisplay(value)
      return
    }
    let frame: number
    const start = performance.now()
    function tick(now: number) {
      const progress = Math.min((now - start) / durationMs, 1)
      const eased = 1 - (1 - progress) ** 3
      setDisplay(Math.round(from + (value - from) * eased))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, durationMs])

  return display
}

type StatCardProps = { label: string; value: number | string; accent?: boolean; suffix?: string; note?: string }

// Same anatomy as the dashboard's MetricTile -- micro-label, then the figure, then an
// optional note -- so the stat row on Agent Tasks and the one on the overview read as
// one component. They used to be mirror images of each other: this one put the number
// first and the label under it, which made the two pages look like different products.
function StatCard({ label, value, accent = false, suffix = '', note }: StatCardProps) {
  const isNumeric = typeof value === 'number'
  const animated = useCountUp(isNumeric ? value : 0)
  return (
    <div className="work-panel flex min-w-0 flex-col px-4 py-5 sm:px-6 sm:py-6">
      <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-muted-foreground">{label}</p>
      <p className={`stat-number mt-4 text-[30px] leading-none tracking-[-0.06em] sm:text-[36px] ${accent ? 'text-accent' : 'text-foreground'}`}>
        {isNumeric ? animated : value}{suffix}
      </p>
      {note ? <p className="mt-auto pt-2 text-[11px] text-muted-foreground">{note}</p> : null}
    </div>
  )
}

export default StatCard

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

type StatCardProps = { label: string; value: number | string; accent?: boolean; suffix?: string }

function StatCard({ label, value, accent = false, suffix = '' }: StatCardProps) {
  const isNumeric = typeof value === 'number'
  const animated = useCountUp(isNumeric ? value : 0)
  return (
    <div className="work-panel px-4 py-4">
      <p className={`stat-number text-2xl font-semibold ${accent ? 'text-accent' : 'text-foreground'}`}>
        {isNumeric ? animated : value}{suffix}
      </p>
      <p className="label-micro mt-1.5">{label}</p>
    </div>
  )
}

export default StatCard

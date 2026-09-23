function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0
  return (
    <div className="h-1 w-full overflow-hidden bg-white/8">
      <div className="h-full bg-accent transition-[width] duration-400 ease-out" style={{ width: `${pct}%` }} />
    </div>
  )
}

export default ProgressBar

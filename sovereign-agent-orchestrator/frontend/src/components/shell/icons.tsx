// Minimal dependency-free line icons -- no icon library added just for four glyphs.
type IconProps = { className?: string }

const base = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

export function OverviewIcon({ className }: IconProps) {
  return <svg viewBox="0 0 20 20" width="16" height="16" className={className} {...base}><rect x="2.5" y="2.5" width="6" height="6" rx="1" /><rect x="11.5" y="2.5" width="6" height="6" rx="1" /><rect x="2.5" y="11.5" width="6" height="6" rx="1" /><rect x="11.5" y="11.5" width="6" height="6" rx="1" /></svg>
}

export function FeedIcon({ className }: IconProps) {
  return <svg viewBox="0 0 20 20" width="16" height="16" className={className} {...base}><path d="M3 4h14v9H8l-4 3v-3H3z" /></svg>
}

export function KnowledgeIcon({ className }: IconProps) {
  return <svg viewBox="0 0 20 20" width="16" height="16" className={className} {...base}><path d="M3 5a2 2 0 0 1 2-2h4v14H5a2 2 0 0 1-2-2z" /><path d="M17 5a2 2 0 0 0-2-2h-4v14h4a2 2 0 0 0 2-2z" /></svg>
}

export function TasksIcon({ className }: IconProps) {
  return <svg viewBox="0 0 20 20" width="16" height="16" className={className} {...base}><rect x="3" y="3" width="14" height="14" /><path d="M6.5 10l2 2 4.5-4.5" /></svg>
}

export function ArtifactsIcon({ className }: IconProps) {
  return <svg viewBox="0 0 20 20" width="16" height="16" className={className} {...base}><path d="M6 2h6l3 3v13H6z" /><path d="M12 2v3h3" /></svg>
}

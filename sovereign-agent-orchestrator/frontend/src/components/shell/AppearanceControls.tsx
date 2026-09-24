import * as React from 'react'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

type Appearance = { theme: 'dark' | 'light'; magnification: number; setMagnification: (value: number) => void; toggleTheme: () => void }
const AppearanceContext = createContext<Appearance | null>(null)
const DEFAULT_MAGNIFICATION = 100
const MIN_MAGNIFICATION = 50
const MAX_MAGNIFICATION = 150
// Zoom moves in fixed increments rather than a free-running slider, so it always
// lands on a round number and 100% is reachable by pressing a button.
const MAGNIFICATION_STEP = 5

function snap(value: number) {
  const stepped = Math.round(value / MAGNIFICATION_STEP) * MAGNIFICATION_STEP
  return Math.min(MAX_MAGNIFICATION, Math.max(MIN_MAGNIFICATION, stepped))
}

function readPreference(key: string) {
  return document.cookie.split('; ').find((entry) => entry.startsWith(`${key}=`))?.split('=')[1]
}

function savePreference(key: string, value: string) {
  document.cookie = `${key}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => readPreference('sovereign-theme') === 'light' ? 'light' : 'dark')
  const [magnification, setMagnificationState] = useState(() => {
    const saved = Number(readPreference('sovereign-magnification'))
    // A value left behind by the old slider can sit off-step; snap it on the way in.
    return Number.isFinite(saved) && saved > 0 ? snap(saved) : DEFAULT_MAGNIFICATION
  })

  React.useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    savePreference('sovereign-theme', theme)
  }, [theme])

  React.useLayoutEffect(() => {
    document.documentElement.style.setProperty('--main-window-zoom', String(magnification / 100))
    savePreference('sovereign-magnification', String(magnification))
  }, [magnification])

  const setMagnification = (value: number) => setMagnificationState(snap(value))

  return <AppearanceContext.Provider value={{ theme, magnification, setMagnification, toggleTheme: () => setTheme((current) => current === 'dark' ? 'light' : 'dark') }}>{children}</AppearanceContext.Provider>
}

function useAppearance() {
  const context = useContext(AppearanceContext)
  if (!context) throw new Error('AppearanceControls must be used within AppearanceProvider')
  return context
}

export default function AppearanceControls() {
  const { theme, magnification, setMagnification, toggleTheme } = useAppearance()
  const [zoomOpen, setZoomOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!zoomOpen) return
    function handlePointerDown(event: PointerEvent) {
      if (!popoverRef.current?.contains(event.target as Node)) setZoomOpen(false)
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      setZoomOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [zoomOpen])

  const atMin = magnification <= MIN_MAGNIFICATION
  const atMax = magnification >= MAX_MAGNIFICATION

  return <div className="appearance-controls flex items-center gap-1 rounded-full p-1" role="group" aria-label="Display preferences">
    <div ref={popoverRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setZoomOpen((open) => !open)}
        className="appearance-control flex size-9 items-center justify-center rounded-full"
        aria-haspopup="dialog"
        aria-expanded={zoomOpen}
        aria-label={`Zoom, currently ${magnification} percent`}
        title={`Zoom · ${magnification}%`}
      >
        <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.6-4.6M7.8 10.5h5.4"/></svg>
      </button>

      {zoomOpen ? (
        <div className="appearance-popover absolute right-0 top-full z-50 mt-2 w-44 p-3" role="dialog" aria-label="Zoom">
          <span className="text-[10px] uppercase tracking-[0.09em] text-muted-foreground">Zoom</span>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMagnification(magnification - MAGNIFICATION_STEP)}
              disabled={atMin}
              className="zoom-step flex size-8 shrink-0 items-center justify-center"
              aria-label={`Zoom out to ${Math.max(MIN_MAGNIFICATION, magnification - MAGNIFICATION_STEP)} percent`}
            >
              <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M5 12h14"/></svg>
            </button>
            <output className="flex-1 text-center text-sm tabular-nums text-foreground" aria-live="polite">{magnification}%</output>
            <button
              type="button"
              onClick={() => setMagnification(magnification + MAGNIFICATION_STEP)}
              disabled={atMax}
              className="zoom-step flex size-8 shrink-0 items-center justify-center"
              aria-label={`Zoom in to ${Math.min(MAX_MAGNIFICATION, magnification + MAGNIFICATION_STEP)} percent`}
            >
              <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
            </button>
          </div>
          <button
            type="button"
            onClick={() => setMagnification(DEFAULT_MAGNIFICATION)}
            disabled={magnification === DEFAULT_MAGNIFICATION}
            className="zoom-reset mt-2.5 w-full rounded-lg py-1.5 text-[11px]"
          >
            Reset to 100%
          </button>
        </div>
      ) : null}
    </div>

    <button type="button" onClick={toggleTheme} className="appearance-control flex size-9 items-center justify-center rounded-full" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
      {theme === 'dark' ? <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg> : <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M20.5 15.4A9 9 0 0 1 8.6 3.5 9 9 0 1 0 20.5 15.4Z"/></svg>}
    </button>
  </div>
}

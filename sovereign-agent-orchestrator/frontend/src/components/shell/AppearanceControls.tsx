import * as React from 'react'
import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

type Appearance = { theme: 'dark' | 'light'; magnification: number; setMagnification: (value: number) => void; toggleTheme: () => void }
const AppearanceContext = createContext<Appearance | null>(null)
const DEFAULT_MAGNIFICATION = 100
const MIN_MAGNIFICATION = 50
const MAX_MAGNIFICATION = 150

function readPreference(key: string) {
  return document.cookie.split('; ').find((entry) => entry.startsWith(`${key}=`))?.split('=')[1]
}

function savePreference(key: string, value: string) {
  document.cookie = `${key}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => readPreference('sovereign-theme') === 'light' ? 'light' : 'dark')
  const [magnification, setMagnification] = useState(() => {
    const saved = Number(readPreference('sovereign-magnification'))
    return Number.isFinite(saved) && saved >= MIN_MAGNIFICATION && saved <= MAX_MAGNIFICATION ? saved : DEFAULT_MAGNIFICATION
  })

  React.useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    savePreference('sovereign-theme', theme)
  }, [theme])

  React.useLayoutEffect(() => {
    document.documentElement.style.setProperty('--main-window-zoom', String(magnification / 100))
    savePreference('sovereign-magnification', String(magnification))
  }, [magnification])

  return <AppearanceContext.Provider value={{ theme, magnification, setMagnification, toggleTheme: () => setTheme((current) => current === 'dark' ? 'light' : 'dark') }}>{children}</AppearanceContext.Provider>
}

function useAppearance() {
  const context = useContext(AppearanceContext)
  if (!context) throw new Error('AppearanceControls must be used within AppearanceProvider')
  return context
}

export default function AppearanceControls() {
  const { theme, magnification, setMagnification, toggleTheme } = useAppearance()
  return <div className="appearance-controls flex items-center gap-2 rounded-full p-1" role="group" aria-label="Display preferences">
    <label className="flex items-center gap-1.5 px-1.5" title={`Zoom level · ${magnification}%`}>
      <span className="sr-only">Zoom level</span>
      <input id="zoom-slider" type="range" min={MIN_MAGNIFICATION} max={MAX_MAGNIFICATION} step="1" value={magnification} onChange={(event) => setMagnification(Number(event.target.value))} className="zoom-slider w-20 cursor-pointer accent-[var(--color-accent)] sm:w-24" aria-label={`Zoom level, ${magnification}%`} />
      <output className="w-9 text-right text-[10px] leading-none tabular-nums" htmlFor="zoom-slider">{magnification}%</output>
    </label>
    <button type="button" onClick={toggleTheme} className="appearance-control flex size-9 items-center justify-center rounded-full" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
      {theme === 'dark' ? <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg> : <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M20.5 15.4A9 9 0 0 1 8.6 3.5 9 9 0 1 0 20.5 15.4Z"/></svg>}
    </button>
  </div>
}

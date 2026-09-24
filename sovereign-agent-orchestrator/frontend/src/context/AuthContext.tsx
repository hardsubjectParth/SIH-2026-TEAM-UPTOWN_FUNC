import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { devLogin, UNAUTHORIZED_EVENT, type User } from '../services/api'
import { RANK } from '../components/shell/rank'

type AuthContextType = {
  token: string | null
  user: User | null
  isLoggedIn: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

type Session = { token: string; user: User; expiresAt: number }

const SESSION_KEY = 'sovereign-dev-session'
// Opt-in, matching services/api.ts. As `import.meta.env.DEV` this bypassed
// authentication entirely whenever the console ran under `npm run dev`: login
// fabricated a session from the email's local part without ever checking the
// password, and anything unrecognised silently became an administrator.
const PREVIEW_MODE = import.meta.env.VITE_PREVIEW_DATA === 'true'
const PREVIEW_ROLES = new Set<User['role']>(['admin', 'higher', 'lower'])
const AuthContext = createContext<AuthContextType | undefined>(undefined)

function readStoredSession(): Session | null {
  try {
    const stored = sessionStorage.getItem(SESSION_KEY)
    if (!stored) return null
    const parsed = JSON.parse(stored) as Partial<Session>
    const valid = parsed.token && parsed.user && Object.hasOwn(RANK, parsed.user.role)
      && typeof parsed.expiresAt === 'number' && parsed.expiresAt > Date.now()
    if (!valid) { sessionStorage.removeItem(SESSION_KEY); return null }
    return parsed as Session
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(readStoredSession)

  useEffect(() => {
    if (!session) return
    const clear = () => { sessionStorage.removeItem(SESSION_KEY); setSession(null) }
    const timer = window.setTimeout(clear, Math.max(0, session.expiresAt - Date.now()))
    window.addEventListener(UNAUTHORIZED_EVENT, clear)
    return () => { window.clearTimeout(timer); window.removeEventListener(UNAUTHORIZED_EVENT, clear) }
  }, [session])

  const value = useMemo<AuthContextType>(() => ({
    token: session?.token ?? null,
    user: session?.user ?? null,
    isLoggedIn: Boolean(session),
    login: async (email, password) => {
      if (PREVIEW_MODE) {
        const requestedRole = email.trim().toLowerCase().split('@')[0]
        const role = PREVIEW_ROLES.has(requestedRole as User['role']) ? requestedRole as User['role'] : 'admin'
        const next: Session = {
          token: `preview-${role}-token`,
          user: { id: `preview-${role}`, role, tenant_id: 'preview-tenant' },
          expiresAt: Date.now() + 1000 * 60 * 60 * 8,
        }
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(next))
        setSession(next)
        return
      }
      const result = await devLogin(email, password)
      const next: Session = { token: result.access_token, user: result.user, expiresAt: Date.now() + result.expires_in * 1000 }
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(next))
      setSession(next)
    },
    logout: () => { sessionStorage.removeItem(SESSION_KEY); setSession(null) },
  }), [session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

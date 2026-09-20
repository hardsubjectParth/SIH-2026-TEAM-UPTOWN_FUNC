import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'

// The backend's dev-login only recognizes three fixed accounts (admin/higher/lower --
// app/dev_auth.py), not an arbitrary email. A free-text "protocol identifier" field
// per the mockup would just fail against the real auth -- kept the console styling,
// swapped the input for the same role selector the working login already used.
const ACCOUNTS = [
  { value: 'admin', label: 'admin@sovereign.io' },
  { value: 'higher', label: 'higher@sovereign.io' },
  { value: 'lower', label: 'lower@sovereign.io' },
]

function Login() {
  const { isLoggedIn, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [unlocking, setUnlocking] = useState(false)

  if (isLoggedIn && !unlocking) return <Navigate to="/app/feed" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      setUnlocking(true)
      window.setTimeout(() => navigate('/app/feed', { replace: true }), 220)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to sign in')
      setSubmitting(false)
    }
  }

  const fieldClass =
    'w-full rounded-xl border border-white/8 bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-accent/50'

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-6 py-12">
      {/* Concentric halo bleeding off the top-left corner, per the mockup. */}
      <div
        className="pointer-events-none absolute -top-40 -left-40 h-[620px] w-[620px] rounded-full opacity-60"
        style={{ background: 'radial-gradient(circle, rgba(143,184,156,0.07), transparent 62%)' }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(ellipse at center, rgba(143,184,156,0.045), transparent 60%)' }}
      />

      <motion.div
        animate={unlocking ? { scale: 0.98, opacity: 0 } : { scale: 1, opacity: 1 }}
        transition={{ duration: 0.2 }}
        className="relative w-full max-w-[420px]"
      >
        <div className="text-center">
          <h1 className="font-display text-[34px] leading-none font-bold tracking-tight text-foreground">Sovereign AI</h1>
          <p className="label-wide mt-4">Intelligence Protocol Access</p>
        </div>

        <div className="mt-10 rounded-2xl bg-surface/40 p-6">
          <div className="border-hairline rounded-2xl bg-surface px-8 py-9">
            <h2 className="font-display text-[22px] leading-tight font-semibold text-foreground">Authorization Required</h2>

            <form onSubmit={handleSubmit} className="mt-7 flex flex-col gap-5">
              <label className="flex flex-col gap-2.5">
                <span className="label-micro">Protocol Identifier</span>
                <select value={username} onChange={(event) => setUsername(event.target.value)} className={fieldClass}>
                  {ACCOUNTS.map((account) => <option value={account.value} key={account.value}>{account.label}</option>)}
                </select>
              </label>

              <label className="flex flex-col gap-2.5">
                <span className="label-micro">Access Token</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  autoComplete="current-password"
                  className={fieldClass}
                  style={{ letterSpacing: password ? '0.25em' : 'normal' }}
                />
              </label>

              {error ? <p className="text-xs text-danger" role="alert">{error}</p> : null}

              <button
                type="submit"
                disabled={submitting}
                className="mt-1 rounded-xl bg-primary px-4 py-3.5 text-sm font-semibold text-primary-foreground transition hover:bg-primary-hover hover:shadow-[0_0_24px_rgba(60,90,71,0.55)] disabled:opacity-60"
              >
                {submitting ? 'Initializing…' : 'Initialize Session'}
              </button>
            </form>

            <div className="mt-7 border-t border-white/7 pt-6 text-center">
              <p className="text-[13px] text-muted-foreground">New agent?</p>
              <p className="mt-1 text-[15px] text-foreground">Request Access Protocol</p>
            </div>
          </div>

          <div className="mt-7 flex items-center justify-center gap-10">
            <span className="label-wide">Sovereign OS v4.2.0</span>
            <span className="label-wide flex items-center gap-2">
              <span
                className="h-1.5 w-1.5 animate-status-pulse rounded-full bg-accent"
                style={{ boxShadow: '0 0 6px var(--color-accent)' }}
              />
              Secure Connection Active
            </span>
          </div>
        </div>
      </motion.div>
    </main>
  )
}

export default Login

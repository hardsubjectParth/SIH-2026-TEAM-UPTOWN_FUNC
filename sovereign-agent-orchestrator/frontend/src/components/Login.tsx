import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'
import AppearanceControls from './shell/AppearanceControls'

function Login() {
  const { isLoggedIn, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [unlocking, setUnlocking] = useState(false)

  if (isLoggedIn && !unlocking) return <Navigate to="/app" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password)
      setUnlocking(true)
      window.setTimeout(() => navigate('/app', { replace: true }), 220)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to sign in')
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page flex min-h-screen flex-col text-foreground">
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-5 sm:px-10">
        <div className="flex items-center gap-3"><span aria-hidden="true" className="brand-mark flex size-9 items-center justify-center border border-accent/40 bg-[#36242a] font-mono font-semibold text-accent">S/</span><div><p className="text-[13px] font-semibold tracking-[0.01em]">SOVEREIGN</p><p className="font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground">Operations / AI</p></div></div>
        <AppearanceControls />
      </header>
      <div className="mx-auto grid w-full max-w-[1240px] flex-1 items-center gap-12 px-6 py-12 sm:px-10 md:grid-cols-[minmax(0,1fr)_minmax(350px,0.9fr)] md:gap-10 lg:gap-20 lg:py-20">
        <div className="hidden max-w-[570px] flex-col items-start md:flex">
          <p className="label-micro text-accent">A considered way to work</p>
          <h2 className="mt-6 text-[clamp(3.3rem,6vw,5.8rem)] font-medium leading-[1.03] tracking-[-0.065em]">Intelligence,<br />under your<br /><span className="text-accent">control.</span></h2>
          <p className="mt-8 max-w-sm border-l border-accent/45 pl-5 text-sm leading-7 text-muted-foreground">One workspace for your tasks, knowledge, reviews and generated work. Every action remains visible in context.</p>
          <div className="mt-16 flex w-full items-center gap-4 border-t border-white/10 pt-5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"><span className="text-accent">01 / Access</span><span className="h-px flex-1 bg-white/10" /><span>02 / Workspace</span></div>
        </div>
        <motion.section
          animate={unlocking ? { y: -8, opacity: 0 } : { y: 0, opacity: 1 }}
          transition={{ duration: 0.2 }}
          aria-labelledby="sign-in-title"
          className="protocol-surface w-full px-6 py-8 sm:px-9 sm:py-10"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-5"><p className="label-micro text-accent">Sign in / 01</p><span aria-hidden="true" className="font-mono text-xs text-accent/60">S / OS</span></div>
          <h1 id="sign-in-title" className="mt-9 text-[32px] font-medium tracking-[-0.045em]">Welcome back<span className="text-accent">.</span></h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Use your account credentials to enter the workspace.</p>
          <form onSubmit={handleSubmit} className="mt-9 flex flex-col gap-5">
            <label className="flex flex-col gap-2"><span className="font-mono text-[10px] uppercase tracking-[0.13em] text-muted-foreground">Email address</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="username" placeholder="name@organization.com" className="w-full rounded-full border border-accent/20 bg-[#0c0d10]/85 px-5 py-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-accent/70" /></label>
            <label className="flex flex-col gap-2"><span className="font-mono text-[10px] uppercase tracking-[0.13em] text-muted-foreground">Password</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required autoComplete="current-password" placeholder="Enter your password" className="w-full rounded-full border border-accent/20 bg-[#0c0d10]/85 px-5 py-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-accent/70" /></label>
            {error ? <p className="border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger" role="alert">{error}</p> : null}
            <button type="submit" disabled={submitting} className="action-primary mt-2 w-full px-4 py-3 text-sm">{submitting ? 'Signing in…' : 'Enter workspace'} <span aria-hidden="true">→</span></button>
          </form>
          <p className="mt-9 border-t border-white/10 pt-5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Access level is assigned to your account.</p>
        </motion.section>
      </div>
      <footer className="flex justify-between border-t border-white/10 px-6 py-4 font-mono text-[10px] uppercase tracking-widest text-muted-foreground sm:px-10"><span>Sovereign / Operations</span><span>Private workspace</span></footer>
    </main>
  )
}

export default Login

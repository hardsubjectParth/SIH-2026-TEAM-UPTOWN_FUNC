import { NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { useConversations } from '../../hooks/useConversations'
import { RANK } from './rank'
import { OverviewIcon, FeedIcon, KnowledgeIcon, TasksIcon, ArtifactsIcon } from './icons'
import { createConversation } from '../../services/api'
import type { Conversation, Role } from '../../types/api'

const NAV = (role: Role) => [
  { to: '/app', label: 'Overview', Icon: OverviewIcon, end: true },
  { to: '/app/feed', label: 'Intelligence Feed', Icon: FeedIcon, end: false },
  { to: '/app/tasks', label: role === 'lower' ? 'My Tasks' : 'Agent Tasks', Icon: TasksIcon, end: false },
  { to: '/app/knowledge', label: 'Knowledge Base', Icon: KnowledgeIcon, end: false },
  { to: '/app/artifacts', label: role === 'lower' ? 'My Artifacts' : 'Artifacts', Icon: ArtifactsIcon, end: false },
]

function groupSessions(conversations: Conversation[]) {
  const today: Conversation[] = []
  const previous7: Conversation[] = []
  const older: Conversation[] = []
  const now = Date.now()
  for (const conversation of conversations) {
    const date = new Date(conversation.updated_at)
    if (date.toDateString() === new Date(now).toDateString()) today.push(conversation)
    else if (now - date.getTime() <= 7 * 24 * 60 * 60 * 1000) previous7.push(conversation)
    else older.push(conversation)
  }
  return { today, previous7, older }
}

function Sidebar() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const { conversations, mutate } = useConversations()
  const [error, setError] = useState<string | null>(null)
  const { today, previous7, older } = groupSessions(conversations)
  const rank = user ? RANK[user.role] : RANK.lower

  function signOut() {
    logout()
    navigate('/login', { replace: true })
  }

  async function newSession() {
    if (!token) return
    setError(null)
    try {
      const created = await createConversation(token, 'New session')
      mutate()
      navigate(`/app/feed/${created.data.id}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to create session')
    }
  }

  const sessionGroups: Array<[string, Conversation[]]> = [
    ['Today', today], ['Previous 7 Days', previous7],
    ...(older.length ? [['Earlier', older] as [string, Conversation[]]] : []),
  ]

  return (
    <aside className="sidebar-shell relative z-10 flex w-full shrink-0 flex-col border-b border-rule bg-[#111216]/90 backdrop-blur-xl md:h-dvh md:w-[244px] md:border-r md:border-b-0 lg:w-[256px]">
      <div className="flex items-center justify-between border-b border-rule px-5 py-4 md:px-5 md:py-7">
        <div className="flex items-center gap-3"><span aria-hidden="true" className="brand-mark flex size-9 items-center justify-center border border-accent/40 bg-[#36242a] font-mono text-base font-semibold text-accent">S<span className="mb-3 text-[9px]">/</span></span><div><h1 className="text-[13px] font-semibold tracking-[0.01em] text-foreground">SOVEREIGN</h1><p className="font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground">Operations / AI</p></div></div>
        <button type="button" onClick={signOut} className="rounded-full border border-rule-strong bg-fill px-3 py-1.5 text-[11px] text-muted-foreground hover:text-foreground md:hidden">Sign out</button>
      </div>

      <p className="label-micro hidden px-6 pt-6 pb-3 md:block">Workspace</p>
      <nav className="flex gap-1 overflow-x-auto px-4 pb-3 md:flex-col md:gap-0.5 md:overflow-visible md:px-3 md:pb-0" aria-label="Main navigation">
        {NAV(user?.role ?? 'lower').map(({ to, label, Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `flex shrink-0 items-center gap-3 rounded-full border px-3 py-2.5 text-xs font-medium transition-colors md:text-[13px] ${isActive ? 'border-accent/25 bg-[#59343c]/35 text-foreground shadow-[inset_0_1px_0_rgba(255,223,201,0.12)]' : 'border-transparent text-muted-foreground hover:bg-fill hover:text-foreground'}`}>
            <Icon className="size-4 text-accent/70" /><span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="mt-8 hidden flex-col overflow-hidden border-t border-rule px-5 pt-5 md:flex">
        <div className="flex items-center justify-between"><p className="label-micro">Recent sessions</p><button type="button" onClick={newSession} className="flex size-8 items-center justify-center rounded-full border border-accent/35 bg-accent/8 text-lg leading-none text-accent hover:bg-accent/20" aria-label="New session">+</button></div>
        {error ? <p role="alert" className="mt-2 text-xs text-danger">{error}</p> : null}
      </div>
      <div className="mt-3 hidden min-h-0 flex-1 overflow-y-auto px-4 md:block">
        {sessionGroups.map(([heading, items]) => items.length ? (
          <div key={heading} className="mb-5"><p className="label-micro mb-2 px-2 text-[9px]">{heading}</p><div className="flex flex-col gap-0.5">{items.slice(0, 12).map((conversation) => <NavLink key={conversation.id} to={`/app/feed/${conversation.id}`} className={({ isActive }) => `block truncate rounded-full px-3 py-2 text-xs transition-colors ${isActive ? 'bg-fill-strong text-foreground' : 'text-muted-foreground hover:bg-fill hover:text-foreground'}`}>{conversation.title}</NavLink>)}</div></div>
        ) : null)}
        {conversations.length === 0 ? <p className="px-2 text-xs text-muted-foreground">No sessions yet.</p> : null}
      </div>

      <div className="mt-auto hidden border-t border-rule p-4 md:block">
        <div className="flex items-center gap-3 rounded-2xl border border-accent/15 bg-fill p-3"><span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/25 bg-accent/10 font-mono text-xs text-accent">{rank.name[0]}</span><div className="min-w-0"><p className="truncate text-xs font-medium text-foreground">{rank.name}</p><p className="truncate text-[10px] text-muted-foreground">{rank.subtitle}</p></div></div>
        <button type="button" onClick={signOut} className="mt-2 w-full px-1 py-2 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground transition hover:text-foreground">Sign out <span aria-hidden="true">→</span></button>
      </div>
    </aside>
  )
}

export default Sidebar

import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'
import { useConversations } from '../../hooks/useConversations'
import { RANK } from './rank'
import { FeedIcon, KnowledgeIcon, TasksIcon, ArtifactsIcon, SearchIcon, ChatIcon, KebabIcon } from './icons'
import Avatar from '../shared/Avatar'
import { createConversation } from '../../services/api'
import type { Conversation } from '../../types/api'

const NAV = [
  { to: '/app/feed', label: 'Intelligence Feed', Icon: FeedIcon },
  { to: '/app/knowledge', label: 'Knowledge Base', Icon: KnowledgeIcon },
  { to: '/app/tasks', label: 'Agent Tasks', Icon: TasksIcon },
  { to: '/app/artifacts', label: 'Artifacts', Icon: ArtifactsIcon },
]

function isToday(iso: string) {
  const date = new Date(iso)
  const now = new Date()
  return date.toDateString() === now.toDateString()
}

function isWithinDays(iso: string, days: number) {
  const diff = Date.now() - new Date(iso).getTime()
  return diff >= 0 && diff <= days * 24 * 60 * 60 * 1000
}

function groupSessions(conversations: Conversation[]) {
  const today: Conversation[] = []
  const previous7: Conversation[] = []
  const older: Conversation[] = []
  for (const conversation of conversations) {
    if (isToday(conversation.updated_at)) today.push(conversation)
    else if (isWithinDays(conversation.updated_at, 7)) previous7.push(conversation)
    else older.push(conversation)
  }
  return { today, previous7, older }
}

function Sidebar() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const { conversations, mutate } = useConversations()
  const [query, setQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const rank = user ? RANK[user.role] : RANK.lower

  const matching = query.trim()
    ? conversations.filter((conversation) => conversation.title.toLowerCase().includes(query.trim().toLowerCase()))
    : conversations
  const { today, previous7, older } = groupSessions(matching)

  function signOut() {
    logout()
    navigate('/login', { replace: true })
  }

  async function newSession() {
    if (!token) return
    const created = await createConversation(token, 'New session')
    mutate()
    navigate(`/app/feed/${created.data.id}`)
  }

  const sessionGroups: Array<[string, Conversation[]]> = [
    ['Today', today],
    ['Previous 7 Days', previous7],
    ...(older.length ? [['Earlier', older] as [string, Conversation[]]] : []),
  ]

  return (
    <aside className="flex h-screen w-[264px] shrink-0 flex-col border-r border-white/7 bg-black/30">
      <div className="px-6 pt-7 pb-6">
        <h1 className="font-display text-[19px] font-bold tracking-tight text-foreground">Sovereign AI</h1>
      </div>

      <nav className="flex flex-col gap-1 px-3" aria-label="Main navigation">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'bg-surface-raised font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-surface hover:text-foreground'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive ? (
                  <motion.span layoutId="nav-active" className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-accent" />
                ) : null}
                <Icon className={isActive ? 'text-accent' : ''} />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 pt-6">
        <label className="border-hairline flex items-center gap-2 rounded-xl bg-surface px-3 py-2 focus-within:border-accent/40">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sessions..."
            aria-label="Search sessions"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
          />
          <SearchIcon size={14} className="shrink-0 text-muted-foreground" />
        </label>
      </div>

      <div className="flex items-center justify-between px-6 pt-6 pb-2">
        <span className="label-micro">Archive</span>
        <button type="button" onClick={newSession} className="label-micro text-accent transition hover:text-foreground">
          New Session
        </button>
      </div>

      <div className="scroll-slim min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {sessionGroups.map(([heading, items]) =>
          items.length ? (
            <div key={heading} className="mb-4">
              <p className="label-micro mb-1 px-3">{heading}</p>
              <div className="flex flex-col gap-0.5">
                {items.map((conversation) => (
                  <NavLink
                    key={conversation.id}
                    to={`/app/feed/${conversation.id}`}
                    className={({ isActive }) =>
                      `relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] transition-colors ${
                        isActive ? 'bg-surface-raised text-foreground' : 'text-foreground/75 hover:bg-surface hover:text-foreground'
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive ? (
                          <motion.span layoutId="session-active" className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-accent" />
                        ) : null}
                        <ChatIcon size={14} className="shrink-0 text-muted-foreground" />
                        <span className="truncate">{conversation.title}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ) : null,
        )}
        {matching.length === 0 ? (
          <p className="px-3 text-xs text-muted-foreground">{query.trim() ? 'No matching sessions.' : 'No sessions yet.'}</p>
        ) : null}
      </div>

      <div className="relative border-t border-white/7 p-4">
        {menuOpen ? (
          <div className="border-hairline absolute right-4 bottom-[76px] left-4 overflow-hidden rounded-xl bg-surface-raised">
            <button
              type="button"
              onClick={signOut}
              className="w-full px-3.5 py-2.5 text-left text-[13px] text-foreground transition hover:bg-white/5"
            >
              Sign out
            </button>
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-label="Account menu"
          className="border-hairline flex w-full items-center gap-3 rounded-xl bg-surface px-3 py-2.5 text-left transition hover:border-white/12"
        >
          <Avatar name={rank.name} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-semibold text-foreground">{rank.name}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{rank.subtitle}</span>
          </span>
          <KebabIcon size={15} className="shrink-0 text-muted-foreground" />
        </button>
      </div>
    </aside>
  )
}

export default Sidebar

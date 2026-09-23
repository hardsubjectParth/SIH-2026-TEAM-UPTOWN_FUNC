import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, MotionConfig, motion } from 'framer-motion'
import Login from './components/Login'
import Shell from './components/shell/Shell'
import IntelligenceFeedPage from './pages/IntelligenceFeedPage'
import AgentTasksPage from './pages/AgentTasksPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import IngestKnowledgePage from './pages/IngestKnowledgePage'
import ArtifactsPage from './pages/ArtifactsPage'
import DashboardPage from './pages/DashboardPage'

function PageTransition({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      className="flex min-h-0 flex-1 flex-col"
    >
      {children}
    </motion.div>
  )
}

// Looping CSS animations (the status-dot pulse) keep repainting even when the window
// isn't focused -- cheap per-frame but still wasted work for a background tab/window.
// Pausing on blur and resuming on focus keeps it a true idle-CPU saver.
function usePauseAnimationsOnBlur() {
  useEffect(() => {
    const root = document.documentElement
    const pause = () => root.classList.add('motion-paused')
    const resume = () => root.classList.remove('motion-paused')
    window.addEventListener('blur', pause)
    window.addEventListener('focus', resume)
    return () => {
      window.removeEventListener('blur', pause)
      window.removeEventListener('focus', resume)
    }
  }, [])
}

function App() {
  const location = useLocation()
  usePauseAnimationsOnBlur()

  return (
    // reducedMotion="user" is the part that actually matters for
    // prefers-reduced-motion: Framer Motion's spring/slide transitions are driven by
    // JS (inline transforms via rAF), not CSS @keyframes, so the reduced-motion rule
    // in index.css (which only zeroes CSS animation-duration) never touches them on
    // its own -- this is the real switch that disables spring/slide/stagger for users
    // who asked for it, while opacity fades still play (motion, not decoration).
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          <Route path="/login" element={<Login />} />

          <Route path="/app" element={<Shell><PageTransition><DashboardPage /></PageTransition></Shell>} />
          <Route path="/app/feed" element={<Shell><PageTransition><IntelligenceFeedPage /></PageTransition></Shell>} />
          <Route path="/app/feed/:id" element={<Shell><PageTransition><IntelligenceFeedPage /></PageTransition></Shell>} />
          <Route path="/app/tasks" element={<Shell><PageTransition><AgentTasksPage /></PageTransition></Shell>} />
          <Route path="/app/knowledge" element={<Shell><PageTransition><KnowledgeBasePage /></PageTransition></Shell>} />
          <Route path="/app/knowledge/ingest" element={<Shell><PageTransition><IngestKnowledgePage /></PageTransition></Shell>} />
          <Route path="/app/artifacts" element={<Shell><PageTransition><ArtifactsPage /></PageTransition></Shell>} />

          <Route path="/" element={<Navigate to="/app" replace />} />
          <Route path="*" element={<Navigate to="/app" replace />} />
        </Routes>
      </AnimatePresence>
    </MotionConfig>
  )
}

export default App

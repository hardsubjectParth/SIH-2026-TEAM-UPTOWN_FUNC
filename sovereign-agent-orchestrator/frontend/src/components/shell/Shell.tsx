import type { ReactNode } from 'react'
import ProtectedRoute from '../ProtectedRoute'
import Sidebar from './Sidebar'
import AppearanceControls from './AppearanceControls'

function Shell({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground md:flex-row">
        <Sidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col"><div className="workspace-toolbar flex shrink-0 items-center justify-between gap-3 px-4 py-2.5 sm:px-8" role="toolbar" aria-label="Workspace display controls"><span className="truncate text-xs text-muted-foreground">Your workspace</span><AppearanceControls /></div><div className="main-window flex min-h-0 min-w-0 flex-1 flex-col">{children}</div></div>
      </div>
    </ProtectedRoute>
  )
}

export default Shell

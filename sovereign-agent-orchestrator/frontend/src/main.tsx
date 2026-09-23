import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import { AuthProvider } from './context/AuthContext'
import App from './App.tsx'
import { AppearanceProvider } from './components/shell/AppearanceControls'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <AppearanceProvider><App /></AppearanceProvider>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
)

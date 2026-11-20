// frontend/src/main.tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { applyTheme, getThemePref } from './utils/theme'
import { installClientLog } from './utils/clientLog'

installClientLog()   // browser errors go to the backend log (POST /api/client-log)

applyTheme(getThemePref())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

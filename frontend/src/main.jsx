import React from 'react'
import { createRoot } from 'react-dom/client'

// Self-hosted via npm rather than a CDN link, so the UI never blocks on a
// network font and works offline — which matters for a product whose whole
// Local mode promise is that nothing leaves the machine.
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/newsreader/400.css'
import '@fontsource/newsreader/600.css'
import '@fontsource/newsreader/400-italic.css'
import '@fontsource/jetbrains-mono/400.css'

import './styles/tokens.css'
import './styles/app.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

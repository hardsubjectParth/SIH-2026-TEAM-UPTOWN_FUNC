import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// v0: workspace package registered in pnpm-workspace.yaml
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
  },
})

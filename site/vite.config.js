import { fileURLToPath } from 'node:url'
import { defineConfig, searchForWorkspaceRoot } from 'vite'
import react from '@vitejs/plugin-react-swc'

const siteRoot = fileURLToPath(new URL('.', import.meta.url))
const packagesDir = fileURLToPath(new URL('../packages', import.meta.url))

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      // setting allow replaces Vite's default, so keep the site's own root
      // and add the shared packages (design tokens) next to it
      allow: [searchForWorkspaceRoot(siteRoot), packagesDir],
    },
  },
})

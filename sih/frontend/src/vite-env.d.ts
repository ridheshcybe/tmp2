/// <reference types="vite/client" />

// This file was missing, so `import.meta.env` was untyped and every
// VITE_* lookup (including the one already in src/services/api.ts) failed
// `npm run typecheck`.  Vite's client types also cover importing .css,
// ?url and ?raw assets.

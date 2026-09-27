/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Aerospace theme colors
        'cockpit': {
          'bg': '#0b0f19',        // Deep slate/navy background
          'surface': '#111827',    // Elevated surface
          'border': '#1f2937',     // Border color
          'muted': '#6b7280',      // Muted text
        },
        'hud': {
          'amber': '#f59e0b',      // Cockpit HUD amber
          'amber-dim': '#d97706',  // Dimmed amber
          'amber-glow': '#fbbf24', // Bright amber glow
        },
        'alert': {
          'red': '#ef4444',        // Critical alert
          'red-dim': '#dc2626',    // Dimmed red
          'red-glow': '#f87171',   // Bright red glow
        },
        'nominal': {
          'green': '#10b981',      // Nominal status
          'green-dim': '#059669',  // Dimmed green
          'green-glow': '#34d399', // Bright green glow
        },
        'cyber': {
          'cyan': '#06b6d4',       // Cyber cyan
          'cyan-dim': '#0891b2',   // Dimmed cyan
          'cyan-glow': '#22d3ee',  // Bright cyan glow
        },
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'Fira Code', 'monospace'],
        'display': ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'glow-amber': '0 0 20px rgba(245, 158, 11, 0.3)',
        'glow-red': '0 0 20px rgba(239, 68, 68, 0.3)',
        'glow-green': '0 0 20px rgba(16, 185, 129, 0.3)',
        'glow-cyan': '0 0 20px rgba(6, 182, 212, 0.3)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(6, 182, 212, 0.5)' },
          '100%': { boxShadow: '0 0 20px rgba(6, 182, 212, 0.8)' },
        },
      },
    },
  },
  plugins: [],
}

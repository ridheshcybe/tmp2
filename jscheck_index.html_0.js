
    tailwind.config = {
      darkMode: "class",
      theme: {
        extend: {
          colors: {
            "background": "#f5f0e8",
            "surface": "#ffffff",
            "surface-subtle": "#f9f7f2",
            "surface-muted": "#ede8df",
            "outline": "#e2ded6",
            "outline-strong": "#1a1a1a",
            "primary": "#1a1a1a",
            "primary-container": "#ffcc00",
            "on-primary-container": "#1a1a1a",
            "secondary": "#e63b2e",
            "secondary-container": "#fee2e2",
            "tertiary": "#0055ff",
            "tertiary-container": "#e0edff",
            "on-surface": "#1a1a1a",
            "on-surface-variant": "#6b6762"
          },
          borderRadius: {
            "DEFAULT": "0.25rem",
            "md": "0.375rem",
            "lg": "0.5rem",
            "xl": "0.75rem"
          },
          fontFamily: {
            headline: ["Space Grotesk", "sans-serif"],
            display: ["Space Grotesk", "sans-serif"],
            body: ["Inter", "sans-serif"],
            mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"]
          }
        }
      }
    }
  
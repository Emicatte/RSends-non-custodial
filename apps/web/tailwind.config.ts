const defaultTheme = require('tailwindcss/defaultTheme')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['var(--font-display)', ...defaultTheme.fontFamily.sans],
        mono:    ['var(--font-mono)', ...defaultTheme.fontFamily.mono],
        sans:    ['var(--font-display)', ...defaultTheme.fontFamily.sans],
      },
      colors: {
        // RSends palette — references CSS variables for runtime flexibility.
        // `terracotta` fails AA on body text (3.87:1 on paper); reach for
        // `terracotta-deep` for links, small text and filled surfaces.
        ink:                'var(--rs-ink)',
        'ink-muted':        'var(--rs-ink-muted)',
        line:               'var(--rs-line)',
        terracotta:         'var(--rs-terracotta)',
        'terracotta-deep':  'var(--rs-terracotta-deep)',
        paper:              'var(--rs-paper)',
        surface:            'var(--rs-surface)',
        wash:               'var(--rs-wash)',
      },
      borderRadius: {
        // Deliberately three steps, not one. A single radius everywhere is
        // the flattest tell of a generated design.
        control: '4px',  // buttons, inputs, pills
        card:    '8px',  // cards, panels, code blocks
        frame:   '12px', // device frames, media
      },
    },
  },
  plugins: [],
}
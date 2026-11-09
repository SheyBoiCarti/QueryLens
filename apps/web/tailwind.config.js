/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'var(--bg-page)', surface: 'var(--bg-surface)', subtle: 'var(--bg-subtle)',
        control: 'var(--bg-control)', active: 'var(--bg-active)', border: 'var(--border)',
        'border-control': 'var(--border-control)', 'border-row': 'var(--border-row)',
        text: 'var(--text)', muted: 'var(--text-muted)', dim: 'var(--text-dim)',
        accent: 'var(--accent)', 'accent-bg': 'var(--accent-bg)', 'accent-border': 'var(--accent-border)',
        primary: 'var(--btn-primary-bg)', 'primary-hover': '#00764A',
        danger: 'var(--danger)', 'danger-border': '#5C2B2B',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['Source Code Pro', 'monospace'],
      },
      fontSize: { sm: ['13px', '1.5'], base: ['13px', '1.5'], lg: ['18px', '1.5'], xl: ['20px', '1.5'] },
      borderRadius: { DEFAULT: '6px', md: '6px', lg: '6px' },
    },
  },
  plugins: [],
};

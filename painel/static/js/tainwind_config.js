/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class', '[data-theme="dark"]'], // ativa dark por classe ou data-attr
  content: [
    './templates/**/*.html',
    './**/*.html',
    './static/**/*.js',
  ],
  theme: {
    extend: {
      borderRadius: {
        DEFAULT: '12px',
        md: '12px',
        lg: '16px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,.06)',
        md: '0 6px 16px rgba(15,23,42,.08)',
      },
    },
  },
  corePlugins: {
    // Mantemos todos – mas as cores vêm de CSS vars nos componentes
  },
  safelist: [
    // se você gera badges/cores dinâmicos no backend, liste aqui
    'bg-blue-50', 'bg-amber-50', 'bg-rose-50',
  ],
};

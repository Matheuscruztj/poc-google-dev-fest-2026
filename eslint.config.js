import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    files: ['app/static/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: globals.browser,
    },
    rules: js.configs.recommended.rules,
  },
];

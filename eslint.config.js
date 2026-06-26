/**
 * ESLintConfig
 *
 * Flat config (ESLint 9) extending eslint-config-universe for
 * React Native / TypeScript / Expo, with project-specific overrides.
 *
 * Rules are set to catch real bugs while avoiding noise from stylistic
 * preferences that would require invasive changes across the codebase.
 */
const native = require('eslint-config-universe/flat/native');

module.exports = [
  ...native,
  {
    // TypeScript-specific rules — scoped to .ts/.tsx to avoid
    // crashing on .js config files (eslint.config.js, jest.config.js, etc.)
    files: ['**/*.ts', '**/*.tsx'],
    rules: {
      '@typescript-eslint/array-type': 'off',

      // ── Unused vars — keep as error, but allow unused catch params ──
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrors: 'none',
        },
      ],
    },
  },
  {
    // Global rules applied to all files
    rules: {
      // ── Overly strict rules disabled to avoid invasive reformatting ──
      'import/order': 'off',
      'import/no-duplicates': 'off',
      'import/no-named-as-default-member': 'off',
      'import/first': 'off',
      'react/jsx-curly-brace-presence': 'off',

      // ── React Native ──
      'react-native/no-raw-text': 'off',
    },
  },
];

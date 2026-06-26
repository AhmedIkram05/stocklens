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
    rules: {
      // ── Overly strict rules disabled to avoid invasive reformatting ──
      'import/order': 'off',
      'import/no-duplicates': 'off',
      'import/no-named-as-default-member': 'off',
      'import/first': 'off',
      'react/jsx-curly-brace-presence': 'off',
      '@typescript-eslint/array-type': 'off',

      // ── Unused vars — keep as error, but allow unused catch params ──
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrors: 'none',
        },
      ],

      // ── React Native ──
      'react-native/no-raw-text': 'off',
    },
  },
];

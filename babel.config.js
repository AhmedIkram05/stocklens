/**
 * BabelConfig
 *
 * Babel configuration for the Expo project. Enables `module-resolver`
 * alias `@` → `./src` for concise imports across the codebase.
 */
const path = require('path');

module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      [
        'module-resolver',
        {
          extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
          alias: {
            '@': path.resolve(__dirname, 'frontend', 'src'),
          },
        },
      ],
    ],
  };
};

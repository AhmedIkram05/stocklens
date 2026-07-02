/**
 * BabelConfig
 *
 * Babel configuration for the Expo project. Enables `module-resolver`
 * alias `@` → `./src` for concise imports across the codebase.
 */
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
            '@': './frontend/src',
          },
        },
      ],
    ],
  };
};

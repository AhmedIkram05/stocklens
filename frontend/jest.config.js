/**
 * JestConfig
 *
 * Jest configuration for the project (jest-expo preset), moduleNameMapper
 * for `@` alias, and setup file for test environment mocks.
 */
const path = require('path');

// ponytail: must come before module.exports — preset's setupFiles check this at load time
process.env.EXPO_OS = 'ios';

module.exports = {
  preset: 'jest-expo',
  testEnvironment: 'node',
  // ponytail: force babel-jest to find root babel.config.js;
  // jest-expo's resolveBabelConfig returns null when one exists, so
  // babel falls back to process.cwd() which may not be the project root.
  // Also forward the platform to babel-preset-expo so it inlines
  // process.env.EXPO_OS (via expo-define-plugin) instead of replacing it with undefined.
  transform: {
    '\\.[jt]sx?$': [
      'babel-jest',
      {
        configFile: path.resolve(__dirname, '..', 'babel.config.js'),
        caller: { name: 'metro', bundler: 'metro', platform: 'ios' },
      },
    ],
  },
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testPathIgnorePatterns: [
    '/node_modules/',
    '<rootDir>/src/__tests__/fixtures/',
    '<rootDir>/src/__tests__/utils/index.ts',
    '<rootDir>/src/__tests__/utils/renderWithProviders.tsx',
  ],
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native|@react-navigation|@react-native-community|expo|expo-.*|@expo/vector-icons|@unimodules|unimodules|sentry-expo|native-base|react-native-svg|react-native-chart-kit)/)',
  ],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.(svg)$': path.join(__dirname, '__mocks__', 'svgMock.js'),
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json', 'node'],
  collectCoverage: true,
  coverageDirectory: '<rootDir>/coverage',
  coverageReporters: ['lcov', 'text-summary'],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/__tests__/**',
    '!src/types/**',
    '!src/**/index.ts',
  ],
  passWithNoTests: true,
};

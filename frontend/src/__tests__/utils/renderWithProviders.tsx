/**
 * Test render utility `renderWithProviders`.
 * Wraps UI with Theme, Auth, SafeArea and optional Navigation for integration tests.
 */

import React, { ReactElement, ReactNode } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { render, RenderOptions } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AuthContext, AuthContextType } from '@/contexts/AuthContext';
import {
  ThemeContext,
  ThemeContextType,
  ThemeMode,
  darkTheme,
  lightTheme,
} from '@/contexts/ThemeContext';

export type ProviderOverrides = {
  withNavigation?: boolean;
  themeMode?: ThemeMode;
  themeValue?: Partial<ThemeContextType>;
  authValue?: Partial<AuthContextType>;
};

const createThemeValue = (
  mode: ThemeMode = 'light',
  overrides?: Partial<ThemeContextType>,
): ThemeContextType => {
  const resolvedMode = overrides?.mode ?? mode;
  const resolvedTheme = overrides?.theme ?? (resolvedMode === 'dark' ? darkTheme : lightTheme);

  return {
    theme: resolvedTheme,
    mode: resolvedMode,
    isDark: overrides?.isDark ?? resolvedMode === 'dark',
    setMode: overrides?.setMode ?? (() => {}),
    ...overrides,
  } as ThemeContextType;
};

const createAuthValue = (overrides?: Partial<AuthContextType>): AuthContextType => ({
  user: null,
  userProfile: null,
  loading: false,
  locked: false,
  signOutUser: async () => {},
  unlockWithDeviceAuth: async () => true,
  unlockWithCredentials: async () => true,
  startLockGrace: () => {},
  ...overrides,
});

const TestProviders = ({
  children,
  overrides,
}: {
  children: ReactNode;
  overrides?: ProviderOverrides;
}) => {
  const themeValue = createThemeValue(overrides?.themeMode, overrides?.themeValue);
  const authValue = createAuthValue(overrides?.authValue);
  const content =
    overrides?.withNavigation === false ? (
      children
    ) : (
      <NavigationContainer>{children}</NavigationContainer>
    );

  return (
    <ThemeContext.Provider value={themeValue}>
      <AuthContext.Provider value={authValue}>{content}</AuthContext.Provider>
    </ThemeContext.Provider>
  );
};

export type RenderWithProvidersOptions = RenderOptions & { providerOverrides?: ProviderOverrides };

export const renderWithProviders = (ui: ReactElement, options?: RenderWithProvidersOptions) => {
  const { providerOverrides, ...renderOptions } = options ?? {};
  const Wrapper = ({ children }: { children?: ReactNode }) => (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 375, height: 812 },
        insets: { top: 0, bottom: 0, left: 0, right: 0 },
      }}
    >
      <TestProviders overrides={providerOverrides}>{children}</TestProviders>
    </SafeAreaProvider>
  );

  return render(ui, { wrapper: Wrapper, ...renderOptions });
};

/**
 * ThemeContext
 *
 * Semantic theme tokens and light/dark mode management.
 */

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

export type ThemeMode = 'light' | 'dark';

/**
 * Base brand colors - consistent across light and dark modes
 * Export these for components that need static color values
 */
export const brandColors = {
  green: '#10b981',
  blue: '#007AFF',
  red: '#FF3B30',
  white: '#ffffff',
  black: '#000000',
  gray: '#f5f5f5',
} as const;

/**
 * ThemeColors interface - semantic color tokens for the app
 */
export interface ThemeColors {
  // Brand colors (consistent across modes)
  primary: string; // Green - primary actions, branding
  secondary: string; // Blue - accents, links
  error: string; // Red - errors, destructive actions

  // Backgrounds (mode-specific)
  background: string; // Page/screen background
  surface: string; // Cards, modals, default elevation

  // Text (mode-specific)
  text: string; // Primary text
  textSecondary: string; // Secondary/muted text

  // Borders (mode-specific)
  border: string; // Default borders, dividers
}

const THEMES: Record<ThemeMode, ThemeColors> = {
  light: {
    primary: brandColors.green,
    secondary: brandColors.blue,
    error: brandColors.red,
    background: brandColors.gray,
    surface: brandColors.white,
    text: brandColors.black,
    textSecondary: '#00000099',
    border: '#00000026',
  },
  dark: {
    primary: brandColors.green,
    secondary: brandColors.blue,
    error: brandColors.red,
    background: brandColors.black,
    surface: '#1C1C1E',
    text: brandColors.white,
    textSecondary: '#ffffff99',
    border: '#ffffff26',
  },
} as const;

export const lightTheme = THEMES.light;
export const darkTheme = THEMES.dark;

export interface ThemeContextType {
  /** Current theme colors */
  theme: ThemeColors;
  /** Current theme mode */
  mode: ThemeMode;
  /** Change theme mode and persist */
  setMode: (mode: ThemeMode) => void;
  /** Convenience flag for dark mode checks */
  isDark: boolean;
}

export const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const THEME_STORAGE_KEY = 'theme_mode';

/**
 * ThemeProvider - Wraps app to provide theme context
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>('light');

  // Load saved theme preference on mount
  useEffect(() => {
    const loadTheme = async () => {
      try {
        const savedMode = await SecureStore.getItemAsync(THEME_STORAGE_KEY);
        if (savedMode === 'light' || savedMode === 'dark') {
          setModeState(savedMode);
        }
      } catch (error) {}
    };
    loadTheme();
  }, []);

  // Save theme preference when changed
  const setMode = async (newMode: ThemeMode) => {
    setModeState(newMode);
    try {
      await SecureStore.setItemAsync(THEME_STORAGE_KEY, newMode);
    } catch (error) {}
  };

  const theme = useMemo(() => THEMES[mode], [mode]);
  const isDark = mode === 'dark';

  return (
    <ThemeContext.Provider value={{ theme, mode, setMode, isDark }}>
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * useTheme Hook - Access theme from any component
 *
 * @example
 * const { theme, isDark, setMode } = useTheme();
 * <View style={{ backgroundColor: theme.background }}>
 *   <Text style={{ color: theme.text }}>Hello</Text>
 * </View>
 */
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

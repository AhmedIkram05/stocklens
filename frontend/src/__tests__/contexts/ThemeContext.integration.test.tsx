/**
 * Tests for `ThemeContext` (integration).
 * Verifies theme mode switching, persistence to SecureStore, and defaults.
 */

import React from 'react';
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { ThemeProvider, useTheme, brandColors } from '@/contexts/ThemeContext';
import * as SecureStore from 'expo-secure-store';

// Mock SecureStore to avoid actual device storage during tests
jest.mock('expo-secure-store');

describe('ThemeContext', () => {
  // Clear all mocks before each test to ensure clean state
  beforeEach(() => {
    jest.clearAllMocks();
  });

  /**
   * Test: Context provider requirement
   * Validates that useTheme hook throws error when used outside ThemeProvider.
   * Prevents undefined behavior if developer forgets to wrap app in provider.
   */
  it('throws when useTheme is used outside provider', () => {
    expect(() =>
      renderHook(() => useTheme(), { wrapper: ({ children }) => <>{children}</> }),
    ).toThrow('useTheme must be used within a ThemeProvider');
  });

  /**
   * Test: Theme mode switching and persistence
   * Validates that:
   * 1. Light mode is the default
   * 2. Theme can be switched to dark mode
   * 3. Theme preference is saved to SecureStore
   * 4. Theme colors update correctly (gray → black background)
   */
  it('provides light theme defaults and toggles to dark mode', async () => {
    // Mock SecureStore methods
    const getItemAsync = jest.spyOn(SecureStore, 'getItemAsync').mockResolvedValue('light');
    const setItemAsync = jest.spyOn(SecureStore, 'setItemAsync').mockResolvedValue();

    // Render theme hook
    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    // Wait for theme to load from storage
    await waitFor(() => {
      expect(getItemAsync).toHaveBeenCalled();
    });

    // Verify default light theme
    expect(result.current.theme.background).toBe(brandColors.gray);
    expect(result.current.mode).toBe('light');

    // Switch to dark mode
    await act(async () => {
      await result.current.setMode('dark');
    });

    // Verify dark mode is saved to storage
    expect(setItemAsync).toHaveBeenCalledWith('theme_mode', 'dark');

    // Verify theme colors updated to dark mode
    await waitFor(() => {
      expect(result.current.mode).toBe('dark');
      expect(result.current.theme.background).toBe(brandColors.black);
    });

    getItemAsync.mockRestore();
    setItemAsync.mockRestore();
  });

  /**
   * Test: Theme restoration on app restart
   * Validates that previously selected theme (dark mode) is restored from SecureStore
   * when the app is reopened. Ensures user preference persists across sessions.
   */
  it('restores persisted mode on mount', async () => {
    // Mock SecureStore to return 'dark' as the saved theme
    jest.spyOn(SecureStore, 'getItemAsync').mockResolvedValueOnce('dark');

    // Render theme hook
    const { result } = renderHook(() => useTheme(), {
      wrapper: ThemeProvider,
    });

    // Verify dark mode was restored from storage
    await waitFor(() => {
      expect(result.current.mode).toBe('dark');
      expect(result.current.isDark).toBe(true);
    });
  });
});

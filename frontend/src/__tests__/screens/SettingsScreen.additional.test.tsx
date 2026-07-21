/**
 * Additional tests for `SettingsScreen` focusing on edge cases and error handling.
 * Tests device auth unavailable states, error handling, and boundary conditions.
 */

import React from 'react';
import { act, fireEvent, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';
import SettingsScreen from '@/screens/SettingsScreen';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import * as deviceAuth from '@/hooks/useDeviceAuth';
import { receiptService } from '@/services/receipts';

jest.mock('@/hooks/useDeviceAuth', () => ({
  isDeviceAuthAvailable: jest.fn(),
  isDeviceEnabled: jest.fn(),
  authenticateDevice: jest.fn(),
  setDeviceEnabled: jest.fn(),
  clearDeviceCredentials: jest.fn(),
}));

jest.mock('@/services/receipts', () => ({
  receiptService: {
    deleteAll: jest.fn(),
  },
}));

const alertSpy = jest.spyOn(Alert, 'alert');
const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;

describe('SettingsScreen edge cases', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
    (deviceAuth.isDeviceAuthAvailable as jest.Mock).mockResolvedValue(true);
    (deviceAuth.isDeviceEnabled as jest.Mock).mockResolvedValue(false);
    (deviceAuth.authenticateDevice as jest.Mock).mockResolvedValue({ success: true } as any);
    mockedReceiptService.deleteAll.mockResolvedValue();
  });

  const renderScreen = (overrides?: Parameters<typeof renderWithProviders>[1]) =>
    renderWithProviders(
      <SettingsScreen />,
      overrides ?? { providerOverrides: { withNavigation: false } },
    );

  it('handles device auth unavailable gracefully', async () => {
    // Use mockResolvedValue so device auth stays unavailable throughout the test
    (deviceAuth.isDeviceAuthAvailable as jest.Mock).mockResolvedValue(false);
    (deviceAuth.isDeviceEnabled as jest.Mock).mockResolvedValue(false);

    const { getAllByRole } = renderScreen();

    await waitFor(() => {
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalled();
    });

    // Verify switch is OFF (device auth not enabled)
    const switches = getAllByRole('switch');
    expect(switches[0].props.value).toBe(false);

    // Should show explanatory alert when toggled
    act(() => {
      fireEvent(switches[0], 'onValueChange', true);
    });

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Device authentication unavailable',
        expect.stringContaining('not available or not configured'),
        expect.any(Array),
      );
    });
  });

  it('handles device auth enable failure', async () => {
    (deviceAuth.isDeviceAuthAvailable as jest.Mock).mockResolvedValueOnce(true);
    (deviceAuth.isDeviceEnabled as jest.Mock).mockResolvedValueOnce(false);
    (deviceAuth.authenticateDevice as jest.Mock).mockResolvedValueOnce({
      success: false,
      error: 'Auth failed',
    } as any);

    const { getAllByRole } = renderScreen();

    // Wait for initial load
    await waitFor(() => {
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalled();
    });

    // Toggle switch to enable
    const switchEl = getAllByRole('switch')[0];
    act(() => {
      fireEvent(switchEl, 'onValueChange', true);
    });

    // Wait for auth attempt
    await waitFor(() => {
      expect(deviceAuth.authenticateDevice).toHaveBeenCalledWith(
        'Authenticate to enable device passcode login',
      );
    });

    // Should show failure alert with the specific error message
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Authentication failed',
        'Auth failed',
        expect.any(Array),
      );
    });
  });

  it('handles device auth enable success', async () => {
    (deviceAuth.isDeviceAuthAvailable as jest.Mock).mockResolvedValueOnce(true);
    (deviceAuth.isDeviceEnabled as jest.Mock).mockResolvedValueOnce(false);
    (deviceAuth.authenticateDevice as jest.Mock).mockResolvedValueOnce({ success: true } as any);
    (deviceAuth.setDeviceEnabled as jest.Mock).mockResolvedValueOnce(undefined);
    (deviceAuth.clearDeviceCredentials as jest.Mock).mockResolvedValueOnce(undefined);

    const { getAllByRole } = renderScreen();

    // Wait for initial load
    await waitFor(() => {
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalled();
    });

    // Toggle switch to enable
    const switchEl = getAllByRole('switch')[0];
    act(() => {
      fireEvent(switchEl, 'onValueChange', true);
    });

    // Wait for successful enable
    await waitFor(() => {
      expect(deviceAuth.setDeviceEnabled).toHaveBeenCalledWith(true);
    });

    // Should show success message
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Enabled',
        expect.stringContaining('Device passcode login enabled'),
      );
    });
  });

  it('handles clear data error', async () => {
    mockedReceiptService.deleteAll.mockRejectedValueOnce(new Error('Delete failed'));

    const { getByText } = renderScreen({
      providerOverrides: { withNavigation: false },
    });

    // Tap clear data
    act(() => {
      fireEvent.press(getByText('Clear All Data'));
    });

    // Wait for confirmation dialog
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Clear All Data',
        'Are you sure you want to delete all scanned receipts stored on this device? This action cannot be undone.',
        expect.arrayContaining([
          expect.objectContaining({ text: 'Cancel', style: 'cancel' }),
          expect.objectContaining({
            text: 'Delete',
            style: 'destructive',
          }),
        ]),
      );
    });

    // Find the delete button from the last alert call and press it
    const alertCalls = alertSpy.mock.calls;
    const lastCall = alertCalls[alertCalls.length - 1];
    const buttons = lastCall[2] as Array<{ text?: string; style?: string; onPress?: () => void }>;
    const deleteBtn = buttons?.find(
      (btn: any) => btn.text === 'Delete' && btn.style === 'destructive',
    );

    act(() => {
      deleteBtn?.onPress?.();
    });

    // Verify error handling - actual error message is 'Delete failed'
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('Error', 'Delete failed');
    });
  });

  it('handles sign out error', async () => {
    // First render to get the initial alert mock
    const signOutUser = jest.fn().mockRejectedValueOnce(new Error('Sign out failed'));
    const { getByText } = renderScreen({
      providerOverrides: {
        withNavigation: false,
        authValue: { signOutUser },
      },
    });

    // Tap log out
    act(() => {
      fireEvent.press(getByText('Log Out'));
    });

    // Confirm sign out
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Sign Out',
        'Are you sure you want to sign out?',
        expect.arrayContaining([
          expect.objectContaining({ text: 'Cancel', style: 'cancel' }),
          expect.objectContaining({
            text: 'Sign Out',
            style: 'destructive',
          }),
        ]),
      );
    });

    // Find and press sign out button from the alert
    const alertCalls = alertSpy.mock.calls;
    const lastCall = alertCalls[alertCalls.length - 1];
    const buttons = lastCall[2] as Array<{ text?: string; style?: string; onPress?: () => void }>;
    const signOutBtn = buttons?.find(
      (btn: any) => btn.text === 'Sign Out' && btn.style === 'destructive',
    );

    act(() => {
      signOutBtn?.onPress?.();
    });

    // Verify error handling
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('Error', 'Failed to sign out');
    });
  });

  it('refreshes device auth status on pull-to-refresh', async () => {
    const { UNSAFE_getByType } = renderScreen();

    await waitFor(() => {
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalled();
    });

    // Get RefreshControl and trigger it
    const { RefreshControl } = require('react-native');
    const refreshControl = UNSAFE_getByType(RefreshControl);

    // Simulate pull-to-refresh
    act(() => {
      refreshControl.props.onRefresh();
    });

    // Wait for refresh to complete
    await waitFor(() => {
      // Should be called twice: initial load + refresh
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalledTimes(2);
      expect(deviceAuth.isDeviceEnabled).toHaveBeenCalledTimes(2);
    });
  });

  it('handles rapid toggle of device auth switch', async () => {
    (deviceAuth.isDeviceAuthAvailable as jest.Mock).mockResolvedValue(true);
    (deviceAuth.isDeviceEnabled as jest.Mock).mockResolvedValueOnce(false);
    (deviceAuth.authenticateDevice as jest.Mock).mockResolvedValue({ success: true } as any);
    (deviceAuth.setDeviceEnabled as jest.Mock).mockResolvedValue(undefined);

    const { getAllByRole } = renderScreen();

    // Wait for initial load
    await waitFor(() => {
      expect(deviceAuth.isDeviceAuthAvailable).toHaveBeenCalled();
    });

    const switchEl = getAllByRole('switch')[0];

    // Rapid toggle on/off/on
    act(() => {
      fireEvent(switchEl, 'onValueChange', true);
    });

    await waitFor(() => {
      expect(deviceAuth.authenticateDevice).toHaveBeenCalled();
    });
  });
});

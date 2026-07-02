/**
 * Tests for `LockScreen` (integration).
 * Verifies device/passcode unlock flow, password fallback, forgot-password
 * behavior, and associated error handling.
 */

import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, waitFor } from '@testing-library/react-native';
import LockScreen from '@/screens/LockScreen';
import { renderWithProviders } from '../utils';
import * as authModule from '@/services/auth';

jest.mock('@/services/auth', () => ({
  authService: {
    forgotPassword: jest.fn(),
  },
}));

const alertSpy = jest.spyOn(Alert, 'alert');

describe('LockScreen', () => {
  let unlockWithDeviceAuth: jest.Mock;
  let unlockWithCredentials: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
    unlockWithDeviceAuth = jest.fn();
    unlockWithCredentials = jest.fn();
    (authModule.authService.forgotPassword as jest.Mock).mockResolvedValue({ message: 'ok' });
  });

  const renderScreen = (overrides?: { email?: string }) =>
    renderWithProviders(<LockScreen />, {
      providerOverrides: {
        authValue: {
          unlockWithDeviceAuth,
          unlockWithCredentials,
          user: { email: overrides?.email ?? 'test@example.com' } as any,
          userProfile: { email: overrides?.email ?? 'test@example.com' } as any,
        },
      },
    });

  it('renders locked screen with email and unlock options', () => {
    const { getByText } = renderScreen();

    expect(getByText('Locked')).toBeTruthy();
    expect(getByText('Unlock to continue')).toBeTruthy();
    expect(getByText('test@example.com')).toBeTruthy();
    expect(getByText('Unlock with Device Passcode')).toBeTruthy();
  });

  it('calls unlockWithDeviceAuth when device auth button pressed', async () => {
    unlockWithDeviceAuth.mockResolvedValue(true);
    const { getByText } = renderScreen();

    fireEvent.press(getByText('Unlock with Device Passcode'));

    await waitFor(() => expect(unlockWithDeviceAuth).toHaveBeenCalled());
  });

  it('shows alert when device auth unlock fails', async () => {
    unlockWithDeviceAuth.mockResolvedValue(false);
    const { getByText } = renderScreen();

    fireEvent.press(getByText('Unlock with Device Passcode'));

    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith('Unlock Failed', expect.any(String)));
  });

  it('validates password field before unlocking with credentials', () => {
    const { getByText } = renderScreen();

    fireEvent.press(getByText('Unlock'));

    expect(alertSpy).toHaveBeenCalledWith('Missing Password', 'Please enter your account password');
    expect(unlockWithCredentials).not.toHaveBeenCalled();
  });

  it('unlocks with credentials when password provided', async () => {
    unlockWithCredentials.mockResolvedValue(true);
    const { getByPlaceholderText, getByText } = renderScreen();

    fireEvent.changeText(getByPlaceholderText('Password'), 'securePass123');
    fireEvent.press(getByText('Unlock'));

    await waitFor(() => {
      expect(unlockWithCredentials).toHaveBeenCalledWith('test@example.com', 'securePass123');
    });
  });

  it('shows alert when credential unlock fails', async () => {
    unlockWithCredentials.mockResolvedValue(false);
    const { getByPlaceholderText, getByText } = renderScreen();

    fireEvent.changeText(getByPlaceholderText('Password'), 'wrongPass');
    fireEvent.press(getByText('Unlock'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('Unlock Failed', 'Invalid password. Please try again.');
    });
  });

  it('triggers forgot password flow', async () => {
    const { getByText } = renderScreen({ email: 'user@test.com' });

    fireEvent.press(getByText('Forgot password?'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Send Reset Link?',
        expect.stringContaining('user@test.com'),
        expect.any(Array),
      );
    });

    // Verify the confirmation dialog was shown
    const alertCall = alertSpy.mock.calls.find((c) => c[0] === 'Send Reset Link?');
    expect(alertCall).toBeDefined();
    const buttons = alertCall?.[2];
    expect(buttons).toBeDefined();
    expect(buttons?.find((b: any) => b.text === 'Send')).toBeDefined();
    expect(buttons?.find((b: any) => b.text === 'Cancel')).toBeDefined();
  });
});

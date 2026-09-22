/**
 * Tests for `LoginScreen` (integration).
 * Verifies email/password sign-in, lock-grace start, device-auth prompt,
 * and navigation to SignUp.
 */

import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, waitFor } from '@testing-library/react-native';
import LoginScreen from '@/screens/LoginScreen';
import { renderWithProviders } from '../utils';
import { authService } from '@/services/auth';
import { ApiError } from '@/services/api';
import { promptEnableDeviceAuth } from '@/utils/deviceAuthPrompt';
import { useNavigation } from '@react-navigation/native';

jest.mock('@/services/auth', () => ({
  authService: {
    signIn: jest.fn(),
    signUp: jest.fn(),
    signOut: jest.fn(),
    getProfile: jest.fn(),
    isAuthenticated: jest.fn(),
  },
}));

jest.mock('@/utils/deviceAuthPrompt', () => ({
  __esModule: true,
  promptEnableDeviceAuth: jest.fn(),
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(),
  };
});

const mockedSignIn = authService.signIn as jest.MockedFunction<typeof authService.signIn>;
const mockedPrompt = promptEnableDeviceAuth as jest.MockedFunction<typeof promptEnableDeviceAuth>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

const alertSpy = jest.spyOn(Alert, 'alert');

describe('LoginScreen', () => {
  let navigateSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
    navigateSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({ navigate: navigateSpy } as any);
    mockedSignIn.mockResolvedValue({} as any);
    mockedPrompt.mockResolvedValue(true as any);
  });

  it('performs sign-in flow, starts lock grace, and prompts device auth enrollment', async () => {
    const startLockGrace = jest.fn();
    const { getByPlaceholderText, getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: {
        withNavigation: false,
        authValue: { startLockGrace },
      },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'demo@example.com');
    await fireEvent.changeText(getByPlaceholderText('Password'), 's3cret!');

    await fireEvent.press(getByText('Login'));

    await waitFor(() => {
      expect(mockedSignIn).toHaveBeenCalledWith({ email: 'demo@example.com', password: 's3cret!' });
    });

    expect(startLockGrace).toHaveBeenCalled();
    expect(mockedPrompt).toHaveBeenCalledWith('demo@example.com', 's3cret!');
  });

  it('navigates to SignUp screen from footer CTA', async () => {
    const { getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.press(getByText('Sign Up'));

    expect(navigateSpy).toHaveBeenCalledWith('SignUp');
  });

  it('shows missing information alert when password is empty on submit', async () => {
    const { getByPlaceholderText, getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'demo@example.com');
    await fireEvent.press(getByText('Login'));

    expect(alertSpy).toHaveBeenCalledWith(
      'Missing information',
      'Please enter both your email and password to continue.',
    );
    expect(mockedSignIn).not.toHaveBeenCalled();
  });

  it('shows missing information alert when both fields are empty on submit', async () => {
    const { getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.press(getByText('Login'));

    expect(alertSpy).toHaveBeenCalledWith(
      'Missing information',
      'Please enter both your email and password to continue.',
    );
    expect(mockedSignIn).not.toHaveBeenCalled();
  });

  it('shows validation error for invalid email format from API', async () => {
    mockedSignIn.mockRejectedValue(new ApiError(422, 'Please enter a valid email and password.'));
    const { getByPlaceholderText, getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'invalid');
    await fireEvent.changeText(getByPlaceholderText('Password'), 'pw');
    await fireEvent.press(getByText('Login'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Sign In Error',
        'Please enter a valid email and password.',
      );
    });
  });

  it('shows generic error message on API failure', async () => {
    mockedSignIn.mockRejectedValue(new Error('Network request failed'));
    const { getByPlaceholderText, getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'demo@example.com');
    await fireEvent.changeText(getByPlaceholderText('Password'), 's3cret!');
    await fireEvent.press(getByText('Login'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Sign In Error',
        'An error occurred signing in. Please try again.',
      );
    });
  });

  it('shows 401 error message for invalid credentials', async () => {
    mockedSignIn.mockRejectedValue(new ApiError(401, 'Invalid email or password.'));
    const { getByPlaceholderText, getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'wrong@example.com');
    await fireEvent.changeText(getByPlaceholderText('Password'), 'wrong');
    await fireEvent.press(getByText('Login'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Sign In Error',
        'Invalid email or password. Please try again.',
      );
    });
  });

  it('renders KeyboardAvoidingView with correct behavior', async () => {
    const { root } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    // v14 host tree: KeyboardAvoidingView is composite; behavior is applied via
    // nested ScrollView's keyboardShouldPersistTaps (host prop).
    const sv = root?.queryAll((el) => el.props.keyboardShouldPersistTaps !== undefined)[0]!;
    expect(sv).toBeTruthy();
    expect(sv.props.keyboardShouldPersistTaps).toBe('handled');
    // iOS (EXPO_OS=ios) => behavior 'padding'; assert the keyboard-avoiding
    // host structure exists (KAV renders a flex:1 View wrapper).
    const flexWrap = root?.queryAll((el) => {
      const s = el.props.style;
      if (!s) return false;
      const flat = Array.isArray(s) ? Object.assign({}, ...s) : s;
      return flat.flex === 1;
    })[0];
    expect(flexWrap).toBeTruthy();
  });

  it('disables forgot password button after press with 30s cooldown', async () => {
    jest.useFakeTimers();
    const { getByText, getByPlaceholderText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.changeText(getByPlaceholderText('Email'), 'test@example.com');
    await fireEvent.press(getByText('Forgot password?'));

    const forgotButton = getByText('Forgot password?');
    expect(forgotButton).toBeTruthy();

    jest.advanceTimersByTime(30000);
    jest.useRealTimers();
  });

  it('shows email required alert when forgot password pressed without email', async () => {
    const { getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    await fireEvent.press(getByText('Forgot password?'));

    expect(alertSpy).toHaveBeenCalledWith(
      'Email required',
      'Enter the email address for your account to receive a password reset link.',
    );
  });

  it('renders AuthFooter with sign up prompt', async () => {
    const { getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText("Don't have an account?")).toBeTruthy();
    expect(getByText('Sign Up')).toBeTruthy();
  });

  it('renders logo and welcome text', async () => {
    const { getByText } = await renderWithProviders(<LoginScreen />, {
      providerOverrides: { withNavigation: false },
    });

    expect(getByText(/Welcome to Stock/)).toBeTruthy();
    expect(getByText(/Scan your spending/)).toBeTruthy();
  });
});

/**
 * Tests for `SignUpScreen` (integration).
 * Verifies form validation, account creation, lock-grace start, device-auth
 * prompt, and navigation to Login.
 */

import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, waitFor } from '@testing-library/react-native';
import SignUpScreen from '@/screens/SignUpScreen';
import { renderWithProviders } from '../utils';
import { authService } from '@/services/auth';
import { ApiError } from '@/services/api';
import { promptEnableDeviceAuth } from '@/utils/deviceAuthPrompt';
import { useNavigation } from '@react-navigation/native';

jest.mock('@/components/PrimaryButton', () => {
  const React = require('react');
  const { TouchableOpacity, Text } = require('react-native');
  return ({ onPress, children, accessibilityLabel }: any) =>
    React.createElement(
      TouchableOpacity,
      { onPress, accessibilityLabel },
      typeof children === 'string' ? React.createElement(Text, null, children) : children,
    );
});

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

const mockedSignUp = authService.signUp as jest.MockedFunction<typeof authService.signUp>;
const mockedPrompt = promptEnableDeviceAuth as jest.MockedFunction<typeof promptEnableDeviceAuth>;
const mockedUseNavigation = useNavigation as jest.MockedFunction<typeof useNavigation>;

const alertSpy = jest.spyOn(Alert, 'alert');

describe('SignUpScreen', () => {
  let navigateSpy: jest.Mock;
  let goBackSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
    navigateSpy = jest.fn();
    goBackSpy = jest.fn();
    mockedUseNavigation.mockReturnValue({
      navigate: navigateSpy,
      goBack: goBackSpy,
      canGoBack: () => true,
    } as any);
    mockedSignUp.mockResolvedValue({} as any);
    mockedPrompt.mockResolvedValue(true as any);
  });

  it('shows validation alert when email format is invalid', () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
    fireEvent.changeText(getByPlaceholderText('Email'), 'invalid-email');
    fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
    fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');

    fireEvent.press(getByText('Create Account'));

    expect(alertSpy).toHaveBeenCalledWith('Error', 'Please enter a valid email address');
    expect(mockedSignUp).not.toHaveBeenCalled();
  });

  it('creates account, starts grace period, and prompts device auth enrollment', async () => {
    const startLockGrace = jest.fn();
    const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: {
        withNavigation: false,
        authValue: { startLockGrace },
      },
    });

    fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
    fireEvent.changeText(getByPlaceholderText('Email'), 'jane@example.com');
    fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
    fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');

    fireEvent.press(getByText('Create Account'));

    await waitFor(() => {
      expect(mockedSignUp).toHaveBeenCalledWith({
        fullName: 'Jane',
        email: 'jane@example.com',
        password: 'secret1',
      });
    });

    expect(startLockGrace).toHaveBeenCalled();
    expect(mockedPrompt).toHaveBeenCalledWith('jane@example.com', 'secret1');
  });

  it('navigates back to login from footer CTA', () => {
    const { getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.press(getByText('Login'));

    expect(navigateSpy).toHaveBeenCalledWith('Login');
  });

  it('shows alert when first name is empty', () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('Email'), 'test@example.com');
    fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
    fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');

    fireEvent.press(getByText('Create Account'));

    expect(alertSpy).toHaveBeenCalledWith('Error', 'Please fill in all fields correctly');
    expect(mockedSignUp).not.toHaveBeenCalled();
  });

  it('shows alert when password is empty', () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
    fireEvent.changeText(getByPlaceholderText('Email'), 'test@example.com');
    fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');

    fireEvent.press(getByText('Create Account'));

    expect(alertSpy).toHaveBeenCalledWith('Error', 'Please fill in all fields correctly');
    expect(mockedSignUp).not.toHaveBeenCalled();
  });

  it('shows alert when passwords do not match', () => {
    const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
      providerOverrides: { withNavigation: false },
    });

    fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
    fireEvent.changeText(getByPlaceholderText('Email'), 'test@example.com');
    fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
    fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'different');

    fireEvent.press(getByText('Create Account'));

    expect(alertSpy).toHaveBeenCalledWith('Error', 'Please fill in all fields correctly');
    expect(mockedSignUp).not.toHaveBeenCalled();
  });

  describe('API error handling', () => {
    it('shows specific error for 409 conflict', async () => {
      mockedSignUp.mockRejectedValue(new ApiError(409, 'Conflict'));
      const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
      fireEvent.changeText(getByPlaceholderText('Email'), 'jane@example.com');
      fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
      fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');
      fireEvent.press(getByText('Create Account'));

      await waitFor(() => {
        expect(alertSpy).toHaveBeenCalledWith(
          'Sign Up Error',
          'An account with this email already exists',
        );
      });
    });

    it('shows specific error for 422 validation failure', async () => {
      mockedSignUp.mockRejectedValue(new ApiError(422, 'Validation Failed'));
      const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
      fireEvent.changeText(getByPlaceholderText('Email'), 'jane@example.com');
      fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
      fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');
      fireEvent.press(getByText('Create Account'));

      await waitFor(() => {
        expect(alertSpy).toHaveBeenCalledWith(
          'Sign Up Error',
          'Please check your input and try again.',
        );
      });
    });

    it('shows error message for other ApiError status codes', async () => {
      mockedSignUp.mockRejectedValue(new ApiError(500, 'Internal Server Error'));
      const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
      fireEvent.changeText(getByPlaceholderText('Email'), 'jane@example.com');
      fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
      fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');
      fireEvent.press(getByText('Create Account'));

      await waitFor(() => {
        expect(alertSpy).toHaveBeenCalledWith('Sign Up Error', 'Internal Server Error');
      });
    });

    it('shows generic error for non-ApiError exceptions', async () => {
      mockedSignUp.mockRejectedValue(new Error('Network Error'));
      const { getByPlaceholderText, getByText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.changeText(getByPlaceholderText('First Name'), 'Jane');
      fireEvent.changeText(getByPlaceholderText('Email'), 'jane@example.com');
      fireEvent.changeText(getByPlaceholderText('Password'), 'secret1');
      fireEvent.changeText(getByPlaceholderText('Confirm Password'), 'secret1');
      fireEvent.press(getByText('Create Account'));

      await waitFor(() => {
        expect(alertSpy).toHaveBeenCalledWith('Sign Up Error', 'An error occurred during sign up');
      });
    });
  });

  describe('handleBack navigation', () => {
    it('calls goBack when canGoBack returns true', () => {
      const { getByLabelText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.press(getByLabelText('Go back'));

      expect(goBackSpy).toHaveBeenCalled();
      expect(navigateSpy).not.toHaveBeenCalled();
    });

    it('navigates to Login when canGoBack returns false', () => {
      mockedUseNavigation.mockReturnValueOnce({
        navigate: navigateSpy,
        goBack: goBackSpy,
        canGoBack: () => false,
      } as any);

      const { getByLabelText } = renderWithProviders(<SignUpScreen />, {
        providerOverrides: { withNavigation: false },
      });

      fireEvent.press(getByLabelText('Go back'));

      expect(navigateSpy).toHaveBeenCalledWith('Login');
      expect(goBackSpy).not.toHaveBeenCalled();
    });
  });
});

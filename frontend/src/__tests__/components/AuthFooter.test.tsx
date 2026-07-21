import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import AuthFooter from '@/components/AuthFooter';

describe('AuthFooter', () => {
  it('renders actionText', () => {
    const { getByText } = renderWithProviders(<AuthFooter actionText="Sign Up" />);
    expect(getByText('Sign Up')).toBeTruthy();
  });

  it('renders prompt when provided', () => {
    const { getByText } = renderWithProviders(
      <AuthFooter prompt="Don't have an account?" actionText="Sign Up" />,
    );
    expect(getByText("Don't have an account?")).toBeTruthy();
  });

  it('does not render prompt when not provided', () => {
    const { queryByText } = renderWithProviders(<AuthFooter actionText="Sign Up" />);
    expect(queryByText("Don't have an account?")).toBeNull();
  });

  it('renders with empty prompt by default', () => {
    const { queryByText } = renderWithProviders(<AuthFooter actionText="Sign Up" />);
    // Default prompt is ''
    expect(queryByText("Don't have an account?")).toBeNull();
  });

  it('calls onPress when button is pressed', () => {
    const onPress = jest.fn();
    const { getByText } = renderWithProviders(<AuthFooter actionText="Login" onPress={onPress} />);
    fireEvent.press(getByText('Login'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', () => {
    const { getByText } = renderWithProviders(
      <AuthFooter actionText="Sign Up" style={{ marginTop: 20 }} />,
    );
    expect(getByText('Sign Up')).toBeTruthy();
  });
});

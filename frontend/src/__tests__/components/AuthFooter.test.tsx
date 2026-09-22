import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import AuthFooter from '@/components/AuthFooter';

describe('AuthFooter', () => {
  it('renders actionText', async () => {
    const { getByText } = await renderWithProviders(<AuthFooter actionText="Sign Up" />);
    expect(getByText('Sign Up')).toBeTruthy();
  });

  it('renders prompt when provided', async () => {
    const { getByText } = await renderWithProviders(
      <AuthFooter prompt="Don't have an account?" actionText="Sign Up" />,
    );
    expect(getByText("Don't have an account?")).toBeTruthy();
  });

  it('does not render prompt when not provided', async () => {
    const { queryByText } = await renderWithProviders(<AuthFooter actionText="Sign Up" />);
    expect(queryByText("Don't have an account?")).toBeNull();
  });

  it('renders with empty prompt by default', async () => {
    const { queryByText } = await renderWithProviders(<AuthFooter actionText="Sign Up" />);
    // Default prompt is ''
    expect(queryByText("Don't have an account?")).toBeNull();
  });

  it('calls onPress when button is pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(<AuthFooter actionText="Login" onPress={onPress} />);
    await fireEvent.press(getByText('Login'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(
      <AuthFooter actionText="Sign Up" style={{ marginTop: 20 }} />,
    );
    expect(getByText('Sign Up')).toBeTruthy();
  });
});

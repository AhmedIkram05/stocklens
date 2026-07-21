import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import DangerButton from '@/components/DangerButton';

describe('DangerButton', () => {
  it('renders children', () => {
    const { getByText } = renderWithProviders(<DangerButton>Delete Account</DangerButton>);
    expect(getByText('Delete Account')).toBeTruthy();
  });

  it('calls onPress when pressed', () => {
    const onPress = jest.fn();
    const { getByText } = renderWithProviders(
      <DangerButton onPress={onPress}>Delete</DangerButton>,
    );
    fireEvent.press(getByText('Delete'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', () => {
    const { getByText } = renderWithProviders(
      <DangerButton style={{ borderRadius: 0 }}>Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });

  it('accepts custom textStyle', () => {
    const { getByText } = renderWithProviders(
      <DangerButton textStyle={{ fontSize: 18 }}>Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });

  it('accepts accessibilityLabel', () => {
    const { getByText } = renderWithProviders(
      <DangerButton accessibilityLabel="Delete your account">Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });
});

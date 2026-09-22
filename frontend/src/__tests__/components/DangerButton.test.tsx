import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import DangerButton from '@/components/DangerButton';

describe('DangerButton', () => {
  it('renders children', async () => {
    const { getByText } = await renderWithProviders(<DangerButton>Delete Account</DangerButton>);
    expect(getByText('Delete Account')).toBeTruthy();
  });

  it('calls onPress when pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <DangerButton onPress={onPress}>Delete</DangerButton>,
    );
    await fireEvent.press(getByText('Delete'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(
      <DangerButton style={{ borderRadius: 0 }}>Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });

  it('accepts custom textStyle', async () => {
    const { getByText } = await renderWithProviders(
      <DangerButton textStyle={{ fontSize: 18 }}>Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });

  it('accepts accessibilityLabel', async () => {
    const { getByText } = await renderWithProviders(
      <DangerButton accessibilityLabel="Delete your account">Delete</DangerButton>,
    );
    expect(getByText('Delete')).toBeTruthy();
  });
});

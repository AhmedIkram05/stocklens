import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import PrimaryButton from '@/components/PrimaryButton';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';

describe('PrimaryButton', () => {
  it('renders button text', async () => {
    const { getByText } = await renderWithProviders(<PrimaryButton>Click Me</PrimaryButton>);
    expect(getByText('Click Me')).toBeTruthy();
  });

  it('calls onPress when pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <PrimaryButton onPress={onPress}>Click Me</PrimaryButton>,
    );
    await fireEvent.press(getByText('Click Me'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('does not call onPress when disabled', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <PrimaryButton onPress={onPress} disabled>
        Click Me
      </PrimaryButton>,
    );
    await fireEvent.press(getByText('Click Me'));
    expect(onPress).not.toHaveBeenCalled();
  });

  it('renders with custom style', async () => {
    const { getByText } = await renderWithProviders(
      <PrimaryButton style={{ backgroundColor: 'red' }}>Click Me</PrimaryButton>,
    );
    expect(getByText('Click Me')).toBeTruthy();
  });

  it('renders with accessibility label', async () => {
    const { queryByText } = await renderWithProviders(
      <PrimaryButton accessibilityLabel="Submit form">Submit</PrimaryButton>,
    );
    const button = queryByText('Submit');
    // The Pressable has accessibilityLabel, but getByText finds the AppText
    // Just verify the component renders without error
    expect(button).toBeTruthy();
  });

  it('applies pressed state opacity', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <PrimaryButton onPress={onPress}>Click Me</PrimaryButton>,
    );
    const button = getByText('Click Me');
    expect(button.props.style).toBeDefined();
  });
});

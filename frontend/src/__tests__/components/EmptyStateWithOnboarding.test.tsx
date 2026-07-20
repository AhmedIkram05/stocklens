import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import { EmptyStateWithOnboarding } from '@/components/EmptyStateWithOnboarding';

describe('EmptyStateWithOnboarding', () => {
  const defaultProps = {
    title: 'Get Started',
    subtitle: 'Start tracking your expenses',
    primaryText: 'Scan First Receipt',
    onPrimaryPress: jest.fn(),
  };

  it('renders title and subtitle', () => {
    const { getByText } = renderWithProviders(<EmptyStateWithOnboarding {...defaultProps} />);
    expect(getByText('Get Started')).toBeTruthy();
    expect(getByText('Start tracking your expenses')).toBeTruthy();
  });

  it('renders primary button text', () => {
    const { getByText } = renderWithProviders(<EmptyStateWithOnboarding {...defaultProps} />);
    expect(getByText('Scan First Receipt')).toBeTruthy();
  });

  it('calls onPrimaryPress when button is pressed', () => {
    const onPress = jest.fn();
    const { getByText } = renderWithProviders(
      <EmptyStateWithOnboarding {...defaultProps} onPrimaryPress={onPress} />,
    );
    fireEvent.press(getByText('Scan First Receipt'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('renders all 3 onboarding cards with step numbers', () => {
    const { getByText } = renderWithProviders(<EmptyStateWithOnboarding {...defaultProps} />);
    expect(getByText('1')).toBeTruthy();
    expect(getByText('2')).toBeTruthy();
    expect(getByText('3')).toBeTruthy();
  });

  it('renders onboarding card titles correctly', () => {
    const { getByText } = renderWithProviders(<EmptyStateWithOnboarding {...defaultProps} />);
    expect(getByText('Scan Your Receipts')).toBeTruthy();
    expect(getByText('See Investment Potential')).toBeTruthy();
    expect(getByText('Track Your Progress')).toBeTruthy();
  });

  it('renders onboarding card subtitles', () => {
    const { getByText } = renderWithProviders(<EmptyStateWithOnboarding {...defaultProps} />);
    expect(getByText('Take photos of your spending to track expenses')).toBeTruthy();
    expect(getByText('Discover what your spending could be worth if invested')).toBeTruthy();
    expect(
      getByText('Monitor your spending patterns and missed investment opportunities'),
    ).toBeTruthy();
  });

  it('accepts custom iconName', () => {
    const { getByText } = renderWithProviders(
      <EmptyStateWithOnboarding {...defaultProps} iconName="camera" />,
    );
    expect(getByText('Get Started')).toBeTruthy();
  });
});

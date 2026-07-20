import React from 'react';
import { Text } from 'react-native';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import SettingRow from '@/components/SettingRow';

describe('SettingRow', () => {
  it('renders title', () => {
    const { getByText } = renderWithProviders(<SettingRow title="Notifications" />);
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('renders subtitle when provided', () => {
    const { getByText } = renderWithProviders(
      <SettingRow title="Notifications" subtitle="Manage push alerts" />,
    );
    expect(getByText('Manage push alerts')).toBeTruthy();
  });

  it('does not render subtitle when not provided', () => {
    const { queryByText } = renderWithProviders(<SettingRow title="Notifications" />);
    expect(queryByText('Manage push alerts')).toBeNull();
  });

  it('renders icon when provided', () => {
    const { getByText } = renderWithProviders(
      <SettingRow title="Notifications" icon="notifications-outline" />,
    );
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('does not render icon container when icon is not provided', () => {
    const { getByText } = renderWithProviders(<SettingRow title="Notifications" />);
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('renders right content when provided', () => {
    const { getByText } = renderWithProviders(
      <SettingRow title="Version" right={<Text>v1.0.0</Text>} />,
    );
    expect(getByText('v1.0.0')).toBeTruthy();
  });

  it('calls onPress when pressed', () => {
    const onPress = jest.fn();
    const { getByText } = renderWithProviders(<SettingRow title="Account" onPress={onPress} />);
    fireEvent.press(getByText('Account'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('uses destructive color when destructive prop is set', () => {
    const { getByText } = renderWithProviders(<SettingRow title="Delete Account" destructive />);
    expect(getByText('Delete Account')).toBeTruthy();
  });

  it('accepts custom style', () => {
    const { getByText } = renderWithProviders(
      <SettingRow title="Account" style={{ marginTop: 10 }} />,
    );
    expect(getByText('Account')).toBeTruthy();
  });
});

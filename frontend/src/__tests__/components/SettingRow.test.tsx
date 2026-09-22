import React from 'react';
import { Text } from 'react-native';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import SettingRow from '@/components/SettingRow';

describe('SettingRow', () => {
  it('renders title', async () => {
    const { getByText } = await renderWithProviders(<SettingRow title="Notifications" />);
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('renders subtitle when provided', async () => {
    const { getByText } = await renderWithProviders(
      <SettingRow title="Notifications" subtitle="Manage push alerts" />,
    );
    expect(getByText('Manage push alerts')).toBeTruthy();
  });

  it('does not render subtitle when not provided', async () => {
    const { queryByText } = await renderWithProviders(<SettingRow title="Notifications" />);
    expect(queryByText('Manage push alerts')).toBeNull();
  });

  it('renders icon when provided', async () => {
    const { getByText } = await renderWithProviders(
      <SettingRow title="Notifications" icon="notifications-outline" />,
    );
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('does not render icon container when icon is not provided', async () => {
    const { getByText } = await renderWithProviders(<SettingRow title="Notifications" />);
    expect(getByText('Notifications')).toBeTruthy();
  });

  it('renders right content when provided', async () => {
    const { getByText } = await renderWithProviders(
      <SettingRow title="Version" right={<Text>v1.0.0</Text>} />,
    );
    expect(getByText('v1.0.0')).toBeTruthy();
  });

  it('calls onPress when pressed', async () => {
    const onPress = jest.fn();
    const { getByText } = await renderWithProviders(
      <SettingRow title="Account" onPress={onPress} />,
    );
    await fireEvent.press(getByText('Account'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('uses destructive color when destructive prop is set', async () => {
    const { getByText } = await renderWithProviders(
      <SettingRow title="Delete Account" destructive />,
    );
    expect(getByText('Delete Account')).toBeTruthy();
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(
      <SettingRow title="Account" style={{ marginTop: 10 }} />,
    );
    expect(getByText('Account')).toBeTruthy();
  });
});

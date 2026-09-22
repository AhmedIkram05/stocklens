import React from 'react';
import { Text } from 'react-native';
import { renderWithProviders } from '@/__tests__/utils';
import PageHeader from '@/components/PageHeader';

describe('PageHeader', () => {
  it('renders children text', async () => {
    const { getByText } = await renderWithProviders(<PageHeader>My Title</PageHeader>);
    expect(getByText('My Title')).toBeTruthy();
  });

  it('renders custom React element children', async () => {
    const { getByText } = await renderWithProviders(
      <PageHeader>
        <Text>Custom Title</Text>
      </PageHeader>,
    );
    expect(getByText('Custom Title')).toBeTruthy();
  });

  it('renders subtitle when provided', async () => {
    const { getByText } = await renderWithProviders(
      <PageHeader subtitle="This is a subtitle">Title</PageHeader>,
    );
    expect(getByText('This is a subtitle')).toBeTruthy();
  });

  it('does not render subtitle when not provided', async () => {
    const { queryByText } = await renderWithProviders(<PageHeader>Title</PageHeader>);
    expect(queryByText('This is a subtitle')).toBeNull();
  });

  it('handles string children correctly', async () => {
    const { getByText } = await renderWithProviders(<PageHeader>Dashboard</PageHeader>);
    expect(getByText('Dashboard')).toBeTruthy();
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(
      <PageHeader style={{ marginBottom: 0 }}>Title</PageHeader>,
    );
    expect(getByText('Title')).toBeTruthy();
  });
});

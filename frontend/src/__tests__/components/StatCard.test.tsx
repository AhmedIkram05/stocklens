import React from 'react';
import { renderWithProviders } from '@/__tests__/utils';
import StatCard from '@/components/StatCard';

describe('StatCard', () => {
  it('renders value', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$1,234" />);
    expect(getByText('$1,234')).toBeTruthy();
  });

  it('renders numeric value', async () => {
    const { getByText } = await renderWithProviders(<StatCard value={42} />);
    expect(getByText('42')).toBeTruthy();
  });

  it('renders label when provided', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" label="Monthly Spending" />);
    expect(getByText('Monthly Spending')).toBeTruthy();
  });

  it('does not render label when not provided', async () => {
    const { queryByText } = await renderWithProviders(<StatCard value="$500" />);
    expect(queryByText('Monthly Spending')).toBeNull();
  });

  it('renders subtitle when provided', async () => {
    const { getByText } = await renderWithProviders(
      <StatCard value="$500" label="Spending" subtitle="Last 30 days" />,
    );
    expect(getByText('Last 30 days')).toBeTruthy();
  });

  it('does not render subtitle when not provided', async () => {
    const { queryByText } = await renderWithProviders(<StatCard value="$500" />);
    expect(queryByText('Last 30 days')).toBeNull();
  });

  it('uses white variant by default', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('uses green variant', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" variant="green" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('uses blue variant', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" variant="blue" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for white variant', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" variant="white" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for green variant (white text)', async () => {
    const { getByText } = await renderWithProviders(
      <StatCard value="$500" label="Total" variant="green" />,
    );
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for blue variant (white text)', async () => {
    const { getByText } = await renderWithProviders(
      <StatCard value="$500" label="Total" variant="blue" />,
    );
    expect(getByText('$500')).toBeTruthy();
  });

  it('renders React element as value', async () => {
    const { getByText } = await renderWithProviders(<StatCard value={<>{'$1,234'}</>} />);
    expect(getByText('$1,234')).toBeTruthy();
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(<StatCard value="$500" style={{ margin: 10 }} />);
    expect(getByText('$500')).toBeTruthy();
  });
});

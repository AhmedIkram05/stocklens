import React from 'react';
import { renderWithProviders } from '@/__tests__/utils';
import StatCard from '@/components/StatCard';

describe('StatCard', () => {
  it('renders value', () => {
    const { getByText } = renderWithProviders(<StatCard value="$1,234" />);
    expect(getByText('$1,234')).toBeTruthy();
  });

  it('renders numeric value', () => {
    const { getByText } = renderWithProviders(<StatCard value={42} />);
    expect(getByText('42')).toBeTruthy();
  });

  it('renders label when provided', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" label="Monthly Spending" />);
    expect(getByText('Monthly Spending')).toBeTruthy();
  });

  it('does not render label when not provided', () => {
    const { queryByText } = renderWithProviders(<StatCard value="$500" />);
    expect(queryByText('Monthly Spending')).toBeNull();
  });

  it('renders subtitle when provided', () => {
    const { getByText } = renderWithProviders(
      <StatCard value="$500" label="Spending" subtitle="Last 30 days" />,
    );
    expect(getByText('Last 30 days')).toBeTruthy();
  });

  it('does not render subtitle when not provided', () => {
    const { queryByText } = renderWithProviders(<StatCard value="$500" />);
    expect(queryByText('Last 30 days')).toBeNull();
  });

  it('uses white variant by default', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('uses green variant', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" variant="green" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('uses blue variant', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" variant="blue" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for white variant', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" variant="white" />);
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for green variant (white text)', () => {
    const { getByText } = renderWithProviders(
      <StatCard value="$500" label="Total" variant="green" />,
    );
    expect(getByText('$500')).toBeTruthy();
  });

  it('applies correct text color for blue variant (white text)', () => {
    const { getByText } = renderWithProviders(
      <StatCard value="$500" label="Total" variant="blue" />,
    );
    expect(getByText('$500')).toBeTruthy();
  });

  it('renders React element as value', () => {
    const { getByText } = renderWithProviders(<StatCard value={<>{'$1,234'}</>} />);
    expect(getByText('$1,234')).toBeTruthy();
  });

  it('accepts custom style', () => {
    const { getByText } = renderWithProviders(<StatCard value="$500" style={{ margin: 10 }} />);
    expect(getByText('$500')).toBeTruthy();
  });
});

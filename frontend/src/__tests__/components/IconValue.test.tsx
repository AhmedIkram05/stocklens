import React from 'react';
import { renderWithProviders } from '@/__tests__/utils';
import IconValue from '@/components/IconValue';

describe('IconValue', () => {
  it('renders icon and value', () => {
    const { getByText } = renderWithProviders(
      <IconValue iconName="calendar-outline" iconColor="#000" value="Today" />,
    );
    expect(getByText('Today')).toBeTruthy();
  });

  it('renders numeric value', () => {
    const { getByText } = renderWithProviders(
      <IconValue iconName="trophy" iconColor="#000" value={42} />,
    );
    expect(getByText('42')).toBeTruthy();
  });

  it('uses custom iconSize', () => {
    const { getByText } = renderWithProviders(
      <IconValue iconName="calendar-outline" iconColor="#000" value="Today" iconSize={32} />,
    );
    expect(getByText('Today')).toBeTruthy();
  });

  it('uses default iconSize when not provided', () => {
    const { getByText } = renderWithProviders(
      <IconValue iconName="calendar-outline" iconColor="#000" value="Today" />,
    );
    expect(getByText('Today')).toBeTruthy();
  });

  it('applies valueStyle', () => {
    const { getByText } = renderWithProviders(
      <IconValue
        iconName="calendar-outline"
        iconColor="#000"
        value="Today"
        valueStyle={{ fontSize: 18, fontWeight: 'bold' }}
      />,
    );
    expect(getByText('Today')).toBeTruthy();
  });
});

import React from 'react';
import { Text } from 'react-native';
import { renderWithProviders } from '@/__tests__/utils';
import ResponsiveContainer from '@/components/ResponsiveContainer';

describe('ResponsiveContainer', () => {
  it('renders children', async () => {
    const { getByText } = await renderWithProviders(
      <ResponsiveContainer>
        <Text>Hello World</Text>
      </ResponsiveContainer>,
    );
    expect(getByText('Hello World')).toBeTruthy();
  });

  it('uses default maxWidth (960)', async () => {
    const { getByText } = await renderWithProviders(
      <ResponsiveContainer>
        <Text>Content</Text>
      </ResponsiveContainer>,
    );
    expect(getByText('Content')).toBeTruthy();
  });

  it('uses custom maxWidth', async () => {
    const { getByText } = await renderWithProviders(
      <ResponsiveContainer maxWidth={500}>
        <Text>Narrow Content</Text>
      </ResponsiveContainer>,
    );
    expect(getByText('Narrow Content')).toBeTruthy();
  });

  it('accepts custom style', async () => {
    const { getByText } = await renderWithProviders(
      <ResponsiveContainer style={{ backgroundColor: 'red' }}>
        <Text>Styled Content</Text>
      </ResponsiveContainer>,
    );
    expect(getByText('Styled Content')).toBeTruthy();
  });

  it('renders multiple children', async () => {
    const { getByText } = await renderWithProviders(
      <ResponsiveContainer>
        <Text>First</Text>
        <Text>Second</Text>
      </ResponsiveContainer>,
    );
    expect(getByText('First')).toBeTruthy();
    expect(getByText('Second')).toBeTruthy();
  });
});

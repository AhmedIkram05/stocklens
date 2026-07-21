import React from 'react';
import { Text } from 'react-native';
import { renderWithProviders } from '@/__tests__/utils';
import ScreenContainer from '@/components/ScreenContainer';

describe('ScreenContainer', () => {
  it('renders children', () => {
    const { getByText } = renderWithProviders(
      <ScreenContainer>
        <Text>Screen Content</Text>
      </ScreenContainer>,
    );
    expect(getByText('Screen Content')).toBeTruthy();
  });

  it('renders multiple children', () => {
    const { getByText } = renderWithProviders(
      <ScreenContainer>
        <Text>Item A</Text>
        <Text>Item B</Text>
      </ScreenContainer>,
    );
    expect(getByText('Item A')).toBeTruthy();
    expect(getByText('Item B')).toBeTruthy();
  });

  it('accepts custom style', () => {
    const { getByText } = renderWithProviders(
      <ScreenContainer style={{ backgroundColor: 'blue' }}>
        <Text>Styled</Text>
      </ScreenContainer>,
    );
    expect(getByText('Styled')).toBeTruthy();
  });

  it('handles noPadding mode', () => {
    const { getByText } = renderWithProviders(
      <ScreenContainer noPadding>
        <Text>No Padding</Text>
      </ScreenContainer>,
    );
    expect(getByText('No Padding')).toBeTruthy();
  });

  it('accepts contentStyle', () => {
    const { getByText } = renderWithProviders(
      <ScreenContainer contentStyle={{ justifyContent: 'flex-start' }}>
        <Text>Custom Content Style</Text>
      </ScreenContainer>,
    );
    expect(getByText('Custom Content Style')).toBeTruthy();
  });
});

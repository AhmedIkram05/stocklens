/**
 * BackButton — unit tests.
 * Self-contained renderer (relative imports) because the shared
 * renderWithProviders util relies on the `@` path alias, which is
 * currently broken in this jest setup (see repo note).
 */
import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { render } from '@testing-library/react-native';
import { ThemeContext, lightTheme } from '../../contexts/ThemeContext';
import BackButton from '../../components/BackButton';

const mockGoBack = jest.fn();

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return { ...actual, useNavigation: () => ({ goBack: mockGoBack }) };
});

const renderBackButton = (ui: React.ReactElement) =>
  render(
    <ThemeContext.Provider
      value={{ theme: lightTheme, mode: 'light', isDark: false, setMode: () => {} }}
    >
      {ui}
    </ThemeContext.Provider>,
  );

describe('BackButton', () => {
  beforeEach(() => mockGoBack.mockClear());

  it('icon variant calls navigation.goBack on press', () => {
    const { getByLabelText } = renderBackButton(<BackButton />);
    fireEvent.press(getByLabelText('Go back'));
    expect(mockGoBack).toHaveBeenCalledTimes(1);
  });

  it('text variant renders the label and honours a custom onPress', () => {
    const onPress = jest.fn();
    const { getByText } = renderBackButton(
      <BackButton variant="text" label="Cancel" onPress={onPress} />,
    );
    fireEvent.press(getByText('Cancel'));
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(mockGoBack).not.toHaveBeenCalled();
  });

  it('does not fire when disabled', () => {
    const onPress = jest.fn();
    const { getByText } = renderBackButton(
      <BackButton variant="text" label="Cancel" disabled onPress={onPress} />,
    );
    fireEvent.press(getByText('Cancel'));
    expect(onPress).not.toHaveBeenCalled();
    expect(mockGoBack).not.toHaveBeenCalled();
  });
});

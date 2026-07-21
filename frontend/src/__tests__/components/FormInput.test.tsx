import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import FormInput from '@/components/FormInput';

describe('FormInput', () => {
  it('renders with placeholder', () => {
    const { getByPlaceholderText } = renderWithProviders(<FormInput placeholder="Enter email" />);
    expect(getByPlaceholderText('Enter email')).toBeTruthy();
  });

  it('accepts value and onChangeText', () => {
    const onChangeText = jest.fn();
    const { getByDisplayValue } = renderWithProviders(
      <FormInput value="test@example.com" onChangeText={onChangeText} />,
    );
    expect(getByDisplayValue('test@example.com')).toBeTruthy();
  });

  it('shows password toggle when showPasswordToggle and secureTextEntry are true', () => {
    const { getByLabelText } = renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    expect(getByLabelText('Show password')).toBeTruthy();
  });

  it('does not show password toggle when showPasswordToggle is false', () => {
    const { queryByLabelText } = renderWithProviders(
      <FormInput placeholder="Password" secureTextEntry />,
    );
    expect(queryByLabelText('Show password')).toBeNull();
  });

  it('does not show password toggle when secureTextEntry is false', () => {
    const { queryByLabelText } = renderWithProviders(
      <FormInput placeholder="Text" showPasswordToggle secureTextEntry={false} />,
    );
    expect(queryByLabelText('Show password')).toBeNull();
  });

  it('toggle reveals password when pressed', () => {
    const { getByLabelText, queryByLabelText } = renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    // Initially shows eye icon (password hidden)
    const showButton = getByLabelText('Show password');
    fireEvent.press(showButton);
    // After press, should show hide button
    expect(queryByLabelText('Hide password')).toBeTruthy();
  });

  it('toggle hides password when pressed twice', () => {
    const { getByLabelText } = renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    const showButton = getByLabelText('Show password');
    fireEvent.press(showButton);
    const hideButton = getByLabelText('Hide password');
    fireEvent.press(hideButton);
    // Back to show password state
    expect(getByLabelText('Show password')).toBeTruthy();
  });

  it('accepts containerStyle', () => {
    const { getByPlaceholderText } = renderWithProviders(
      <FormInput placeholder="Email" containerStyle={{ marginBottom: 0 }} />,
    );
    expect(getByPlaceholderText('Email')).toBeTruthy();
  });

  it('accepts inputStyle', () => {
    const { getByPlaceholderText } = renderWithProviders(
      <FormInput placeholder="Email" inputStyle={{ fontSize: 16 }} />,
    );
    expect(getByPlaceholderText('Email')).toBeTruthy();
  });
});

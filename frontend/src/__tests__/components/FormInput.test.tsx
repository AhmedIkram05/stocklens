import React from 'react';
import { fireEvent } from '@testing-library/react-native';
import { renderWithProviders } from '@/__tests__/utils';
import FormInput from '@/components/FormInput';

describe('FormInput', () => {
  it('renders with placeholder', async () => {
    const { getByPlaceholderText } = await renderWithProviders(
      <FormInput placeholder="Enter email" />,
    );
    expect(getByPlaceholderText('Enter email')).toBeTruthy();
  });

  it('accepts value and onChangeText', async () => {
    const onChangeText = jest.fn();
    const { getByDisplayValue } = await renderWithProviders(
      <FormInput value="test@example.com" onChangeText={onChangeText} />,
    );
    expect(getByDisplayValue('test@example.com')).toBeTruthy();
  });

  it('shows password toggle when showPasswordToggle and secureTextEntry are true', async () => {
    const { getByLabelText } = await renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    expect(getByLabelText('Show password')).toBeTruthy();
  });

  it('does not show password toggle when showPasswordToggle is false', async () => {
    const { queryByLabelText } = await renderWithProviders(
      <FormInput placeholder="Password" secureTextEntry />,
    );
    expect(queryByLabelText('Show password')).toBeNull();
  });

  it('does not show password toggle when secureTextEntry is false', async () => {
    const { queryByLabelText } = await renderWithProviders(
      <FormInput placeholder="Text" showPasswordToggle secureTextEntry={false} />,
    );
    expect(queryByLabelText('Show password')).toBeNull();
  });

  it('toggle reveals password when pressed', async () => {
    const { getByLabelText, queryByLabelText } = await renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    // Initially shows eye icon (password hidden)
    const showButton = getByLabelText('Show password');
    await fireEvent.press(showButton);
    // After press, should show hide button
    expect(queryByLabelText('Hide password')).toBeTruthy();
  });

  it('toggle hides password when pressed twice', async () => {
    const { getByLabelText } = await renderWithProviders(
      <FormInput placeholder="Password" showPasswordToggle secureTextEntry />,
    );
    const showButton = getByLabelText('Show password');
    await fireEvent.press(showButton);
    const hideButton = getByLabelText('Hide password');
    await fireEvent.press(hideButton);
    // Back to show password state
    expect(getByLabelText('Show password')).toBeTruthy();
  });

  it('accepts containerStyle', async () => {
    const { getByPlaceholderText } = await renderWithProviders(
      <FormInput placeholder="Email" containerStyle={{ marginBottom: 0 }} />,
    );
    expect(getByPlaceholderText('Email')).toBeTruthy();
  });

  it('accepts inputStyle', async () => {
    const { getByPlaceholderText } = await renderWithProviders(
      <FormInput placeholder="Email" inputStyle={{ fontSize: 16 }} />,
    );
    expect(getByPlaceholderText('Email')).toBeTruthy();
  });
});

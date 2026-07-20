/**
 * Tests for `ConfirmationPrompt` — the receipt scan confirmation dialog.
 * Covers showConfirmationPrompt with various display amounts and merchant.
 */

import { Alert } from 'react-native';
import { showConfirmationPrompt } from '@/components/ConfirmationPrompt';

describe('showConfirmationPrompt', () => {
  beforeEach(() => {
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('shows confirm dialog with detected amount', () => {
    const handlers = {
      onConfirm: jest.fn(),
      onEnterManually: jest.fn(),
      onRescan: jest.fn(),
    };

    showConfirmationPrompt('£25.00', handlers, 'Tesco');

    expect(Alert.alert).toHaveBeenCalledWith(
      'Confirm scanned total',
      expect.stringContaining('£25.00'),
      expect.arrayContaining([
        expect.objectContaining({ text: 'Confirm' }),
        expect.objectContaining({ text: 'Enter manually' }),
        expect.objectContaining({ text: 'Rescan' }),
      ]),
      expect.any(Object),
    );
  });

  it('includes merchant name in message when provided', () => {
    showConfirmationPrompt(
      '£42.50',
      {
        onConfirm: jest.fn(),
        onEnterManually: jest.fn(),
        onRescan: jest.fn(),
      },
      'Waitrose',
    );

    expect(Alert.alert).toHaveBeenCalledWith(
      'Confirm scanned total',
      expect.stringContaining('Waitrose'),
      expect.any(Array),
      expect.any(Object),
    );
  });

  it('shows "No amount detected" when amount is empty', () => {
    showConfirmationPrompt('', {
      onConfirm: jest.fn(),
      onEnterManually: jest.fn(),
      onRescan: jest.fn(),
    });

    expect(Alert.alert).toHaveBeenCalledWith(
      'Confirm scanned total',
      expect.stringContaining('No amount detected'),
      expect.any(Array),
      expect.any(Object),
    );
  });

  it('calls onConfirm when Confirm button is pressed', () => {
    const handlers = {
      onConfirm: jest.fn(),
      onEnterManually: jest.fn(),
      onRescan: jest.fn(),
    };

    let confirmPress: () => void = () => {};
    (Alert.alert as jest.Mock).mockImplementation(
      (_title: string, _msg: string, buttons: any[]) => {
        const confirm = buttons.find((b: any) => b.text === 'Confirm');
        if (confirm) confirmPress = confirm.onPress;
      },
    );

    showConfirmationPrompt('£10.00', handlers);
    confirmPress();

    expect(handlers.onConfirm).toHaveBeenCalled();
  });

  it('calls onEnterManually when Enter manually button is pressed', () => {
    const handlers = {
      onConfirm: jest.fn(),
      onEnterManually: jest.fn(),
      onRescan: jest.fn(),
    };

    let enterPress: () => void = () => {};
    (Alert.alert as jest.Mock).mockImplementation(
      (_title: string, _msg: string, buttons: any[]) => {
        const btn = buttons.find((b: any) => b.text === 'Enter manually');
        if (btn) enterPress = btn.onPress;
      },
    );

    showConfirmationPrompt('£10.00', handlers);
    enterPress();

    expect(handlers.onEnterManually).toHaveBeenCalled();
  });

  it('calls onRescan when Rescan button is pressed', () => {
    const handlers = {
      onConfirm: jest.fn(),
      onEnterManually: jest.fn(),
      onRescan: jest.fn(),
    };

    let rescanPress: () => void = () => {};
    (Alert.alert as jest.Mock).mockImplementation(
      (_title: string, _msg: string, buttons: any[]) => {
        const btn = buttons.find((b: any) => b.text === 'Rescan');
        if (btn) rescanPress = btn.onPress;
      },
    );

    showConfirmationPrompt('£10.00', handlers);
    rescanPress();

    expect(handlers.onRescan).toHaveBeenCalled();
  });

  it('handles handler exceptions gracefully', () => {
    const handlers = {
      onConfirm: jest.fn(() => {
        throw new Error('fail');
      }),
      onEnterManually: jest.fn(() => {
        throw new Error('fail');
      }),
      onRescan: jest.fn(() => {
        throw new Error('fail');
      }),
    };

    let confirmPress: () => void = () => {};
    (Alert.alert as jest.Mock).mockImplementation(
      (_title: string, _msg: string, buttons: any[]) => {
        const btn = buttons.find((b: any) => b.text === 'Confirm');
        if (btn) confirmPress = btn.onPress;
      },
    );

    showConfirmationPrompt('£10.00', handlers);
    // Should not throw
    expect(() => confirmPress()).not.toThrow();
  });
});

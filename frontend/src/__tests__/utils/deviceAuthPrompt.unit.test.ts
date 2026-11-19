/**
 * Tests for the device-auth enrollment prompt (`promptEnableDeviceAuth`).
 * Verifies hardware checks, alert presentation, and credential save/decline flows.
 */

import { Alert } from 'react-native';
import * as deviceAuth from '@/hooks/useDeviceAuth';

jest.mock('@/hooks/useDeviceAuth', () => ({
  isDeviceAuthAvailable: jest.fn(),
  setDeviceEnabled: jest.fn(),
  clearDeviceCredentials: jest.fn(async () => {}),
}));

const { promptEnableDeviceAuth } = require('@/utils/deviceAuthPrompt');

const alertSpy = jest.spyOn(Alert, 'alert');
const mockedDeviceAuth = deviceAuth as jest.Mocked<typeof deviceAuth>;

describe('deviceAuthPrompt', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    alertSpy.mockClear();
  });

  it('returns false when device auth hardware unavailable', async () => {
    mockedDeviceAuth.isDeviceAuthAvailable.mockResolvedValue(false);

    const result = await promptEnableDeviceAuth();

    expect(result).toBe(false);
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('shows prompt when device auth available and saves on acceptance', async () => {
    mockedDeviceAuth.isDeviceAuthAvailable.mockResolvedValue(true);
    mockedDeviceAuth.setDeviceEnabled.mockResolvedValue(undefined);

    const promptPromise = promptEnableDeviceAuth();

    await new Promise((resolve) => setImmediate(resolve));

    expect(alertSpy).toHaveBeenCalledWith(
      'Enable Device Auth?',
      expect.any(String),
      expect.any(Array),
      expect.any(Object),
    );

    const alertCall = alertSpy.mock.calls[0];
    const buttons = alertCall[2] as any[];
    const yesButton = buttons.find((b) => b.text === 'Yes');

    await yesButton.onPress();

    const result = await promptPromise;

    expect(mockedDeviceAuth.setDeviceEnabled).toHaveBeenCalledWith(true);
    expect(result).toBe(true);
  });

  it('returns false when user declines (presses No)', async () => {
    mockedDeviceAuth.isDeviceAuthAvailable.mockResolvedValue(true);

    const resultPromise = promptEnableDeviceAuth();

    await new Promise((resolve) => setImmediate(resolve));

    expect(alertSpy).toHaveBeenCalledWith(
      'Enable Device Auth?',
      expect.any(String),
      expect.any(Array),
      expect.any(Object),
    );

    const alertCall = alertSpy.mock.calls[0];
    const buttons = alertCall[2] as any[];
    const noButton = buttons.find((b: any) => b.text === 'No');

    await noButton.onPress();

    const result = await resultPromise;
    expect(result).toBe(false);
    expect(mockedDeviceAuth.clearDeviceCredentials).toHaveBeenCalled();
  });
});

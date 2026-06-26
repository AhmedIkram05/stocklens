/**
 * Tests for `ScanScreen` (integration).
 * Verifies camera permission handling, photo capture/draft creation,
 * OCR invocation, and manual-entry flows.
 */

import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import ScanScreen from '@/screens/ScanScreen';
import { renderWithProviders } from '../utils';
import { useReceiptCapture } from '@/hooks/useReceiptCapture';
import { receiptService } from '@/services/dataService';

jest.mock('@/hooks/useReceiptCapture', () => ({
  useReceiptCapture: jest.fn(),
}));

jest.mock('@/services/dataService', () => ({
  receiptService: {
    create: jest.fn(),
  },
}));

jest.mock('@/services/eventBus', () => ({
  emit: jest.fn(),
}));

jest.mock('expo-camera', () => {
  const React = require('react');
  const { View } = require('react-native');
  const mockTakePictureAsync = jest.fn();
  const CameraView = React.forwardRef((props: any, ref: any) => {
    React.useImperativeHandle(ref, () => ({
      takePictureAsync: mockTakePictureAsync,
    }));
    return <View accessibilityRole="image" {...props} />;
  });
  return {
    __esModule: true,
    CameraView,
    useCameraPermissions: jest.fn(),
    CameraType: { back: 'back', front: 'front' },
    __mockTakePictureAsync: mockTakePictureAsync,
  };
});

const cameraModule = require('expo-camera');
const mockUseCameraPermissions = cameraModule.useCameraPermissions as jest.Mock;
const mockTakePictureAsync = cameraModule.__mockTakePictureAsync as jest.Mock;

const mockedUseReceiptCapture = useReceiptCapture as jest.MockedFunction<typeof useReceiptCapture>;
const mockedReceiptService = receiptService as jest.Mocked<typeof receiptService>;

const renderScreen = (overrides?: { authUid?: string }) =>
  renderWithProviders(<ScanScreen />, {
    providerOverrides: {
      authValue: {
        userProfile: { uid: overrides?.authUid ?? 'user-1' } as any,
        user: { uid: overrides?.authUid ?? 'user-1' } as any,
      },
    },
  });

const createHookState = () => {
  const hookReturn = {
    state: {
      processing: false,
      ocrRaw: null,
      draftReceiptId: null,
      manualModalVisible: false,
      manualEntryText: '',
    },
    actions: {
      setDraftReceiptId: jest.fn(),
      setManualEntryText: jest.fn(),
      setManualModalVisible: jest.fn(),
      processReceipt: jest.fn(),
      saveAndNavigate: jest.fn(),
    },
    pendingRef: { current: {} },
  } as any;

  mockedUseReceiptCapture.mockReturnValue(hookReturn);
  return hookReturn;
};

describe('ScanScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseCameraPermissions.mockReturnValue([{ granted: true }, jest.fn()]);
    mockTakePictureAsync.mockReset();
  });

  it('renders permission prompt when camera access is denied', () => {
    createHookState();
    mockUseCameraPermissions.mockReturnValue([{ granted: false }, jest.fn()]);

    const { getByTestId } = renderScreen();

    expect(getByTestId('camera-permission-text')).toBeTruthy();
  });

  it('captures a photo, creates a draft receipt, and forwards to the OCR workflow', async () => {
    const hook = createHookState();
    mockedReceiptService.create.mockResolvedValue(55 as any);
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://snap.jpg', base64: 'YmFzZTY0' });

    const { getByTestId, queryByTestId } = renderScreen();

    fireEvent.press(getByTestId('capture-button'));

    await waitFor(() => expect(hook.actions.processReceipt).toHaveBeenCalled());

    expect(mockedReceiptService.create).toHaveBeenCalledWith({
      user_id: 'user-1',
      image_uri: 'file://snap.jpg',
      total_amount: undefined,
      ocr_data: '',
      synced: 0,
    });
    expect(hook.actions.setDraftReceiptId).toHaveBeenCalledWith(55);
    expect(hook.actions.processReceipt).toHaveBeenCalledWith({
      photoUri: 'file://snap.jpg',
      photoBase64: 'YmFzZTY0',
      draftIdArg: 55,
    });

    await waitFor(() => expect(queryByTestId('scan-preview-image')).toBeTruthy());
  });

  it('submits manual entry amounts via saveAndNavigate', async () => {
    const hook = createHookState();
    mockedReceiptService.create.mockResolvedValue(99 as any);
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://manual.jpg', base64: 'bWFudWFs' });

    const screen = renderScreen();

    fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(hook.actions.processReceipt).toHaveBeenCalled());

    hook.state.manualModalVisible = true;
    hook.state.manualEntryText = '45.67';
    hook.state.draftReceiptId = 99;
    hook.state.ocrRaw = 'Total £45.67';

    screen.rerender(<ScanScreen />);

    fireEvent.press(screen.getByTestId('manual-confirm-button'));

    await waitFor(() =>
      expect(hook.actions.saveAndNavigate).toHaveBeenCalledWith(
        45.67,
        99,
        'Total £45.67',
        'file://manual.jpg',
      ),
    );
    expect(hook.actions.setManualModalVisible).toHaveBeenCalledWith(false);
  });
});

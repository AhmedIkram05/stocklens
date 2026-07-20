import React from 'react';
import { fireEvent, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';
import ScanScreen from '@/screens/ScanScreen';
import { renderWithProviders } from '../utils';
import { useReceiptCapture } from '@/hooks/useReceiptCapture';

jest.mock('@/hooks/useReceiptCapture', () => ({
  useReceiptCapture: jest.fn(),
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

const renderScreen = () => renderWithProviders(<ScanScreen />);

const createHookState = () => {
  const hookReturn = {
    state: {
      processing: false,
      ocrRaw: null,
      manualModalVisible: false,
      manualEntryText: '',
    },
    actions: {
      setManualEntryText: jest.fn(),
      setManualModalVisible: jest.fn(),
      processReceipt: jest.fn(),
      saveAndNavigate: jest.fn(),
      discardDraft: jest.fn(),
      resetWorkflowState: jest.fn(),
      clearPhotoPreview: jest.fn(),
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

  it('captures a photo and forwards to the OCR workflow', async () => {
    const hook = createHookState();
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://snap.jpg', base64: 'YmFzZTY0' });

    const { getByTestId, queryByTestId } = renderScreen();

    fireEvent.press(getByTestId('capture-button'));

    await waitFor(() =>
      expect(hook.actions.processReceipt).toHaveBeenCalledWith({
        photoUri: 'file://snap.jpg',
      }),
    );

    await waitFor(() => expect(queryByTestId('scan-preview-image')).toBeTruthy());
  });

  it('submits manual entry amounts via saveAndNavigate', async () => {
    const hook = createHookState();
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://manual.jpg', base64: 'bWFudWFs' });

    const screen = renderScreen();

    fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(hook.actions.processReceipt).toHaveBeenCalled());

    hook.state.manualModalVisible = true;
    hook.state.manualEntryText = '45.67';
    hook.state.ocrRaw = 'Total £45.67';

    screen.rerender(<ScanScreen />);

    fireEvent.press(screen.getByTestId('manual-confirm-button'));

    await waitFor(() =>
      expect(hook.actions.saveAndNavigate).toHaveBeenCalledWith(
        45.67,
        'Total £45.67',
        'file://manual.jpg',
      ),
    );
    expect(hook.actions.setManualModalVisible).toHaveBeenCalledWith(false);
  });

  it('shows alert when camera capture fails', async () => {
    mockTakePictureAsync.mockRejectedValue(new Error('camera error'));

    const { getByTestId } = renderScreen();

    fireEvent.press(getByTestId('capture-button'));

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith('Error', 'Failed to capture image');
    });
  });

  it('shows invalid amount alert when manual entry value is not a number', async () => {
    const hook = createHookState();
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://bad.jpg', base64: 'YmFk' });

    const screen = renderScreen();
    fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(hook.actions.processReceipt).toHaveBeenCalled());

    hook.state.manualModalVisible = true;
    hook.state.manualEntryText = 'abc';
    screen.rerender(<ScanScreen />);

    fireEvent.press(screen.getByTestId('manual-confirm-button'));

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith('Invalid amount', 'Enter a valid number');
    });
  });

  it('cancel manual entry triggers discard and reset', async () => {
    const hook = createHookState();
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://cancel.jpg', base64: 'Y2FuY2Vs' });

    const screen = renderScreen();
    fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(hook.actions.processReceipt).toHaveBeenCalled());

    hook.state.manualModalVisible = true;
    screen.rerender(<ScanScreen />);

    fireEvent.press(screen.getByText('Cancel'));

    await waitFor(() => {
      expect(hook.actions.discardDraft).toHaveBeenCalled();
      expect(hook.actions.resetWorkflowState).toHaveBeenCalled();
      expect(hook.actions.setManualModalVisible).toHaveBeenCalledWith(false);
    });
  });

  it('retake button resets the camera', async () => {
    const hook = createHookState();
    mockTakePictureAsync.mockResolvedValue({ uri: 'file://snap.jpg', base64: 'YmFzZTY0' });

    const { getByTestId, queryByTestId } = renderScreen();

    fireEvent.press(getByTestId('capture-button'));

    await waitFor(() => expect(queryByTestId('scan-preview-image')).toBeTruthy());

    fireEvent.press(getByTestId('retake-button'));

    expect(hook.actions.resetWorkflowState).toHaveBeenCalled();
  });
});

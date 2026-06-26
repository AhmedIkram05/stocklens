/**
 * ScanScreen
 *
 * Camera view for capturing receipts and extracting amounts via OCR.
 */

import React, { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Alert,
  Image,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import ScreenContainer from '../components/ScreenContainer';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CameraView, CameraType, useCameraPermissions } from 'expo-camera';
import { brandColors, useTheme } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { receiptService } from '../services/dataService';
import { emit } from '../services/eventBus';
import { useAuth } from '../contexts/AuthContext';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { useReceiptCapture } from '../hooks/useReceiptCapture';

/** Camera/receipt capture screen. */
export default function ScanScreen() {
  const { userProfile } = useAuth();
  const navigation = useNavigation<any>();
  const facing: CameraType = 'back';
  const [permission, requestPermission] = useCameraPermissions();
  const [photo, setPhoto] = useState<string | null>(null);
  const [, setPhotoBase64] = useState<string | null>(null);
  const [isCameraActive, setIsCameraActive] = useState(true);
  const clearPhotoPreview = useCallback(() => {
    setPhoto(null);
    setPhotoBase64(null);
  }, []);
  const capture = useReceiptCapture({
    navigation,
    userUid: userProfile?.uid,
    onResetCamera: clearPhotoPreview,
  });
  const { processing, ocrRaw, draftReceiptId, manualModalVisible, manualEntryText } = capture.state;
  const {
    setDraftReceiptId,
    setManualEntryText,
    setManualModalVisible,
    processReceipt,
    saveAndNavigate,
    discardDraft,
    resetWorkflowState,
  } = capture.actions;
  const cameraRef = useRef<CameraView>(null);
  const { isSmallPhone, isTablet, contentHorizontalPadding, sectionVerticalSpacing } =
    useBreakpoint();
  const insets = useSafeAreaInsets();
  const { theme } = useTheme();

  const captureButtonSize = isSmallPhone ? 60 : isTablet ? 80 : 70;

  useFocusEffect(
    useCallback(() => {
      setIsCameraActive(true);
      return () => setIsCameraActive(false);
    }, []),
  );

  if (!permission) {
    return <View />;
  }

  if (!permission.granted) {
    return (
      <ScreenContainer>
        <View
          style={[
            styles.permissionContainer,
            {
              paddingHorizontal: contentHorizontalPadding,
              paddingVertical: sectionVerticalSpacing,
            },
          ]}
        >
          <Text
            testID="camera-permission-text"
            style={[styles.permissionText, { color: theme.text }]}
          >
            Camera permission is required to scan receipts
          </Text>
          <TouchableOpacity
            style={[styles.permissionButton, { backgroundColor: theme.primary }]}
            onPress={requestPermission}
          >
            <Text style={[styles.permissionButtonText, { color: brandColors.white }]}>
              Grant Permission
            </Text>
          </TouchableOpacity>
        </View>
      </ScreenContainer>
    );
  }

  const takePicture = async () => {
    if (cameraRef.current) {
      try {
        const photo = await cameraRef.current.takePictureAsync({
          quality: 0.7,
          base64: true,
        });
        setPhoto(photo.uri);
        if ((photo as any).base64) setPhotoBase64((photo as any).base64 as string);
        let createdDraftId: number | null = null;
        try {
          const createdId = await receiptService.create({
            user_id: userProfile?.uid || 'anon',
            image_uri: photo.uri,
            total_amount: undefined,
            ocr_data: '',
            synced: 0,
          });
          if (createdId && Number(createdId) > 0) {
            createdDraftId = Number(createdId);
            setDraftReceiptId(createdDraftId);
            try {
              emit('receipts-changed', { id: createdId, userId: userProfile?.uid });
            } catch (e) {}
          }
        } catch (e) {}

        await processReceipt({
          photoUri: photo.uri,
          photoBase64: (photo as any).base64 ?? null,
          draftIdArg: createdDraftId,
        });
      } catch (error) {
        Alert.alert('Error', 'Failed to capture image');
      }
    }
  };
  if (photo) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: brandColors.black }}>
        <View style={styles.previewContainer}>
          <Image testID="scan-preview-image" source={{ uri: photo }} style={styles.previewImage} />
          <Modal
            visible={manualModalVisible}
            transparent
            statusBarTranslucent
            animationType="fade"
            presentationStyle="overFullScreen"
            onRequestClose={() => setManualModalVisible(false)}
          >
            <KeyboardAvoidingView
              behavior={Platform.OS === 'ios' ? 'padding' : undefined}
              style={styles.modalAvoider}
            >
              <View style={styles.modalBackdrop}>
                <View style={styles.modalCard}>
                  <Text style={styles.modalTitle}>Manual entry</Text>
                  <Text style={styles.modalSubtitle}>Enter the total amount</Text>
                  <TextInput
                    testID="manual-entry-input"
                    style={styles.modalInput}
                    keyboardType="decimal-pad"
                    value={manualEntryText}
                    onChangeText={setManualEntryText}
                    placeholder="0.00"
                    placeholderTextColor="#7A7A7A"
                  />
                  <View style={styles.modalRow}>
                    <TouchableOpacity
                      style={[styles.modalBtn, styles.modalCancel]}
                      onPress={async () => {
                        // User cancelled manual entry: delete draft and reset state, return to camera
                        try {
                          await discardDraft(draftReceiptId);
                        } catch (e) {}
                        try {
                          resetWorkflowState();
                        } catch (e) {}
                        setManualModalVisible(false);
                        clearPhotoPreview();
                      }}
                    >
                      <Text style={styles.modalCancelText}>Cancel</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      testID="manual-confirm-button"
                      style={[styles.modalBtn, styles.modalConfirm]}
                      onPress={async () => {
                        const cleaned = String(manualEntryText || '')
                          .replace(/[^0-9.,-]/g, '')
                          .replace(/,/g, '.');
                        const parsed = Number(cleaned);
                        if (!Number.isFinite(parsed) || parsed <= 0) {
                          Alert.alert('Invalid amount', 'Enter a valid number');
                          return;
                        }
                        setManualModalVisible(false);
                        const draft = draftReceiptId;
                        await saveAndNavigate(parsed, draft, ocrRaw, photo);
                      }}
                    >
                      <Text style={styles.modalConfirmText}>Confirm</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            </KeyboardAvoidingView>
          </Modal>
          {processing && (
            <View style={styles.processingOverlay} pointerEvents="none">
              <Text style={styles.processingText}>Processing Receipt...</Text>
            </View>
          )}
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: brandColors.black }}>
      <View style={styles.cameraContainer}>
        {isCameraActive && <CameraView style={styles.camera} facing={facing} ref={cameraRef} />}

        <View
          style={[
            styles.cameraControls,
            {
              paddingHorizontal: contentHorizontalPadding,
              bottom: (() => {
                const base = insets.bottom;
                if (isSmallPhone) return base + spacing.xl;
                if (isTablet) return base + spacing.xxl + spacing.xl;
                return base + spacing.xxl + spacing.sm;
              })(),
            },
          ]}
        >
          <TouchableOpacity
            testID="capture-button"
            activeOpacity={0.85}
            onPress={takePicture}
            style={[
              styles.captureButton,
              {
                width: captureButtonSize,
                height: captureButtonSize,
                borderRadius: captureButtonSize / 2,
              },
            ]}
          />
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  permissionContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  permissionText: {
    ...typography.body,
    textAlign: 'center',
    opacity: 0.7,
    marginBottom: spacing.lg,
  },
  permissionButton: {
    paddingHorizontal: spacing.xxl,
    paddingVertical: spacing.md,
    borderRadius: radii.md,
  },
  permissionButtonText: {
    ...typography.button,
  },
  cameraContainer: {
    flex: 1,
    backgroundColor: brandColors.black,
  },
  camera: {
    flex: 1,
  },

  previewContainer: {
    flex: 1,
    backgroundColor: brandColors.black,
  },
  previewImage: {
    flex: 1,
    resizeMode: 'contain',
  },
  processingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: brandColors.black + 'CC',
  },
  processingText: {
    color: brandColors.white,
    ...typography.sectionTitle,
  },
  modalAvoider: {
    flex: 1,
  },
  modalBackdrop: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.75)',
    paddingHorizontal: spacing.lg,
  },
  modalCard: {
    width: '100%',
    maxWidth: 380,
    borderRadius: radii.lg,
    padding: spacing.lg,
    backgroundColor: brandColors.white,
    shadowColor: brandColors.black,
    shadowOffset: { width: 0, height: spacing.xs },
    shadowOpacity: 0.25,
    shadowRadius: spacing.md,
    elevation: 6,
  },
  modalTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.sm,
    textAlign: 'center',
    color: brandColors.black,
  },
  modalSubtitle: {
    ...typography.body,
    marginBottom: spacing.lg,
    textAlign: 'center',
    color: brandColors.black,
  },
  modalInput: {
    backgroundColor: brandColors.gray,
    borderRadius: radii.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    color: brandColors.black,
  },
  modalRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  modalBtn: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radii.md,
    marginLeft: spacing.sm,
  },
  modalCancel: {
    backgroundColor: brandColors.gray,
  },
  modalConfirm: {
    backgroundColor: brandColors.green,
  },
  modalCancelText: {
    color: brandColors.black,
  },
  modalConfirmText: {
    color: brandColors.white,
  },
  cameraControls: {
    position: 'absolute',
    left: 0,
    right: 0,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 20,
  },
  captureButton: {
    backgroundColor: brandColors.green,
    borderWidth: 1,
    borderColor: brandColors.white,
  },
});

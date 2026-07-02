/**
 * useReceiptCapture
 *
 * Manages the photo → OCR → confirm → save workflow for receipts.
 */

import { useCallback, useRef, useState } from 'react';
import { Alert } from 'react-native';
import Constants from 'expo-constants';
import { receiptService } from '@/services/receipts';
import { performOcrWithFallback } from '@/services/ocrService';
import { parseAmountFromOcrText, validateAmount } from '@/services/receiptParser';
import { emit } from '@/services/eventBus';
import { formatCurrencyGBP } from '@/utils/formatters';
import showConfirmationPrompt from '@/components/ConfirmationPrompt';

export type PendingReceiptState = {
  draftId: string | null;
  ocrText: string | null;
  photoUri: string | null;
  amount: number | null;
};

/** Options required by `useReceiptCapture` (navigation and callbacks). */
type UseReceiptCaptureOptions = {
  navigation: any;
  onResetCamera?: () => void;
};

/** Options provided to `processReceipt` (photo, draft id, callbacks). */
type ProcessReceiptOptions = {
  photoUri?: string | null;
  photoBase64?: string | null;
  draftIdArg?: string | null;
  onSuggestion?: (amount: number | null, ocrText: string | null) => void;
  skipOverlay?: boolean;
};

/** Coordinates the photo → OCR → confirmation → save pipeline. */
export const useReceiptCapture = ({ navigation, onResetCamera }: UseReceiptCaptureOptions) => {
  const [processing, setProcessing] = useState(false);
  const [ocrRaw, setOcrRaw] = useState<string | null>(null);
  const [draftReceiptId, setDraftReceiptId] = useState<string | null>(null);
  const [manualModalVisible, setManualModalVisible] = useState(false);
  const [manualEntryText, setManualEntryText] = useState('');
  const pendingRef = useRef<PendingReceiptState>({
    draftId: null,
    ocrText: null,
    photoUri: null,
    amount: null,
  });

  /** Reset transient hook state so the camera flow can restart. */
  const resetWorkflowState = useCallback(() => {
    setProcessing(false);
    setOcrRaw(null);
    setDraftReceiptId(null);
    pendingRef.current = { draftId: null, ocrText: null, photoUri: null, amount: null };
  }, []);

  /** Delete a draft receipt if it should not persist (rescan/cancel). */
  const discardDraft = useCallback(
    async (draftId?: string | null) => {
      const id = draftId ?? draftReceiptId;
      if (!id) return;
      try {
        await receiptService.delete(id);
        try {
          emit('receipts-changed', { id });
        } catch (e) {}
      } catch (e) {}
    },
    [draftReceiptId],
  );

  /** Save receipt (update or create) then navigate to details. */
  const saveAndNavigate = useCallback(
    async (
      amount: number,
      draftId: string | null,
      ocrText: string | null,
      photoUri: string | null,
    ) => {
      try {
        if (draftId) {
          await receiptService.update(draftId, {
            total_amount: amount,
            ocr_raw_text: ocrText || '',
          });
          try {
            emit('receipts-changed', { id: draftId });
          } catch (e) {}
          resetWorkflowState();
          navigation.navigate('ReceiptDetails' as any, {
            receiptId: draftId,
            totalAmount: amount,
            date: new Date().toISOString(),
            image: photoUri ?? undefined,
          });
          onResetCamera?.();
        } else {
          const created = await receiptService.create({
            receipt_image_s3_key: photoUri ?? undefined,
            total_amount: amount,
            ocr_raw_text: ocrText || '',
          });
          if (created && created.id) {
            try {
              emit('receipts-changed', { id: created.id });
            } catch (e) {}
            resetWorkflowState();
            navigation.navigate('ReceiptDetails' as any, {
              receiptId: created.id,
              totalAmount: amount,
              date: new Date().toISOString(),
              image: photoUri ?? undefined,
            });
            onResetCamera?.();
          }
        }
      } catch (e: any) {
        Alert.alert('Save error', e?.message || 'Failed to save receipt');
      }
    },
    [navigation, onResetCamera, resetWorkflowState],
  );

  /** Prompt the user to enter an amount manually (platform modal). */
  const handleManualEntry = useCallback(
    (prefill?: number | null) => {
      const preset = prefill != null ? String(prefill) : '';
      setManualEntryText(preset);
      setManualModalVisible(true);
    },
    [setManualEntryText, setManualModalVisible],
  );

  /** Run OCR on a photo, suggest amount, and show confirmation overlay. */
  const processReceipt = useCallback(
    async ({
      photoUri,
      photoBase64,
      draftIdArg,
      onSuggestion,
      skipOverlay,
    }: ProcessReceiptOptions) => {
      if (!photoUri) return;
      if (!skipOverlay) setProcessing(true);
      try {
        const extras =
          (Constants as any).manifest?.extra || (Constants as any).expoConfig?.extra || {};
        const apiKey = extras?.OCR_SPACE_API_KEY || process.env.OCR_SPACE_API_KEY || '';
        if (!apiKey) {
          if (!skipOverlay) setProcessing(false);
          Alert.alert(
            'Missing API Key',
            'OCR API key not found. Add `OCR_SPACE_API_KEY` to your app config (app.json) or environment configuration.',
          );
          return;
        }

        const result = await performOcrWithFallback(photoUri, photoBase64 || null, apiKey);
        const ocrText = result?.text || '';
        setOcrRaw(ocrText || null);

        if (!ocrText || !ocrText.trim()) {
          if (onSuggestion) onSuggestion(null, ocrText || null);
          const draft = draftIdArg ?? draftReceiptId ?? null;
          pendingRef.current = {
            draftId: draft,
            ocrText: ocrText || null,
            photoUri: photoUri ?? null,
            amount: null,
          };
          if (!skipOverlay) {
            // For empty OCR results we surface the same confirmation prompt
            // interface so callers/tests can inspect the handlers (enter manually,
            // rescan). The confirmation prompt will present options that map to
            // existing handlers in the flow.
            showConfirmationPrompt('No amount', {
              onConfirm: async () => {
                // Do not save when there is no amount — keep behavior consistent
                // by simply closing the overlay and leaving the draft as-is.
                resetWorkflowState();
                onResetCamera?.();
              },
              onEnterManually: () => handleManualEntry(null),
              onRescan: async () => {
                await discardDraft(draft);
                resetWorkflowState();
                onResetCamera?.();
              },
            });
          }
          return;
        }

        const parsed = parseAmountFromOcrText(ocrText);
        const amount = parsed != null && parsed > 0 ? parsed : null;

        // Validate extracted amount for realistic values
        if (amount !== null && !validateAmount(amount)) {
          // Amount is unrealistic (too high, negative, etc.)
          if (onSuggestion) onSuggestion(null, ocrText);
          const draft = draftIdArg ?? draftReceiptId ?? null;
          pendingRef.current = {
            draftId: draft,
            ocrText,
            photoUri: photoUri ?? null,
            amount: null,
          };
          if (!skipOverlay) {
            Alert.alert(
              'Invalid Amount Detected',
              `The detected amount (${formatCurrencyGBP(amount)}) seems unrealistic. Please enter the amount manually.`,
              [
                {
                  text: 'Enter Manually',
                  onPress: () => handleManualEntry(null),
                },
                {
                  text: 'Rescan',
                  onPress: async () => {
                    await discardDraft(draft);
                    resetWorkflowState();
                    onResetCamera?.();
                  },
                },
              ],
            );
          }
          return;
        }

        if (onSuggestion) onSuggestion(amount, ocrText);

        const draft = draftIdArg ?? draftReceiptId ?? null;
        pendingRef.current = { draftId: draft, ocrText, photoUri: photoUri ?? null, amount };
        const displayAmount = amount != null ? formatCurrencyGBP(amount) : 'No amount detected';
        showConfirmationPrompt(displayAmount, {
          onConfirm: async () => {
            await saveAndNavigate(amount ?? 0, draft, ocrText || null, photoUri || null);
          },
          onEnterManually: () => handleManualEntry(amount),
          onRescan: async () => {
            await discardDraft(draft);
            resetWorkflowState();
            onResetCamera?.();
          },
        });
      } catch (err: any) {
        if (!skipOverlay)
          Alert.alert(
            'OCR Error',
            err?.message ||
              'Could not process the receipt. Please try again or check your network.',
          );
        if (onSuggestion) onSuggestion(null, null);
      } finally {
        if (!skipOverlay) setProcessing(false);
      }
    },
    [
      discardDraft,
      draftReceiptId,
      handleManualEntry,
      onResetCamera,
      resetWorkflowState,
      saveAndNavigate,
    ],
  );

  return {
    state: {
      processing,
      ocrRaw,
      draftReceiptId,
      manualModalVisible,
      manualEntryText,
    },
    actions: {
      setDraftReceiptId,
      setManualEntryText,
      setManualModalVisible,
      setProcessing,
      setOcrRaw,
      resetWorkflowState,
      discardDraft,
      saveAndNavigate,
      processReceipt,
    },
    pendingRef,
  };
};

export type UseReceiptCaptureReturn = ReturnType<typeof useReceiptCapture>;

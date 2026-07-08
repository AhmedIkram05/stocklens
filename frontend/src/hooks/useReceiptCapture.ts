/**
 * useReceiptCapture
 *
 * Manages the photo → scan → confirm → navigate workflow for receipts.
 * Uses the backend cascade OCR endpoint — no client-side OCR or drafts.
 */

import { useCallback, useRef, useState } from 'react';
import { Alert } from 'react-native';
import { receiptService, type ScanResponse } from '@/services/receipts';
import { emit } from '@/services/eventBus';
import { formatCurrencyGBP } from '@/utils/formatters';
import showConfirmationPrompt from '@/components/ConfirmationPrompt';

export type PendingReceiptState = {
  scanResponse: ScanResponse | null;
  photoUri: string | null;
};

/** Options required by useReceiptCapture (navigation and callbacks). */
type UseReceiptCaptureOptions = {
  navigation: any;
  onResetCamera?: () => void;
};

/** Options provided to processReceipt. */
type ProcessReceiptOptions = {
  photoUri?: string | null;
  onSuggestion?: (amount: number | null, ocrText: string | null) => void;
  skipOverlay?: boolean;
};

/** Coordinates the photo → scan → confirmation → navigate pipeline. */
export const useReceiptCapture = ({ navigation, onResetCamera }: UseReceiptCaptureOptions) => {
  const [processing, setProcessing] = useState(false);
  const [ocrRaw, setOcrRaw] = useState<string | null>(null);
  const [manualModalVisible, setManualModalVisible] = useState(false);
  const [manualEntryText, setManualEntryText] = useState('');
  const pendingRef = useRef<PendingReceiptState>({
    scanResponse: null,
    photoUri: null,
  });

  /** Reset transient hook state so the camera flow can restart. */
  const resetWorkflowState = useCallback(() => {
    setProcessing(false);
    setOcrRaw(null);
    pendingRef.current = { scanResponse: null, photoUri: null };
  }, []);

  /** Delete a receipt by ID (used when cancelling manual entry after a scan). */
  const discardDraft = useCallback(async (id?: string | null) => {
    if (!id) return;
    try {
      await receiptService.delete(id);
      try {
        emit('receipts-changed', { id });
      } catch (e) {}
    } catch (e) {}
  }, []);

  /** Create a receipt from manual entry and navigate to details. */
  const saveAndNavigate = useCallback(
    async (amount: number, ocrText: string | null, photoUri: string | null) => {
      try {
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

  /** Scan a receipt photo via the backend cascade and show a confirmation prompt. */
  const processReceipt = useCallback(
    async ({ photoUri, onSuggestion, skipOverlay }: ProcessReceiptOptions) => {
      if (!photoUri) return;
      if (!skipOverlay) setProcessing(true);
      try {
        const result = await receiptService.scan(photoUri);
        const amount = result.extraction?.total ?? null;
        const rawText = result.raw_text ?? null;

        setOcrRaw(rawText);

        if (onSuggestion) onSuggestion(amount, rawText);

        pendingRef.current = {
          scanResponse: result,
          photoUri: photoUri ?? null,
        };

        const displayAmount = amount != null ? formatCurrencyGBP(amount) : 'No amount detected';
        showConfirmationPrompt(displayAmount, {
          onConfirm: async () => {
            emit('receipts-changed', { id: result.id });
            resetWorkflowState();
            navigation.navigate('ReceiptDetails' as any, {
              receiptId: result.id,
              totalAmount: amount ?? 0,
              date: result.extraction?.date ?? new Date().toISOString(),
              image: photoUri ?? undefined,
              source: result.source,
              confidence: result.confidence,
              processingTimeMs: result.processing_time_ms,
            });
            onResetCamera?.();
          },
          onEnterManually: () => handleManualEntry(amount),
          onRescan: async () => {
            resetWorkflowState();
            onResetCamera?.();
          },
        });
      } catch (err: any) {
        if (!skipOverlay) {
          const msg = err?.message?.toLowerCase() ?? '';
          // Backend 422: "Could not extract the total amount…" → manual entry
          // Backend 422: "Could not extract text…" → prompt retake
          // Legacy strings kept for backward compat
          if (
            msg.includes('total amount') ||
            msg.includes('no total amount') ||
            msg.includes('no amount')
          ) {
            Alert.alert(
              'Could not read receipt',
              'No amount could be detected. Please enter manually.',
            );
            if (onSuggestion) onSuggestion(null, null);
            handleManualEntry(null);
          } else if (
            msg.includes('extract text') ||
            msg.includes('no receipt text') ||
            msg.includes('better lighting')
          ) {
            Alert.alert(
              'Could not read receipt',
              'No text was detected. Please retake the photo with better lighting.',
            );
          } else {
            Alert.alert(
              'Scan Error',
              err?.message || 'Could not process the receipt. Please try again.',
            );
          }
        }
        if (onSuggestion) onSuggestion(null, null);
      } finally {
        if (!skipOverlay) setProcessing(false);
      }
    },
    [handleManualEntry, onResetCamera, resetWorkflowState],
  );

  return {
    state: {
      processing,
      ocrRaw,
      manualModalVisible,
      manualEntryText,
    },
    actions: {
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

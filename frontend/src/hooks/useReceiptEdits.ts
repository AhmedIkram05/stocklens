/**
 * useReceiptEdits
 *
 * Modal state and submit/validation logic for the four editable receipt fields
 * (category, merchant, total amount, transaction date). Each submit validates,
 * persists via the receipt service, updates the local receipt optimistically,
 * and emits `receipts-changed` so other screens refresh.
 */

import { useState } from 'react';
import { Alert } from 'react-native';
import { receiptService } from '../services/receipts';
import { emit } from '../services/eventBus';

type Args = {
  receiptId?: string;
  setReceipt: React.Dispatch<React.SetStateAction<any>>;
};

export default function useReceiptEdits({ receiptId, setReceipt }: Args) {
  const [categoryModalVisible, setCategoryModalVisible] = useState(false);
  const [categorySaving, setCategorySaving] = useState(false);

  const [merchantModalVisible, setMerchantModalVisible] = useState(false);
  const [merchantEditValue, setMerchantEditValue] = useState('');
  const [merchantSaving, setMerchantSaving] = useState(false);

  const [amountModalVisible, setAmountModalVisible] = useState(false);
  const [amountEditValue, setAmountEditValue] = useState('');
  const [amountSaving, setAmountSaving] = useState(false);

  const [dateModalVisible, setDateModalVisible] = useState(false);
  const [dateEditValue, setDateEditValue] = useState('');
  const [dateSaving, setDateSaving] = useState(false);

  function notifyChanged() {
    try {
      emit('receipts-changed', { id: receiptId, action: 'updated' });
    } catch (e) {}
  }

  async function handleSelectCategory(catId: string) {
    if (!receiptId) return;
    setCategorySaving(true);
    try {
      await receiptService.update(receiptId, { category_id: catId });
      setReceipt((prev: any) => (prev ? { ...prev, category_id: catId } : prev));
      notifyChanged();
      setCategoryModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update category');
    } finally {
      setCategorySaving(false);
    }
  }

  async function handleUpdateMerchant() {
    if (!receiptId || !merchantEditValue.trim()) return;
    setMerchantSaving(true);
    try {
      await receiptService.update(receiptId, { merchant_name: merchantEditValue.trim() });
      setReceipt((prev: any) =>
        prev ? { ...prev, merchant_name: merchantEditValue.trim() } : prev,
      );
      notifyChanged();
      setMerchantModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update merchant');
    } finally {
      setMerchantSaving(false);
    }
  }

  async function handleUpdateAmount() {
    if (!receiptId || !amountEditValue.trim()) return;
    const parsed = parseFloat(amountEditValue.trim());
    if (isNaN(parsed) || parsed <= 0) {
      Alert.alert('Invalid amount', 'Enter a valid positive number');
      return;
    }
    setAmountSaving(true);
    try {
      await receiptService.update(receiptId, { total_amount: parsed });
      setReceipt((prev: any) => (prev ? { ...prev, total_amount: parsed } : prev));
      notifyChanged();
      setAmountModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update amount');
    } finally {
      setAmountSaving(false);
    }
  }

  async function handleUpdateDate() {
    if (!receiptId || !dateEditValue.trim()) return;
    // Basic date validation: must be YYYY-MM-DD
    const trimmed = dateEditValue.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      Alert.alert('Invalid date', 'Enter date as YYYY-MM-DD');
      return;
    }
    setDateSaving(true);
    try {
      await receiptService.update(receiptId, { transaction_date: trimmed });
      setReceipt((prev: any) => (prev ? { ...prev, transaction_date: trimmed } : prev));
      notifyChanged();
      setDateModalVisible(false);
    } catch {
      Alert.alert('Error', 'Could not update date');
    } finally {
      setDateSaving(false);
    }
  }

  return {
    categoryModalVisible,
    setCategoryModalVisible,
    categorySaving,
    merchantModalVisible,
    setMerchantModalVisible,
    merchantEditValue,
    setMerchantEditValue,
    merchantSaving,
    amountModalVisible,
    setAmountModalVisible,
    amountEditValue,
    setAmountEditValue,
    amountSaving,
    dateModalVisible,
    setDateModalVisible,
    dateEditValue,
    setDateEditValue,
    dateSaving,
    handleSelectCategory,
    handleUpdateMerchant,
    handleUpdateAmount,
    handleUpdateDate,
  } as const;
}

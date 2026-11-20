/**
 * ConfirmationPrompt
 *
 * Show a confirmation alert offering Confirm / Enter manually / Rescan options.
 */

import { Alert } from 'react-native';

type Handlers = {
  /** Callback triggered when user confirms the detected amount */
  onConfirm: () => void | Promise<void>;
  /** Callback triggered when user chooses to manually enter the amount */
  onEnterManually: () => void | Promise<void>;
  /** Callback triggered when user wants to rescan the receipt */
  onRescan: () => void | Promise<void>;
};

/** Show a confirmation dialog for the detected amount. */
export function showConfirmationPrompt(
  displayAmount: string,
  handlers: Handlers,
  merchant?: string | null,
) {
  const parsedAmount =
    typeof displayAmount === 'string' ? Number(displayAmount.replace(/[^0-9.-]/g, '')) : Number.NaN;
  const hasDetectedAmount = Number.isFinite(parsedAmount) && parsedAmount > 0;

  const buttons: any[] = [];
  if (hasDetectedAmount) {
    buttons.push({
      text: 'Confirm',
      onPress: () => {
        try {
          handlers.onConfirm();
        } catch (e) {}
      },
    });
  }
  buttons.push(
    {
      text: 'Enter manually',
      onPress: () => {
        try {
          handlers.onEnterManually();
        } catch (e) {}
      },
    },
    {
      text: 'Rescan',
      onPress: () => {
        try {
          handlers.onRescan();
        } catch (e) {}
      },
    },
  );

  const merchantLine = merchant && merchant.trim() ? `\nMerchant: ${merchant}` : '';
  const message = hasDetectedAmount
    ? `We detected ${displayAmount} from this receipt.${merchantLine}`
    : 'No amount detected. Enter the total manually or rescan the receipt.';

  Alert.alert('Confirm scanned total', message, buttons, { cancelable: true });
}

export default showConfirmationPrompt;

/**
 * useDepositFlow
 *
 * Deposit-into-portfolio flow for a receipt: opens the portfolio picker, loads
 * the portfolios, and records a cash flow sourced from the receipt. (The trade
 * execution flow itself lives in `screens/portfolio/TradeScreen`.)
 */

import { useState } from 'react';
import { Alert } from 'react-native';
import { portfolioService, Portfolio } from '../services/portfolios';
import { formatCurrencyRounded } from '../utils/formatters';

type Args = {
  totalAmount: number;
  receiptId?: string;
  formattedAmount: string;
};

export default function useDepositFlow({ totalAmount, receiptId, formattedAmount }: Args) {
  const [depositModalVisible, setDepositModalVisible] = useState(false);
  const [portfolioList, setPortfolioList] = useState<Portfolio[]>([]);
  const [portfoliosLoading, setPortfoliosLoading] = useState(false);
  const [depositingPid, setDepositingPid] = useState<string | null>(null);

  async function handleOpenDeposit() {
    setDepositModalVisible(true);
    setPortfoliosLoading(true);
    try {
      setPortfolioList(await portfolioService.listPortfolios());
    } catch {
      Alert.alert('Error', 'Could not load portfolios');
      setDepositModalVisible(false);
    } finally {
      setPortfoliosLoading(false);
    }
  }

  async function handleSelectPortfolio(pid: string) {
    setDepositingPid(pid);
    try {
      await portfolioService.createCashFlow(pid, {
        amount: totalAmount,
        source: 'receipt',
        source_id: receiptId ?? undefined,
        notes: `Deposit from ${formattedAmount} receipt`,
      });
      Alert.alert('Deposited', `${formatCurrencyRounded(totalAmount)} deposited into portfolio`);
      setDepositModalVisible(false);
    } catch {
      Alert.alert('Error', 'Failed to deposit. Please try again.');
    } finally {
      setDepositingPid(null);
    }
  }

  return {
    depositModalVisible,
    setDepositModalVisible,
    portfolioList,
    portfoliosLoading,
    depositingPid,
    handleOpenDeposit,
    handleSelectPortfolio,
  } as const;
}

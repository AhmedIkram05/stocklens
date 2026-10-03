/**
 * DepositModal
 *
 * Portfolio picker modal for depositing the receipt amount. Presentational —
 * loading state, portfolio data and the select handler are owned by the caller.
 */

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { radii, spacing, typography } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';
import type { Portfolio } from '../services/portfolios';

type Props = {
  /** Whether the modal is shown */
  visible: boolean;
  /** Formatted receipt amount shown in the title (e.g. "£12.50") */
  formattedAmount: string;
  /** Portfolios available to deposit into */
  portfolios: Portfolio[];
  /** When true, shows a spinner instead of the list */
  loading: boolean;
  /** Id of the portfolio currently being deposited into, if any */
  depositingPid: string | null;
  /** Called with the chosen portfolio id */
  onSelectPortfolio: (portfolioId: string) => void;
  /** Called when Cancel or the hardware back button closes the modal */
  onClose: () => void;
};

export default function DepositModal({
  visible,
  formattedAmount,
  portfolios,
  loading,
  depositingPid,
  onSelectPortfolio,
  onClose,
}: Props) {
  const { theme } = useTheme();

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
          <Text style={[styles.modalTitle, { color: theme.text }]}>
            Deposit {formattedAmount} into…
          </Text>

          {loading ? (
            <View style={styles.modalLoading}>
              <ActivityIndicator size="large" color={theme.primary} />
            </View>
          ) : portfolios.length === 0 ? (
            <View style={styles.modalLoading}>
              <Text style={[{ color: theme.textSecondary }]}>
                No portfolios yet. Create one first.
              </Text>
            </View>
          ) : (
            <FlatList
              data={portfolios}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => {
                const isProcessing = depositingPid === item.id;
                return (
                  <TouchableOpacity
                    style={[styles.modalPortfolioItem, { backgroundColor: theme.background }]}
                    onPress={() => onSelectPortfolio(item.id)}
                    disabled={depositingPid !== null}
                    activeOpacity={0.7}
                  >
                    <Text style={[styles.modalPortfolioName, { color: theme.text }]}>
                      {item.name}
                    </Text>
                    {isProcessing ? (
                      <ActivityIndicator size="small" color={theme.primary} />
                    ) : (
                      <Ionicons name="chevron-forward" size={18} color={theme.textSecondary} />
                    )}
                  </TouchableOpacity>
                );
              }}
            />
          )}

          <TouchableOpacity style={styles.modalCloseBtn} onPress={onClose}>
            <Text style={[styles.modalCloseText, { color: theme.textSecondary }]}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.6)',
    paddingHorizontal: spacing.lg,
  },
  modalCard: {
    borderRadius: radii.lg,
    padding: spacing.lg,
    maxHeight: '60%',
  },
  modalTitle: {
    ...typography.sectionTitle,
    marginBottom: spacing.lg,
    textAlign: 'center',
  },
  modalLoading: {
    paddingVertical: spacing.xl,
    alignItems: 'center',
  },
  modalPortfolioItem: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radii.md,
    marginBottom: spacing.sm,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  modalPortfolioName: {
    ...typography.bodyStrong,
  },
  modalCloseBtn: {
    alignSelf: 'center',
    marginTop: spacing.lg,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xl,
  },
  modalCloseText: {
    ...typography.button,
  },
});

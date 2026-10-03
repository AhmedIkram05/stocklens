/**
 * CategoryPickerModal
 *
 * Modal list for picking a receipt category. Presentational — the caller owns
 * the category list, saving state and update handler.
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
import type { Category } from '../services/categories';

type Props = {
  /** Whether the modal is shown */
  visible: boolean;
  /** Available categories to choose from */
  categories: Category[];
  /** Currently assigned category id (shows a checkmark) */
  selectedCategoryId: string | null;
  /** When true, shows a spinner instead of the list */
  saving: boolean;
  /** Called with the chosen category id */
  onSelectCategory: (categoryId: string) => void;
  /** Called when Cancel or the hardware back button closes the modal */
  onClose: () => void;
};

export default function CategoryPickerModal({
  visible,
  categories,
  selectedCategoryId,
  saving,
  onSelectCategory,
  onClose,
}: Props) {
  const { theme } = useTheme();

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
          <Text style={[styles.modalTitle, { color: theme.text }]}>Select category</Text>

          {saving ? (
            <View style={styles.modalLoading}>
              <ActivityIndicator size="large" color={theme.primary} />
            </View>
          ) : (
            <FlatList
              data={categories}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={[styles.modalPortfolioItem, { backgroundColor: theme.background }]}
                  onPress={() => onSelectCategory(item.id)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.modalPortfolioName, { color: theme.text }]}>
                    {item.name}
                  </Text>
                  {item.id === selectedCategoryId && (
                    <Ionicons name="checkmark" size={18} color={theme.primary} />
                  )}
                </TouchableOpacity>
              )}
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

/**
 * EditValueModal
 *
 * Generic single-field edit modal (merchant name, total amount, transaction date).
 * Purely presentational — value, saving state and handlers are owned by the caller.
 */

import React from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import type { TextInputProps } from 'react-native';
import { radii, spacing, typography } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

type Props = {
  /** Whether the modal is shown */
  visible: boolean;
  /** Modal heading (e.g. "Edit merchant name") */
  title: string;
  /** Current input value */
  value: string;
  /** Called on every keystroke */
  onChangeText: (value: string) => void;
  /** Called when Save is pressed */
  onSave: () => void;
  /** Called when Cancel or the hardware back button closes the modal */
  onClose: () => void;
  /** When true, shows a spinner instead of the input/save controls */
  saving: boolean;
  /** Input placeholder (e.g. "0.00") */
  placeholder: string;
  /** Optional keyboard type (e.g. "decimal-pad") */
  keyboardType?: TextInputProps['keyboardType'];
};

export default function EditValueModal({
  visible,
  title,
  value,
  onChangeText,
  onSave,
  onClose,
  saving,
  placeholder,
  keyboardType,
}: Props) {
  const { theme } = useTheme();

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalCard, { backgroundColor: theme.surface }]}>
          <Text style={[styles.modalTitle, { color: theme.text }]}>{title}</Text>

          {saving ? (
            <View style={styles.modalLoading}>
              <ActivityIndicator size="large" color={theme.primary} />
            </View>
          ) : (
            <>
              <TextInput
                style={[
                  styles.modalInput,
                  {
                    backgroundColor: theme.background,
                    color: theme.text,
                    borderColor: theme.textSecondary + '40',
                  },
                ]}
                value={value}
                onChangeText={onChangeText}
                placeholder={placeholder}
                placeholderTextColor={theme.textSecondary}
                keyboardType={keyboardType}
                autoFocus
              />
              <TouchableOpacity
                style={[styles.modalSaveBtn, { backgroundColor: theme.primary }]}
                onPress={onSave}
                activeOpacity={0.8}
              >
                <Text style={{ color: '#fff', ...typography.button, textAlign: 'center' }}>
                  Save
                </Text>
              </TouchableOpacity>
            </>
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
  modalInput: {
    borderWidth: 1,
    borderRadius: radii.md,
    padding: spacing.md,
    fontSize: 16,
    marginBottom: spacing.md,
  },
  modalSaveBtn: {
    borderRadius: radii.md,
    paddingVertical: spacing.md + 2,
    marginBottom: spacing.sm,
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

import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, CompositeNavigationProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { StatusBar } from 'expo-status-bar';
import { useTheme } from '../../contexts/ThemeContext';
import { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService } from '../../services/portfolios';

type CreatePortfolioNavProp = CompositeNavigationProp<
  StackNavigationProp<PortfolioStackParamList, 'CreatePortfolio'>,
  StackNavigationProp<PortfolioStackParamList>
>;

export default function CreatePortfolioScreen() {
  const navigation = useNavigation<CreatePortfolioNavProp>();
  const { theme } = useTheme();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [depositAmount, setDepositAmount] = useState('');
  const [source, setSource] = useState<'manual' | 'receipt'>('manual');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameValid = name.trim().length > 0;

  const handleCreate = async () => {
    if (!nameValid || loading) return;

    setLoading(true);
    setError(null);

    try {
      const portfolio = await portfolioService.createPortfolio({
        name: name.trim(),
        description: description.trim() || undefined,
      });

      const deposit = parseFloat(depositAmount.replace(/,/g, ''));
      if (depositAmount.trim().length > 0 && !isNaN(deposit) && deposit > 0) {
        await portfolioService.createCashFlow(portfolio.id, {
          amount: deposit,
          source,
          notes: 'Initial deposit',
        });
      }

      navigation.goBack();
    } catch (e) {
      setError('Failed to create portfolio. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <StatusBar style={theme.background === '#000000' ? 'light' : 'dark'} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} disabled={loading}>
            <Text style={[styles.headerButton, { color: theme.primary }]}>Cancel</Text>
          </TouchableOpacity>
          <Text style={[styles.title, { color: theme.text }]}>Create Portfolio</Text>
          <View style={styles.headerButton} />
        </View>

        <View style={styles.form}>
          <Text style={[styles.label, { color: theme.text }]}>Name</Text>
          <TextInput
            style={[
              styles.input,
              {
                backgroundColor: theme.surface,
                borderColor: theme.border,
                color: theme.text,
              },
            ]}
            placeholder="My Portfolio"
            placeholderTextColor={theme.textSecondary}
            value={name}
            onChangeText={setName}
            autoCapitalize="words"
            autoCorrect={false}
            editable={!loading}
          />

          <Text style={[styles.label, { color: theme.text, marginTop: 20 }]}>
            Description (optional)
          </Text>
          <TextInput
            style={[
              styles.input,
              {
                backgroundColor: theme.surface,
                borderColor: theme.border,
                color: theme.text,
              },
            ]}
            placeholder="What's this portfolio for?"
            placeholderTextColor={theme.textSecondary}
            value={description}
            onChangeText={setDescription}
            autoCapitalize="sentences"
            autoCorrect
            editable={!loading}
          />

          <Text style={[styles.label, { color: theme.text, marginTop: 20 }]}>
            Initial Deposit (optional)
          </Text>
          <TextInput
            style={[
              styles.input,
              {
                backgroundColor: theme.surface,
                borderColor: theme.border,
                color: theme.text,
              },
            ]}
            placeholder="0.00"
            placeholderTextColor={theme.textSecondary}
            value={depositAmount}
            onChangeText={setDepositAmount}
            keyboardType="decimal-pad"
            editable={!loading}
          />

          {depositAmount.trim().length > 0 && (
            <>
              <Text style={[styles.label, { color: theme.text, marginTop: 20 }]}>
                Deposit Source
              </Text>
              <View style={styles.sourceRow}>
                <TouchableOpacity
                  style={[
                    styles.sourceButton,
                    {
                      backgroundColor: source === 'manual' ? theme.primary : theme.surface,
                      borderColor: source === 'manual' ? theme.primary : theme.border,
                    },
                  ]}
                  onPress={() => setSource('manual')}
                  disabled={loading}
                >
                  <Text
                    style={[
                      styles.sourceButtonText,
                      {
                        color: source === 'manual' ? '#ffffff' : theme.text,
                      },
                    ]}
                  >
                    Manual
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.sourceButton,
                    {
                      backgroundColor: source === 'receipt' ? theme.primary : theme.surface,
                      borderColor: source === 'receipt' ? theme.primary : theme.border,
                    },
                  ]}
                  onPress={() => setSource('receipt')}
                  disabled={loading}
                >
                  <Text
                    style={[
                      styles.sourceButtonText,
                      {
                        color: source === 'receipt' ? '#ffffff' : theme.text,
                      },
                    ]}
                  >
                    Receipt
                  </Text>
                </TouchableOpacity>
              </View>
            </>
          )}

          {error && <Text style={[styles.errorText, { color: theme.error }]}>{error}</Text>}

          <TouchableOpacity
            style={[
              styles.createButton,
              {
                backgroundColor: nameValid ? theme.primary : theme.border,
              },
            ]}
            onPress={handleCreate}
            disabled={!nameValid || loading}
          >
            {loading ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.createButtonText}>Create</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  headerButton: {
    width: 60,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
  },
  form: {
    flex: 1,
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  sourceRow: {
    flexDirection: 'row',
    gap: 12,
  },
  sourceButton: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
  },
  sourceButtonText: {
    fontSize: 14,
    fontWeight: '600',
  },
  errorText: {
    fontSize: 14,
    marginTop: 12,
    textAlign: 'center',
  },
  createButton: {
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 24,
  },
  createButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { StatusBar } from 'expo-status-bar';

import { useTheme, brandColors } from '../../contexts/ThemeContext';
import BackButton from '../../components/BackButton';
import { PortfolioStackParamList } from '../../navigation/AppNavigator';
import { portfolioService, Holding } from '../../services/portfolios';
import { marketService, QuoteData } from '../../services/market';
import { ApiError } from '../../services/api';
import { radii, spacing, typography } from '../../styles/theme';

type TradeRouteProp = RouteProp<PortfolioStackParamList, 'Trade'>;
type TradeNavigationProp = StackNavigationProp<PortfolioStackParamList, 'Trade'>;

export default function TradeScreen() {
  const navigation = useNavigation<TradeNavigationProp>();
  const route = useRoute<TradeRouteProp>();
  const { portfolioId, mode } = route.params;
  const { theme } = useTheme();

  const [ticker, setTicker] = useState('');
  const [sharesText, setSharesText] = useState('');
  const [localMode, setLocalMode] = useState<'buy' | 'sell'>(mode);
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);
  const [holdingsError, setHoldingsError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [freeCash, setFreeCash] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const shares = parseFloat(sharesText) || 0;
  const total = quote && shares > 0 ? shares * quote.price : 0;

  const loadHoldings = useCallback(async () => {
    if (localMode !== 'sell') return;
    setHoldingsLoading(true);
    setHoldingsError(null);
    try {
      const data = await portfolioService.listHoldings(portfolioId);
      setHoldings(data);
    } catch {
      setHoldingsError('Failed to load holdings. Check your connection.');
    } finally {
      setHoldingsLoading(false);
    }
  }, [localMode, portfolioId]);

  const loadFreeCash = useCallback(async () => {
    try {
      const p = await portfolioService.getPerformance(portfolioId);
      setFreeCash(p.free_cash_balance);
    } catch {
      setFreeCash(null);
    }
  }, [portfolioId]);

  useEffect(() => {
    loadHoldings();
  }, [loadHoldings]);

  useEffect(() => {
    loadFreeCash();
  }, [loadFreeCash]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.allSettled([loadHoldings(), loadFreeCash()]);
    setRefreshing(false);
  }, [loadHoldings, loadFreeCash]);

  const handleFetchQuote = useCallback(async () => {
    const trimmed = ticker.trim().toUpperCase();
    if (!trimmed) return;
    setQuoteLoading(true);
    setQuoteError(null);
    setQuote(null);
    try {
      const data = await marketService.getQuote(trimmed);
      setQuote(data);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Could not fetch quote';
      setQuoteError(message);
    } finally {
      setQuoteLoading(false);
    }
  }, [ticker]);

  const getValidationError = (): string | null => {
    if (!ticker.trim()) return null;
    if (shares <= 0) return 'Shares must be greater than 0';
    if (localMode === 'buy' && freeCash !== null && total > freeCash) {
      return `Insufficient funds: $${total.toFixed(2)} exceeds available $${freeCash.toFixed(2)}`;
    }
    if (localMode === 'sell') {
      if (holdingsLoading) return null; // ponytail: skip validation while loading; prevents flash-before-fetch
      if (holdingsError) return 'Unable to verify holdings. Try again.';
      const holding = holdings.find((h) => h.ticker.toUpperCase() === ticker.trim().toUpperCase());
      if (!holding) return `You don't own any shares of ${ticker.trim().toUpperCase()}`;
      if (shares > holding.shares) {
        return `You only own ${holding.shares} shares of ${ticker.trim().toUpperCase()}`;
      }
    }
    return null;
  };

  const canConfirm =
    ticker.trim().length > 0 &&
    shares > 0 &&
    quote !== null &&
    !quoteLoading &&
    !holdingsLoading &&
    !getValidationError();

  const validationError = getValidationError();

  const handleConfirm = async () => {
    if (!canConfirm || !quote) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await portfolioService.createTransaction(portfolioId, {
        ticker: ticker.trim().toUpperCase(),
        shares,
        price_per_share: quote.price,
        type: localMode === 'buy' ? 'BUY' : 'SELL',
      });
      navigation.goBack();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Transaction failed';
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const isBuy = localMode === 'buy';
  const actionColor = isBuy ? brandColors.green : brandColors.red;

  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: theme.background }]} edges={['top']}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={theme.primary}
              colors={[theme.primary]}
            />
          }
        >
          <BackButton variant="text" label="Cancel" />
          <Text style={[styles.header, { color: theme.text }]}>{isBuy ? 'Buy' : 'Sell'}</Text>

          <View style={styles.modeToggle}>
            <TouchableOpacity
              style={[
                styles.modeButton,
                styles.modeButtonLeft,
                isBuy ? { backgroundColor: brandColors.green } : { backgroundColor: theme.surface },
              ]}
              onPress={() => setLocalMode('buy')}
              activeOpacity={0.7}
            >
              <Text style={[styles.modeButtonText, { color: isBuy ? '#fff' : theme.text }]}>
                Buy
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.modeButton,
                styles.modeButtonRight,
                !isBuy ? { backgroundColor: brandColors.red } : { backgroundColor: theme.surface },
              ]}
              onPress={() => setLocalMode('sell')}
              activeOpacity={0.7}
            >
              <Text style={[styles.modeButtonText, { color: !isBuy ? '#fff' : theme.text }]}>
                Sell
              </Text>
            </TouchableOpacity>
          </View>

          <View style={styles.inputGroup}>
            <Text style={[styles.label, { color: theme.textSecondary }]}>Ticker</Text>
            <TextInput
              style={[
                styles.input,
                { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border },
              ]}
              placeholder="AAPL"
              placeholderTextColor={theme.textSecondary}
              value={ticker}
              onChangeText={(t) => setTicker(t.toUpperCase())}
              onBlur={handleFetchQuote}
              autoCapitalize="characters"
              autoCorrect={false}
              returnKeyType="done"
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={[styles.label, { color: theme.textSecondary }]}>Shares</Text>
            <TextInput
              style={[
                styles.input,
                { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border },
              ]}
              placeholder="0"
              placeholderTextColor={theme.textSecondary}
              value={sharesText}
              onChangeText={setSharesText}
              keyboardType="decimal-pad"
              returnKeyType="done"
            />
          </View>

          {quoteLoading && (
            <View style={styles.quoteRow}>
              <ActivityIndicator size="small" color={theme.primary} />
              <Text style={[styles.quoteLoadingText, { color: theme.textSecondary }]}>
                Fetching quote...
              </Text>
            </View>
          )}

          {quoteError && (
            <Text style={[styles.errorText, { color: theme.error }]}>{quoteError}</Text>
          )}

          {quote && !quoteLoading && (
            <View style={[styles.previewRow, { backgroundColor: theme.surface }]}>
              <Text style={[styles.previewText, { color: theme.text }]}>
                {quote.ticker} × {sharesText || '0'} @ ${quote.price.toFixed(2)} ={' '}
                <Text style={{ fontWeight: '700' }}>${total.toFixed(2)}</Text>
              </Text>
            </View>
          )}

          {localMode === 'sell' && holdingsLoading && (
            <View style={styles.quoteRow}>
              <ActivityIndicator size="small" color={theme.primary} />
              <Text style={[styles.quoteLoadingText, { color: theme.textSecondary }]}>
                Loading holdings…
              </Text>
            </View>
          )}

          {holdingsError && (
            <Text style={[styles.errorText, { color: theme.error }]}>{holdingsError}</Text>
          )}

          {validationError && (
            <Text style={[styles.errorText, { color: theme.error }]}>{validationError}</Text>
          )}

          {submitError && (
            <Text style={[styles.errorText, { color: theme.error }]}>{submitError}</Text>
          )}

          <TouchableOpacity
            style={[
              styles.confirmButton,
              { backgroundColor: canConfirm ? actionColor : theme.border },
            ]}
            disabled={!canConfirm || submitting}
            onPress={handleConfirm}
            activeOpacity={0.8}
          >
            {submitting ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.confirmButtonText}>
                {isBuy ? 'Buy' : ' Sell'} ${total.toFixed(2)}
              </Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  scroll: {
    padding: spacing.lg,
    paddingTop: spacing.xl,
  },
  header: {
    ...typography.pageTitle,
    marginBottom: spacing.xl,
  },
  modeToggle: {
    flexDirection: 'row',
    marginBottom: spacing.xl,
  },
  modeButton: {
    flex: 1,
    paddingVertical: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modeButtonLeft: {
    borderTopLeftRadius: radii.md,
    borderBottomLeftRadius: radii.md,
  },
  modeButtonRight: {
    borderTopRightRadius: radii.md,
    borderBottomRightRadius: radii.md,
  },
  modeButtonText: {
    ...typography.button,
  },
  inputGroup: {
    marginBottom: spacing.lg,
  },
  label: {
    ...typography.captionStrong,
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  input: {
    ...typography.body,
    height: 48,
    borderWidth: 1,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
  },
  quoteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.md,
  },
  quoteLoadingText: {
    ...typography.caption,
    marginLeft: spacing.sm,
  },
  previewRow: {
    padding: spacing.lg,
    borderRadius: radii.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  previewText: {
    ...typography.body,
  },
  errorText: {
    ...typography.caption,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  confirmButton: {
    height: 52,
    borderRadius: radii.md,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: spacing.md,
  },
  confirmButtonText: {
    color: '#fff',
    ...typography.button,
  },
});

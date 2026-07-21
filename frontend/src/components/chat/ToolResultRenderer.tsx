/**
 * ToolResultRenderer
 *
 * Registry of 16 specialised renderers for agent tool results.
 * Each renderer receives the parsed JSON result and returns JSX.
 * Fallback: monospace JSON dump for unknown tools or errors.
 *
 * All renderers are pure functions — no state, no side effects.
 */

import React from 'react';
import { Platform, View, Text, StyleSheet, ScrollView } from 'react-native';
import { useTheme } from '../../contexts/ThemeContext';
import { spacing, radii, typography } from '../../styles/theme';

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatCurrency(value: number | null | undefined, suffix = 'GBP'): string {
  if (value == null) return '—';
  return `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${suffix}`;
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toLocaleString();
}

function formatLargeNumber(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return value.toLocaleString();
}

// ── Shared sub-components ───────────────────────────────────────────────────

function KeyValueRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: 'positive' | 'negative' | 'neutral';
}) {
  const { theme } = useTheme();
  const color =
    highlight === 'positive' ? '#10b981' : highlight === 'negative' ? '#FF3B30' : theme.text;

  return (
    <View style={styles.kvRow}>
      <Text style={[styles.kvLabel, { color: theme.textSecondary }]}>{label}</Text>
      <Text style={[styles.kvValue, { color }]}>{value}</Text>
    </View>
  );
}

// ── 1. Key-value card (get_portfolio_summary) ───────────────────────────────

function PortfolioSummaryRenderer({ data }: { data: any }) {
  const pl = data.unrealised_pl_gbp ?? 0;
  const pct = data.total_cost_basis_gbp ? (pl / data.total_cost_basis_gbp) * 100 : 0;
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{data.name ?? 'Portfolio Summary'}</Text>
      {data.description ? <Text style={styles.cardSubtitle}>{data.description}</Text> : null}
      <KeyValueRow label="Total Value" value={formatCurrency(data.total_market_value_gbp)} />
      <KeyValueRow label="Cost Basis" value={formatCurrency(data.total_cost_basis_gbp)} />
      <KeyValueRow
        label="Unrealised P&L"
        value={`${formatCurrency(pl)} (${formatPct(pct)})`}
        highlight={pl >= 0 ? 'positive' : 'negative'}
      />
      <KeyValueRow label="Cash Balance" value={formatCurrency(data.free_cash_balance_gbp)} />
      <KeyValueRow label="Holdings" value={String(data.holding_count ?? 0)} />
    </View>
  );
}

// ── 2. Table (get_portfolio_holdings) ───────────────────────────────────────

function PortfolioHoldingsRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const holdings = data.holdings ?? [];
  if (holdings.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No holdings found.</Text>
    );
  }
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator>
      <View>
        <View style={[styles.tableRow, styles.tableHeader]}>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Ticker
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Shares
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Cost/Share
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Value
          </Text>
        </View>
        {holdings.map((h: any, i: number) => (
          <View key={h.ticker ?? i} style={[styles.tableRow, i % 2 === 1 && { opacity: 0.85 }]}>
            <Text style={[styles.tableCell, { color: theme.text }]}>{h.ticker}</Text>
            <Text style={[styles.tableCell, { color: theme.text }]}>{formatNumber(h.shares)}</Text>
            <Text style={[styles.tableCell, { color: theme.text }]}>
              {formatCurrency(h.average_cost_basis)}
            </Text>
            <Text style={[styles.tableCell, { color: theme.text }]}>
              {h.average_cost_basis_gbp != null && h.shares != null
                ? formatCurrency(h.average_cost_basis_gbp * h.shares)
                : '—'}
            </Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// ── 3. Horizontal bars (get_sector_exposure) ────────────────────────────────

function SectorExposureRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const sectors = data.sectors ?? [];
  if (sectors.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
        No sector data available.
      </Text>
    );
  }
  return (
    <View style={styles.card}>
      {sectors.map((s: any) => (
        <View key={s.sector} style={styles.barRow}>
          <View style={styles.barLabelRow}>
            <Text style={[styles.barLabel, { color: theme.text }]}>{s.sector}</Text>
            <Text style={[styles.barValue, { color: theme.textSecondary }]}>
              {s.allocation_pct?.toFixed(1)}%
            </Text>
          </View>
          <View style={[styles.barTrack, { backgroundColor: theme.border }]}>
            <View
              style={[
                styles.barFill,
                {
                  width: `${Math.min(s.allocation_pct ?? 0, 100)}%`,
                  backgroundColor: theme.primary,
                },
              ]}
            />
          </View>
          <Text style={[styles.barSub, { color: theme.textSecondary }]}>
            {s.tickers?.join(', ')}
          </Text>
        </View>
      ))}
      <Text style={[styles.barTotal, { color: theme.textSecondary }]}>
        Total: {formatCurrency(data.total_value_gbp)}
      </Text>
    </View>
  );
}

// ── 4. Metrics card (get_portfolio_performance) ─────────────────────────────

function PortfolioPerformanceRenderer({ data }: { data: any }) {
  const twr = data.twr as number | undefined;
  const twrAnn = data.twr_annualised as number | undefined;
  const gain = data.total_gain_loss as number | undefined;
  const gainPct = data.total_gain_loss_pct as number | undefined;
  return (
    <View style={styles.metricsGrid}>
      {twr != null && (
        <MetricBox
          label="TWR"
          value={formatPct(twr)}
          highlight={twr >= 0 ? 'positive' : 'negative'}
        />
      )}
      {twrAnn != null && (
        <MetricBox
          label="Ann. TWR"
          value={formatPct(twrAnn)}
          highlight={twrAnn >= 0 ? 'positive' : 'negative'}
        />
      )}
      {gain != null && (
        <MetricBox
          label="Total Gain"
          value={formatCurrency(gain)}
          highlight={gain >= 0 ? 'positive' : 'negative'}
        />
      )}
      {gainPct != null && (
        <MetricBox
          label="Gain %"
          value={formatPct(gainPct)}
          highlight={gainPct >= 0 ? 'positive' : 'negative'}
        />
      )}
    </View>
  );
}

function MetricBox({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: 'positive' | 'negative';
}) {
  const { theme } = useTheme();
  const color =
    highlight === 'positive' ? '#10b981' : highlight === 'negative' ? '#FF3B30' : theme.text;
  return (
    <View style={[styles.metricBox, { backgroundColor: theme.surface }]}>
      <Text style={[styles.metricLabel, { color: theme.textSecondary }]}>{label}</Text>
      <Text style={[styles.metricValue, { color }]}>{value}</Text>
    </View>
  );
}

// ── 5. Comparison card (compare_to_benchmark) ───────────────────────────────

function BenchmarkComparisonRenderer({ data }: { data: any }) {
  const alpha = data.excess_return_alpha as number | undefined;
  return (
    <View style={styles.card}>
      <KeyValueRow label="Portfolio Return" value={formatPct(data.portfolio_return)} />
      <KeyValueRow
        label={`${data.benchmark_ticker ?? 'Benchmark'} Return`}
        value={formatPct(data.benchmark_return)}
      />
      <KeyValueRow
        label="Alpha"
        value={formatPct(alpha)}
        highlight={alpha != null ? (alpha >= 0 ? 'positive' : 'negative') : undefined}
      />
      <KeyValueRow label="Tracking Error" value={formatPct(data.tracking_error)} />
      <KeyValueRow
        label="Info Ratio"
        value={data.information_ratio != null ? data.information_ratio.toFixed(2) : '—'}
      />
    </View>
  );
}

// ── 6. Score + bars (get_portfolio_diversification_score) ───────────────────

function DiversificationScoreRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const exposures = data.ticker_exposures ?? [];
  const score = data.hhi_score;
  const isWellDiversified = score != null && score < 1000;
  return (
    <View style={styles.card}>
      <View style={styles.scoreRow}>
        <Text style={[styles.scoreValue, { color: isWellDiversified ? '#10b981' : '#FF3B30' }]}>
          {score != null ? score.toFixed(0) : '—'}
        </Text>
        <Text style={[styles.scoreLabel, { color: theme.textSecondary }]}>
          {data.concentration_level ?? 'Unknown'} concentration
        </Text>
      </View>
      <KeyValueRow label="Effective Holdings" value={data.effective_holdings?.toFixed(1) ?? '—'} />
      {exposures.slice(0, 5).map((e: any) => (
        <View key={e.ticker} style={styles.barRow}>
          <View style={styles.barLabelRow}>
            <Text style={[styles.barLabel, { color: theme.text }]}>{e.ticker}</Text>
            <Text style={[styles.barValue, { color: theme.textSecondary }]}>
              {e.exposure_pct?.toFixed(1)}%
            </Text>
          </View>
          <View style={[styles.barTrack, { backgroundColor: theme.border }]}>
            <View
              style={[
                styles.barFill,
                { width: `${Math.min(e.exposure_pct ?? 0, 100)}%`, backgroundColor: theme.primary },
              ]}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

// ── 7. Table (compare_tickers_side_by_side) ────────────────────────────────

function TickerComparisonRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const tickers = data.tickers ?? [];
  if (tickers.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No comparison data.</Text>
    );
  }
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator>
      <View>
        <View style={[styles.tableRow, styles.tableHeader]}>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Metric
          </Text>
          {tickers.map((t: any) => (
            <Text
              key={t.ticker}
              style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}
            >
              {t.ticker}
            </Text>
          ))}
        </View>
        {['price', 'change_pct', 'market_cap', 'pe_ratio', 'sector'].map((metric) => (
          <View key={metric} style={[styles.tableRow, { opacity: 0.9 }]}>
            <Text style={[styles.tableCell, { color: theme.textSecondary }]}>{metric}</Text>
            {tickers.map((t: any, i: number) => (
              <Text key={i} style={[styles.tableCell, { color: theme.text }]}>
                {metric === 'price'
                  ? formatCurrency(t[metric])
                  : metric === 'change_pct'
                    ? formatPct(t[metric])
                    : metric === 'market_cap'
                      ? formatLargeNumber(t[metric])
                      : metric === 'pe_ratio'
                        ? (t[metric]?.toFixed(2) ?? '—')
                        : (t[metric] ?? '—')}
              </Text>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// ── 8. Mini table (get_market_ohlcv) ───────────────────────────────────────

function OhlcvRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const rows = data.ohlcv ?? [];
  if (rows.length === 0) {
    return <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No OHLCV data.</Text>;
  }
  const latest = rows.slice(0, 10);
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator>
      <View>
        <View style={[styles.tableRow, styles.tableHeader]}>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Date
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            O
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            H
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            L
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            C
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Vol
          </Text>
        </View>
        {latest.map((r: any, i: number) => (
          <View key={i} style={[styles.tableRow, i % 2 === 1 && { opacity: 0.85 }]}>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.date ? String(r.date).slice(0, 10) : '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.open?.toFixed(2) ?? '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.high?.toFixed(2) ?? '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.low?.toFixed(2) ?? '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.close?.toFixed(2) ?? '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {r.volume != null ? formatNumber(r.volume) : '—'}
            </Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// ── 9. Quote card (get_market_quote) ───────────────────────────────────────

function QuoteRenderer({ data }: { data: any }) {
  const change = data.change as number | undefined;
  const changePct = data.change_pct as number | undefined;
  const isUp = (change ?? 0) >= 0;
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{data.ticker}</Text>
      <Text style={[styles.quotePrice, { color: isUp ? '#10b981' : '#FF3B30' }]}>
        {formatCurrency(data.price)}
      </Text>
      <Text style={[styles.quoteChange, { color: isUp ? '#10b981' : '#FF3B30' }]}>
        {change != null ? `${isUp ? '+' : ''}${change.toFixed(2)}` : '—'} ({formatPct(changePct)})
      </Text>
      <KeyValueRow label="Prev Close" value={formatCurrency(data.previous_close)} />
      <KeyValueRow label="Volume" value={formatNumber(data.volume)} />
    </View>
  );
}

// ── 10. Info card (get_ticker_info) ─────────────────────────────────────────

function TickerInfoRenderer({ data }: { data: any }) {
  return (
    <ScrollView style={styles.infoScroll} nestedScrollEnabled>
      <Text style={styles.cardTitle}>{data.company_name ?? data.ticker}</Text>
      {data.description ? (
        <Text style={styles.infoDescription} numberOfLines={4}>
          {data.description}
        </Text>
      ) : null}
      <KeyValueRow label="Sector" value={data.sector ?? '—'} />
      <KeyValueRow label="Industry" value={data.industry ?? '—'} />
      <KeyValueRow label="Market Cap" value={formatLargeNumber(data.market_cap)} />
      <KeyValueRow label="P/E Ratio" value={data.pe_ratio?.toFixed(2) ?? '—'} />
      <KeyValueRow
        label="Div. Yield"
        value={data.dividend_yield != null ? formatPct(data.dividend_yield * 100) : '—'}
      />
      <KeyValueRow label="Country" value={data.country ?? '—'} />
      <KeyValueRow label="Exchange" value={data.exchange ?? '—'} />
    </ScrollView>
  );
}

// ── 11. Article list (get_market_news) ──────────────────────────────────────

function NewsRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const articles = data.articles ?? [];
  if (articles.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No news articles.</Text>
    );
  }
  return (
    <View style={styles.articleList}>
      {articles.map((a: any, i: number) => (
        <View key={i} style={[styles.articleItem, { borderBottomColor: theme.border }]}>
          <Text style={[styles.articleTitle, { color: theme.text }]} numberOfLines={2}>
            {a.title ?? 'Untitled'}
          </Text>
          <Text style={[styles.articleMeta, { color: theme.textSecondary }]}>
            {a.publisher ?? ''}
            {a.published_date ? ` · ${String(a.published_date).slice(0, 10)}` : ''}
          </Text>
          {a.summary ? (
            <Text style={[styles.articleSummary, { color: theme.textSecondary }]} numberOfLines={2}>
              {a.summary}
            </Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

// ── 12. Direction badge (get_lstm_forecast) ────────────────────────────────

function LstmForecastRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const pred = data.prediction as string | undefined;
  const conf = data.confidence as number | undefined;
  const color = pred === 'UP' ? '#10b981' : pred === 'DOWN' ? '#FF3B30' : '#6b7280'; // FLAT → gray
  return (
    <View style={styles.card}>
      <View style={styles.forecastRow}>
        <View style={[styles.badge, { backgroundColor: color + '20' }]}>
          <Text style={[styles.badgeText, { color }]}>{pred ?? 'N/A'}</Text>
        </View>
        {conf != null && (
          <Text style={[styles.confText, { color: theme.text }]}>
            {`${(conf * 100).toFixed(0)}% confidence`}
          </Text>
        )}
      </View>
      {data.ticker ? <KeyValueRow label="Ticker" value={data.ticker} /> : null}
      {data.model_version ? <KeyValueRow label="Model" value={data.model_version} /> : null}
    </View>
  );
}

// ── 13. Category bars (get_spending_analysis) ───────────────────────────────

function SpendingAnalysisRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const categories = data.category_breakdown ?? [];
  if (categories.length === 0) {
    return (
      <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No spending data.</Text>
    );
  }
  return (
    <View style={styles.card}>
      <KeyValueRow label="Total Spent" value={formatCurrency(data.total_spent_gbp)} />
      {categories.map((c: any) => (
        <View key={c.name} style={styles.barRow}>
          <View style={styles.barLabelRow}>
            <Text style={[styles.barLabel, { color: theme.text }]}>{c.name}</Text>
            <Text style={[styles.barValue, { color: theme.textSecondary }]}>
              {formatCurrency(c.amount_gbp)} ({c.pct_of_total?.toFixed(1)}%)
            </Text>
          </View>
          <View style={[styles.barTrack, { backgroundColor: theme.border }]}>
            <View
              style={[
                styles.barFill,
                { width: `${Math.min(c.pct_of_total ?? 0, 100)}%`, backgroundColor: theme.primary },
              ]}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

// ── 14. Transaction table (get_recent_transactions) ─────────────────────────

function RecentTransactionsRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  const txs = data.transactions ?? [];
  if (txs.length === 0) {
    return <Text style={[styles.emptyText, { color: theme.textSecondary }]}>No transactions.</Text>;
  }
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator>
      <View>
        <View style={[styles.tableRow, styles.tableHeader]}>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Date
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Type
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Ticker
          </Text>
          <Text style={[styles.tableCell, styles.tableHeaderCell, { color: theme.textSecondary }]}>
            Amount
          </Text>
        </View>
        {txs.slice(0, 10).map((t: any, i: number) => (
          <View key={i} style={[styles.tableRow, i % 2 === 1 && { opacity: 0.85 }]}>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {t.date ? String(t.date).slice(0, 10) : '—'}
            </Text>
            <Text
              style={[
                styles.tableCellSm,
                {
                  color: t.type === 'BUY' ? '#10b981' : t.type === 'SELL' ? '#FF3B30' : theme.text,
                },
              ]}
            >
              {t.type ?? '—'}
            </Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>{t.ticker ?? '—'}</Text>
            <Text style={[styles.tableCellSm, { color: theme.text }]}>
              {t.total_amount_gbp != null
                ? formatCurrency(t.total_amount_gbp)
                : t.total_amount != null
                  ? formatCurrency(t.total_amount)
                  : '—'}
            </Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// ── 15. Summary card (get_cash_flow_summary) ────────────────────────────────

function CashFlowSummaryRenderer({ data }: { data: any }) {
  const rec = data.most_recent_deposit;
  return (
    <View style={styles.card}>
      <KeyValueRow label="Total Deposits" value={formatCurrency(data.total_deposits_gbp)} />
      <KeyValueRow label="Deposit Count" value={formatNumber(data.deposit_count)} />
      {rec ? (
        <KeyValueRow
          label="Last Deposit"
          value={`${formatCurrency(rec.amount)}${rec.date ? ` on ${String(rec.date).slice(0, 10)}` : ''}`}
        />
      ) : null}
    </View>
  );
}

// ── 16. Dividend card (get_dividend_insights) ───────────────────────────────

function DividendInsightsRenderer({ data }: { data: any }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{data.ticker ?? 'Dividend'}</Text>
      <KeyValueRow
        label="Dividend Yield"
        value={data.dividend_yield != null ? formatPct(data.dividend_yield * 100) : '—'}
      />
      <KeyValueRow
        label="Dividend Rate"
        value={data.dividend_rate != null ? formatCurrency(data.dividend_rate) : '—'}
      />
      <KeyValueRow
        label="Payout Ratio"
        value={data.payout_ratio != null ? formatPct(data.payout_ratio * 100) : '—'}
      />
      <KeyValueRow
        label="Ex-Dividend Date"
        value={data.ex_dividend_date ? String(data.ex_dividend_date).slice(0, 10) : '—'}
      />
      {data.last_dividend_date ? (
        <KeyValueRow
          label="Last Dividend"
          value={`${formatCurrency(data.last_dividend_value)} on ${data.last_dividend_date}`}
        />
      ) : null}
    </View>
  );
}

// ── Fallback: JSON dump ─────────────────────────────────────────────────────

function JsonFallbackRenderer({ data }: { data: any }) {
  const { theme } = useTheme();
  return (
    <ScrollView style={styles.jsonScroll} nestedScrollEnabled>
      <Text style={[styles.jsonText, { color: theme.textSecondary }]}>
        {JSON.stringify(data, null, 2)}
      </Text>
    </ScrollView>
  );
}

// ── Renderer Registry ───────────────────────────────────────────────────────

type RendererFn = (props: { data: any }) => React.ReactElement;

const RENDERER_REGISTRY: Record<string, RendererFn> = {
  get_portfolio_summary: PortfolioSummaryRenderer,
  get_portfolio_holdings: PortfolioHoldingsRenderer,
  get_sector_exposure: SectorExposureRenderer,
  get_portfolio_performance: PortfolioPerformanceRenderer,
  compare_to_benchmark: BenchmarkComparisonRenderer,
  get_portfolio_diversification_score: DiversificationScoreRenderer,
  compare_tickers_side_by_side: TickerComparisonRenderer,
  get_market_ohlcv: OhlcvRenderer,
  get_market_quote: QuoteRenderer,
  get_ticker_info: TickerInfoRenderer,
  get_market_news: NewsRenderer,
  get_lstm_forecast: LstmForecastRenderer,
  get_spending_analysis: SpendingAnalysisRenderer,
  get_recent_transactions: RecentTransactionsRenderer,
  get_cash_flow_summary: CashFlowSummaryRenderer,
  get_dividend_insights: DividendInsightsRenderer,
};

const DEFAULT_RENDERER: RendererFn = JsonFallbackRenderer;

/**
 * Resolve the appropriate renderer for a tool name.
 * Falls back to JSON dump for unknown tools.
 */
export function getToolRenderer(toolName: string): RendererFn {
  return RENDERER_REGISTRY[toolName] ?? DEFAULT_RENDERER;
}

/**
 * Render a tool result using the appropriate renderer.
 */
export function renderToolResult(toolName: string, data: any): React.ReactElement {
  const Renderer = getToolRenderer(toolName);
  return <Renderer data={data} />;
}

// ── Styles ──────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  card: {
    padding: spacing.sm,
    gap: spacing.xs,
  },
  cardTitle: {
    ...typography.subtitle,
    marginBottom: spacing.xs,
  },
  cardSubtitle: {
    ...typography.caption,
    marginBottom: spacing.xs,
  },
  kvRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 2,
  },
  kvLabel: {
    ...typography.caption,
    flex: 1,
  },
  kvValue: {
    ...typography.caption,
    ...typography.captionStrong,
    textAlign: 'right',
  },
  tableRow: {
    flexDirection: 'row',
    paddingVertical: 4,
    paddingHorizontal: spacing.xs,
  },
  tableHeader: {
    borderBottomWidth: 1,
    borderBottomColor: '#00000020',
    paddingBottom: 6,
  },
  tableHeaderCell: {
    ...typography.overline,
    fontSize: 10,
  },
  tableCell: {
    ...typography.caption,
    width: 80,
    fontSize: 12,
  },
  tableCellSm: {
    ...typography.caption,
    width: 64,
    fontSize: 11,
  },
  barRow: {
    marginBottom: spacing.sm,
  },
  barLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 2,
  },
  barLabel: {
    ...typography.caption,
    fontSize: 12,
  },
  barValue: {
    ...typography.caption,
    fontSize: 11,
  },
  barTrack: {
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 4,
  },
  barSub: {
    ...typography.caption,
    fontSize: 10,
    marginTop: 1,
  },
  barTotal: {
    ...typography.caption,
    fontSize: 11,
    marginTop: spacing.xs,
  },
  sectionHeader: {
    ...typography.overline,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    padding: spacing.sm,
  },
  metricBox: {
    flex: 1,
    minWidth: 80,
    padding: spacing.sm,
    borderRadius: radii.sm,
    alignItems: 'center',
  },
  metricLabel: {
    ...typography.caption,
    fontSize: 10,
    marginBottom: 2,
  },
  metricValue: {
    ...typography.metricSm,
    fontSize: 16,
  },
  scoreRow: {
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  scoreValue: {
    ...typography.metric,
    fontSize: 36,
  },
  scoreLabel: {
    ...typography.caption,
    marginTop: 2,
  },
  quotePrice: {
    ...typography.metric,
    fontSize: 28,
    marginBottom: spacing.xs,
  },
  quoteChange: {
    ...typography.subtitle,
    marginBottom: spacing.sm,
  },
  forecastRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  badge: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radii.pill,
  },
  badgeText: {
    ...typography.captionStrong,
    fontSize: 14,
  },
  confText: {
    ...typography.body,
  },
  infoScroll: {
    maxHeight: 200,
  },
  infoDescription: {
    ...typography.caption,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  articleList: {
    gap: 0,
  },
  articleItem: {
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  articleTitle: {
    ...typography.caption,
    ...typography.captionStrong,
  },
  articleMeta: {
    ...typography.caption,
    fontSize: 10,
    marginTop: 2,
  },
  articleSummary: {
    ...typography.caption,
    fontSize: 11,
    marginTop: 2,
  },
  jsonScroll: {
    maxHeight: 200,
  },
  jsonText: {
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 10,
    lineHeight: 14,
  },
  emptyText: {
    ...typography.caption,
    padding: spacing.sm,
    textAlign: 'center',
  },
});

/**
 * OnboardingScreen
 *
 * Welcome screen shown on first launch with an animated chart and CTA.
 */

import React, { useMemo, useRef, useEffect } from 'react';
import { Animated, Easing } from 'react-native';
import Svg, { Rect, Line } from 'react-native-svg';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { Text, View } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import PrimaryButton from '../components/PrimaryButton';
import { spacing, typography } from '../styles/theme';
import { brandColors } from '../contexts/ThemeContext';
import { useNavigation } from '@react-navigation/native';
import { useTheme } from '../contexts/ThemeContext';

type OHLC = { open: number; high: number; low: number; close: number };

/**
 * Generate OHLC candlestick data for the onboarding chart.
 * @param count Number of candles to generate
 * @param start Starting price value
 */
const makeOHLCSeries = (count: number, start = 100) => {
  const res: OHLC[] = [];
  let prevClose = start;
  const majorSwings = Math.max(3, Math.round(count / 6));
  const phase = Math.random() * Math.PI * 2;

  // Calculate total upward movement needed to ensure end > start
  const totalUpwardTarget = start * (0.3 + Math.random() * 0.4); // 30-70% increase
  const upwardPerStep = totalUpwardTarget / count;

  for (let i = 0; i < count; i++) {
    const open = prevClose;
    const progress = i / Math.max(1, count - 1);

    // Stronger baseline uptrend to guarantee overall rise
    const baselineUp = upwardPerStep + progress * (Math.random() * 4 + 2);

    // Reduced major swings for predictability
    const major = Math.sin(progress * Math.PI * majorSwings + phase) * (4 + Math.random() * 4);

    // Minimal micro fluctuations
    const micro =
      (Math.sin(progress * Math.PI * 2.3) + Math.sin(progress * Math.PI * 4.6) * 0.3) *
      (2 + Math.random() * 2);

    // Slightly more frequent and bigger shocks for added dips, but only in the middle (not first/last 3 candles)
    const shock = i >= 3 && i < count - 3 && Math.random() < 0.4 ? -(6 + Math.random() * 8) : 0;

    const delta = baselineUp * 0.8 + major * 0.5 + micro + shock + (Math.random() - 0.5) * 2;
    const close = Math.max(1, open + delta);

    // Ensure some volatility but keep highs/lows reasonable
    const volatility = 3 + Math.random() * 4;
    const high = Math.max(open, close) + Math.random() * volatility;
    const low = Math.min(open, close) - Math.random() * volatility;

    res.push({ open, high, low, close });
    prevClose = close;
  }

  // Final adjustment: ensure last close > first open
  if (res.length > 0 && res[res.length - 1].close <= start) {
    const last = res[res.length - 1];
    last.close = start + Math.random() * 10 + 5; // Boost by 5-15
    last.high = Math.max(last.high, last.close + Math.random() * 3);
  }

  return res;
};

export default function OnboardingScreen() {
  const navigation = useNavigation();
  const {
    width: screenWidth,
    isSmallPhone,
    isTablet,
    contentHorizontalPadding,
    sectionVerticalSpacing,
  } = useBreakpoint();
  const { theme } = useTheme();

  const handleGetStarted = () => navigation.navigate('Login' as never);

  const graphHeight = isTablet ? 420 : isSmallPhone ? 280 : 360;
  const graphWidth = Math.max(240, screenWidth - contentHorizontalPadding * 2);
  const insets = useSafeAreaInsets();
  const chartRightPad = Math.max(insets.right, contentHorizontalPadding);

  const buttonMaxWidth = isTablet ? screenWidth * 0.5 : screenWidth * 0.75;

  const candleCount = 18;
  const data = useMemo(() => makeOHLCSeries(candleCount, 90), [candleCount]);
  const progresses = useRef<Animated.Value[]>(
    Array.from({ length: candleCount }, () => new Animated.Value(0)),
  ).current;

  useEffect(() => {
    const animations = progresses.map((p, idx) =>
      Animated.timing(p, {
        toValue: 1,
        duration: 700,
        delay: idx * 90,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: false,
      }),
    );
    Animated.stagger(60, animations).start();
  }, [progresses]);

  const values = data.flatMap((d) => [d.high, d.low, d.open, d.close]);
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const pad = 10;
  const usableH = Math.max(40, graphHeight - pad * 2);

  const valueToY = (v: number) => {
    if (vMax === vMin) return pad + usableH / 2;
    const t = (v - vMin) / (vMax - vMin);
    return pad + (1 - t) * usableH;
  };

  const approxStep = candleCount > 1 ? graphWidth / (candleCount - 1) : graphWidth;
  const approxBody = Math.max(8, Math.min(approxStep * 0.64, 36));
  const minSidePad = Math.ceil(approxBody / 2) + 2;
  const effectiveLeftPad = Math.max(0, 0, minSidePad);
  const effectiveRightPad = Math.max(chartRightPad, minSidePad);
  const availableW = Math.max(40, graphWidth - effectiveLeftPad - effectiveRightPad);

  let estStep = candleCount > 1 ? availableW / (candleCount - 1) : availableW;
  let estBody = Math.max(8, Math.min(estStep * 0.64, 36));
  if (candleCount > 1) {
    const refined = Math.max(6, (availableW - estBody) / (candleCount - 1));
    estStep = refined;
    estBody = Math.max(8, Math.min(estStep * 0.64, 36));
  }

  const step = estStep;
  const bodyWidth = estBody;
  const computeXCenter = (i: number) => effectiveLeftPad + bodyWidth / 2 + step * i;

  const AnimatedRect: any = Animated.createAnimatedComponent(Rect as any);
  const AnimatedLine: any = Animated.createAnimatedComponent(Line as any);

  return (
    <ScreenContainer contentStyle={{ paddingVertical: sectionVerticalSpacing }}>
      <PageHeader>
        <Text
          style={[
            typography.display,
            { color: theme.text, fontWeight: '800', marginBottom: spacing.md },
          ]}
        >
          Stock
          <Text style={{ color: brandColors.green }}>Lens</Text>
        </Text>
        <>
          <Text style={[typography.pageSubtitle, { color: theme.textSecondary }]}>
            Scan your Spending
          </Text>
          <Text style={[typography.pageSubtitle, { color: theme.textSecondary }]}>
            See your missed Investing
          </Text>
        </>
      </PageHeader>

      <View style={{ width: '100%', justifyContent: 'center', alignItems: 'center' }}>
        <Svg
          testID="onboarding-chart-svg"
          width={graphWidth}
          height={graphHeight}
          viewBox={`0 0 ${graphWidth} ${graphHeight}`}
        >
          {data.map((d, i) => {
            const p = progresses[i];
            const xCenter = computeXCenter(i);
            const x = xCenter - bodyWidth / 2;

            const yOpen = valueToY(d.open);
            const yClose = valueToY(d.close);
            const yHigh = valueToY(d.high);
            const yLow = valueToY(d.low);

            const isUp = d.close >= d.open;
            const fill = isUp ? brandColors.green : brandColors.red;
            const stroke = '#00000014';

            const bodyY = Math.min(yOpen, yClose);
            const bodyH = Math.max(1, Math.abs(yClose - yOpen));

            const animY = p.interpolate({
              inputRange: [0, 1],
              outputRange: [pad + usableH, bodyY],
            }) as any;
            const animH = p.interpolate({ inputRange: [0, 1], outputRange: [0, bodyH] }) as any;
            const animHigh = p.interpolate({
              inputRange: [0, 1],
              outputRange: [pad + usableH, yHigh],
            }) as any;
            const animLow = p.interpolate({
              inputRange: [0, 1],
              outputRange: [pad + usableH, yLow],
            }) as any;

            return (
              <React.Fragment key={`c-${i}`}>
                <AnimatedLine
                  x1={xCenter}
                  x2={xCenter}
                  y1={animHigh}
                  y2={animLow}
                  stroke={stroke}
                  strokeWidth={2}
                  strokeLinecap="round"
                  opacity={0.95}
                />
                <AnimatedRect
                  x={x}
                  y={animY}
                  width={bodyWidth}
                  height={animH}
                  fill={fill}
                  stroke={brandColors.black}
                  strokeOpacity={0.06}
                  rx={2}
                />
              </React.Fragment>
            );
          })}
        </Svg>
      </View>

      <View
        style={{
          alignSelf: isSmallPhone ? 'stretch' : 'flex-end',
          width: isTablet ? '40%' : isSmallPhone ? '100%' : '60%',
          maxWidth: buttonMaxWidth,
        }}
      >
        <PrimaryButton onPress={handleGetStarted} accessibilityLabel="Get started">
          Let's Get Started
        </PrimaryButton>
      </View>
    </ScreenContainer>
  );
}

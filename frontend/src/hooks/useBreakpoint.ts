/**
 * useBreakpoint
 *
 * Returns responsive layout info (orientation, device class, spacing, cardsPerRow).
 */

import { useMemo } from 'react';
import { useWindowDimensions } from 'react-native';
import { breakpoints, spacing } from '../styles/theme';

type BreakpointInfo = {
  /** Current window width in pixels */
  width: number;
  /** Current window height in pixels */
  height: number;
  /** Screen orientation based on width/height ratio */
  orientation: 'portrait' | 'landscape';
  /** True if width >= 768px (tablet size) */
  isTablet: boolean;
  /** True if width is between 414-767px */
  isLargePhone: boolean;
  /** True if width <= 360px (compact phones) */
  isSmallPhone: boolean;
  /** Recommended horizontal padding (16px or 32px) */
  contentHorizontalPadding: number;
  /** Recommended vertical section spacing (24px or 32px) */
  sectionVerticalSpacing: number;
  /** Suggested number of cards per row in grid layouts (2 or 3) */
  cardsPerRow: number;
};

/**
 * Returns responsive breakpoint information based on current window size.
 * Values update automatically when window dimensions change.
 */
export function useBreakpoint(): BreakpointInfo {
  const { width, height } = useWindowDimensions();
  return useMemo(() => {
    const orientation: 'portrait' | 'landscape' = width >= height ? 'landscape' : 'portrait';
    const isTablet = width >= breakpoints.tablet;
    const isLargePhone = width >= breakpoints.largePhone && width < breakpoints.tablet;
    const isSmallPhone = width <= breakpoints.smallPhone;

    const contentHorizontalPadding = isTablet ? spacing.xxl : spacing.md;

    const sectionVerticalSpacing = isTablet ? spacing.xxl : spacing.xl;
    const cardsPerRow = isTablet ? 3 : 2;

    return {
      width,
      height,
      orientation,
      isTablet,
      isLargePhone,
      isSmallPhone,
      contentHorizontalPadding,
      sectionVerticalSpacing,
      cardsPerRow,
    };
  }, [height, width]);
}

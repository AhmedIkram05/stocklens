/**
 * Theme Tokens
 *
 * Non-color design tokens: spacing, sizes, radii, typography, shadows and breakpoints.
 */

import { TextStyle, ViewStyle } from 'react-native';
import { scale, moderateScale } from '../utils/responsive';

/**
 * spacing - Consistent spacing scale
 * Values scale proportionally based on device width
 */
export const spacing = {
  xs: scale(4),
  sm: scale(8),
  md: scale(12),
  lg: scale(16),
  xl: scale(24),
  xxl: scale(32),
} as const;

/**
 * sizes - Common UI element dimensions
 *
 * Values use moderateScale() for balanced sizing across devices
 *
 * Controls:
 * - controlSm (36px): Small buttons, compact inputs
 * - controlMd (44px): Standard touch targets (iOS/Android guideline)
 * - controlLg (56px): Large primary actions
 *
 * Avatars:
 * - avatarSm (40px): List item avatars
 * - avatarMd (56px): Profile avatars
 *
 * Usage:
 * height: sizes.controlMd, width: sizes.avatarSm
 */
export const sizes = {
  controlSm: Math.round(moderateScale(36)),
  controlMd: Math.round(moderateScale(44)),
  controlLg: Math.round(moderateScale(56)),
  avatarSm: Math.round(scale(40)),
  avatarMd: Math.round(scale(56)),
} as const;

/**
 * radii - Border radius scale
 *
 * Values use moderateScale() with minimum thresholds for small devices
 *
 * Scale:
 * - sm (6-8px): Subtle rounding, buttons, inputs
 * - md (8-12px): Default card rounding
 * - lg (12-16px): Large cards, modals
 * - xl (16-24px): Hero elements, featured cards
 * - pill (999px): Fully rounded (badges, pills)
 *
 * Usage:
 * borderRadius: radii.md, borderRadius: radii.pill
 */
export const radii = {
  sm: Math.max(6, Math.round(moderateScale(8))),
  md: Math.max(8, Math.round(moderateScale(12))),
  lg: Math.max(12, Math.round(moderateScale(16))),
  xl: Math.max(16, Math.round(moderateScale(24))),
  pill: 999,
} as const;

/**
 * breakpoints - Device width breakpoints
 *
 * Used by useBreakpoint hook for responsive layouts
 *
 * Breakpoints:
 * - smallPhone (360px): Small Android devices (e.g., older budget phones)
 * - largePhone (414px): Large phones (e.g., iPhone Pro Max)
 * - tablet (768px): Tablets and iPad Mini
 *
 * Usage:
 * const { isTablet } = useBreakpoint(); // checks if width >= 768
 */
export const breakpoints = {
  smallPhone: 360,
  largePhone: 414,
  tablet: 768,
} as const;

/**
 * typography - Text style definitions
 *
 * All font sizes use moderateScale() for balanced text scaling
 *
 * Text Hierarchy:
 * - display (48px): Hero text, splash screens
 * - pageTitle (34px): Screen titles
 * - pageSubtitle (20px): Screen subtitles (italic)
 * - sectionTitle (22px): Section headings
 * - subtitle (18px): Card/component titles
 * - metric (32px): Large numbers, statistics
 * - metricSm (18px): Small metrics, inline numbers
 * - body (16px): Body text, paragraphs
 * - bodyStrong (16px): Emphasized body text
 * - caption (14px): Small text, descriptions
 * - captionStrong (14px): Emphasized captions
 * - button (16px): Button text
 * - overline (12px): Labels, tags (all caps with letter spacing)
 *
 * Usage:
 * ...typography.body, fontSize: typography.pageTitle.fontSize
 */
export const typography = {
  display: {
    fontSize: moderateScale(48),
    fontWeight: '700',
  },
  pageTitle: {
    fontSize: moderateScale(34),
    fontWeight: '700',
  },
  pageSubtitle: {
    fontSize: moderateScale(20),
    fontStyle: 'italic',
    lineHeight: Math.round(moderateScale(26)),
  },
  sectionTitle: {
    fontSize: moderateScale(22),
    fontWeight: '700',
  },
  subtitle: {
    fontSize: moderateScale(18),
    fontWeight: '500',
  },
  metric: {
    fontSize: moderateScale(32),
    fontWeight: '700',
  },
  metricSm: {
    fontSize: moderateScale(18),
    fontWeight: '700',
  },
  body: {
    fontSize: moderateScale(16),
    fontWeight: '400',
  },
  bodyStrong: {
    fontSize: moderateScale(16),
    fontWeight: '600',
  },
  caption: {
    fontSize: moderateScale(14),
    fontWeight: '400',
  },
  captionStrong: {
    fontSize: moderateScale(14),
    fontWeight: '600',
  },
  button: {
    fontSize: moderateScale(16),
    fontWeight: '600',
  },
  overline: {
    fontSize: moderateScale(12),
    fontWeight: '500',
    letterSpacing: 1,
  },
} satisfies Record<string, TextStyle>;

/**
 * shadows - Elevation system for depth
 * Platform-aware shadows (iOS uses shadow properties, Android uses elevation)
 */
export const shadows = {
  level1: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
  },
  level2: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 6,
    elevation: 2,
  },
} satisfies Record<string, ViewStyle>;

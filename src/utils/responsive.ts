/**
 * Responsive
 *
 * Device-aware scaling helpers: scale, verticalScale, moderateScale and cap.
 */

import { Dimensions } from 'react-native';

/**
 * Current screen dimensions
 */
const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');

/**
 * Base dimensions (iPhone X reference)
 */
const BASE_WIDTH = 375;
const BASE_HEIGHT = 812;

/**
 * Tablet width threshold (768px)
 */
const TABLET_WIDTH_THRESHOLD = 768;

/**
 * Tablet scaling multiplier (0.45 for tablets, 1.0 for phones)
 */
const TABLET_SCALE_MULTIPLIER = SCREEN_WIDTH >= TABLET_WIDTH_THRESHOLD ? 0.45 : 1;

/** Scale a base size proportionally to the device width. */
export const scale = (size: number) =>
  Math.round((SCREEN_WIDTH / BASE_WIDTH) * TABLET_SCALE_MULTIPLIER * size);

/** Scale a base size proportionally to the device height. */
export const verticalScale = (size: number) =>
  Math.round((SCREEN_HEIGHT / BASE_HEIGHT) * TABLET_SCALE_MULTIPLIER * size);

/** Moderate scaling: interpolate between base size and full scale by `factor`. */
export const moderateScale = (size: number, factor = 0.5) =>
  Math.round(size + (scale(size) - size) * factor);

/** Clamp a value between optional `min` and `max` bounds. */
export const cap = (value: number, min?: number, max?: number) => {
  if (typeof min === 'number' && value < min) return min;
  if (typeof max === 'number' && value > max) return max;
  return value;
};

export default {
  scale,
  verticalScale,
  moderateScale,
  cap,
};

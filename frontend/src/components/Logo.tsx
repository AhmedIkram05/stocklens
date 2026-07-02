/**
 * Logo
 *
 * StockLens logo component (responsive image).
 */

import React from 'react';
import { Image, ImageStyle } from 'react-native';
import { useBreakpoint } from '../hooks/useBreakpoint';

type Props = {
  /** Optional custom width in pixels (overrides responsive calculation) */
  width?: number;
  /** Optional custom height in pixels (overrides responsive calculation) */
  height?: number;
  /** Optional custom styling for the Image */
  style?: ImageStyle;
  /** Optional test ID for automated testing */
  testID?: string;
};

const logoImage = require('../../assets/StockLens_Logo_T.png');

/**
 * Renders the StockLens logo with responsive dimensions.
 * Default width is 60% of screen width (capped at 360px/480px).
 * Default height maintains 2:1 aspect ratio.
 */
export default function Logo({ width, height, style, testID }: Props) {
  const { width: screenWidth, isTablet } = useBreakpoint();

  const defaultWidth = width ?? Math.min(Math.round(screenWidth * 0.6), isTablet ? 480 : 360);
  const defaultHeight = height ?? Math.round(defaultWidth * 0.5);

  return (
    <Image
      source={logoImage}
      style={[{ width: defaultWidth, height: defaultHeight }, style]}
      resizeMode="contain"
      testID={testID}
    />
  );
}

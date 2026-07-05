/**
 * Carousel
 *
 * Generic horizontal carousel (FlatList wrapper).
 */

import React from 'react';
import { FlatList, StyleProp, ViewStyle } from 'react-native';

type Props<T> = {
  /** Array of data items to display in the carousel */
  data: T[];
  /** Function to render each item in the carousel */
  renderItem: ({ item, index }: { item: T; index: number }) => React.ReactElement | null;
  /** Function to extract unique keys for each item */
  keyExtractor?: (item: T, index: number) => string;
  /** Distance between snap points in pixels (for snap-to-interval behavior) */
  snapInterval?: number;
  /** Optional styling for the FlatList content container */
  contentContainerStyle?: StyleProp<ViewStyle>;
  /** Optional styling for the FlatList itself */
  style?: StyleProp<ViewStyle>;
  /** Whether to show horizontal scroll indicator. Default: false */
  showsHorizontalScrollIndicator?: boolean;
  /** Scroll deceleration rate. Default: 'fast' */
  decelerationRate?: 'normal' | 'fast' | number;
  /** Snap alignment relative to container. Default: 'start' */
  snapToAlignment?: 'start' | 'center' | 'end';
};

/**
 * Renders a horizontal FlatList with optional snapping behavior.
 * Generic type T allows for type-safe data handling.
 */
export default function Carousel<T>({
  data,
  renderItem,
  keyExtractor,
  snapInterval,
  contentContainerStyle,
  style,
  showsHorizontalScrollIndicator = false,
  decelerationRate = 'fast',
  snapToAlignment = 'start',
}: Props<T>) {
  return (
    <FlatList
      data={data}
      horizontal
      keyExtractor={keyExtractor as any}
      showsHorizontalScrollIndicator={showsHorizontalScrollIndicator}
      contentContainerStyle={contentContainerStyle}
      snapToAlignment={snapToAlignment}
      decelerationRate={decelerationRate}
      snapToInterval={snapInterval}
      renderItem={({ item, index }) => renderItem({ item: item as T, index })}
      style={style}
    />
  );
}

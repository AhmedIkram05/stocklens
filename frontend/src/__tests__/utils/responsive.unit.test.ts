jest.mock('react-native', () => ({
  Dimensions: {
    get: jest.fn(() => ({ width: 375, height: 812, scale: 2, fontScale: 1 })),
  },
  StyleSheet: { create: (obj: any) => obj },
  Platform: { OS: 'ios', select: jest.fn((obj) => obj.ios || obj.default) },
}));

import { scale, verticalScale, moderateScale, cap } from '@/utils/responsive';

describe('responsive utils', () => {
  describe('scale', () => {
    it('scales size proportionally to screen width (iPhone X: 375)', () => {
      // scale = round((375 / 375) * 1 * size) = size
      expect(scale(10)).toBe(10);
      expect(scale(16)).toBe(16);
      expect(scale(100)).toBe(100);
    });

    it('returns integer values', () => {
      expect(Number.isInteger(scale(10.5))).toBe(true);
    });
  });

  describe('verticalScale', () => {
    it('scales size proportionally to screen height (iPhone X: 812)', () => {
      // verticalScale = round((812 / 812) * 1 * size) = size
      expect(verticalScale(10)).toBe(10);
      expect(verticalScale(16)).toBe(16);
      expect(verticalScale(100)).toBe(100);
    });

    it('returns integer values', () => {
      expect(Number.isInteger(verticalScale(10.5))).toBe(true);
    });
  });

  describe('moderateScale', () => {
    it('interpolates between base size and scaled size with default factor 0.5', () => {
      const base = 100;
      const result = moderateScale(base);
      // moderateScale = round(size + (scale(size) - size) * 0.5) = round(100 + 0) = 100
      expect(result).toBe(base);
    });

    it('uses custom factor when provided', () => {
      const base = 100;
      const result1 = moderateScale(base, 0);
      const result2 = moderateScale(base, 1);
      expect(result1).toBe(base);
      expect(result2).toBe(base);
    });

    it('returns integer values', () => {
      expect(Number.isInteger(moderateScale(10.5, 0.5))).toBe(true);
    });
  });

  describe('cap', () => {
    it('returns value when within bounds', () => {
      expect(cap(5, 0, 10)).toBe(5);
      expect(cap(0, 0, 10)).toBe(0);
      expect(cap(10, 0, 10)).toBe(10);
    });

    it('returns min when value is below min', () => {
      expect(cap(-5, 0, 10)).toBe(0);
      expect(cap(-100, 0, 10)).toBe(0);
    });

    it('returns max when value is above max', () => {
      expect(cap(15, 0, 10)).toBe(10);
      expect(cap(100, 0, 10)).toBe(10);
    });

    it('works with only min bound', () => {
      expect(cap(-5, 0)).toBe(0);
      expect(cap(5, 0)).toBe(5);
    });

    it('works with only max bound', () => {
      expect(cap(15, undefined, 10)).toBe(10);
      expect(cap(5, undefined, 10)).toBe(5);
    });

    it('works with no bounds', () => {
      expect(cap(5)).toBe(5);
      expect(cap(-5)).toBe(-5);
    });
  });
});

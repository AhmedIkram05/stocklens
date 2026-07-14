import { act, renderHook } from '@testing-library/react-native';
import { useBreakpoint } from '@/hooks/useBreakpoint';

jest.mock(
  '@/utils/responsive',
  () => ({
    scale: jest.fn((size: number) => size),
    verticalScale: jest.fn((size: number) => size),
    moderateScale: jest.fn((size: number, _factor?: number) => size),
    cap: jest.fn((value: number, _min?: number, _max?: number) => value),
    default: {
      scale: jest.fn((size: number) => size),
      verticalScale: jest.fn((size: number) => size),
      moderateScale: jest.fn((size: number, _factor?: number) => size),
      cap: jest.fn((value: number, _min?: number, _max?: number) => value),
    },
  }),
  { virtual: true },
);

jest.mock(
  '@/styles/theme',
  () => ({
    spacing: {
      xs: 4,
      sm: 8,
      md: 12,
      lg: 16,
      xl: 24,
      xxl: 32,
    },
    breakpoints: {
      smallPhone: 360,
      largePhone: 414,
      tablet: 768,
    },
    sizes: {
      controlSm: 36,
      controlMd: 44,
      controlLg: 56,
      avatarSm: 40,
      avatarMd: 56,
    },
    radii: {
      sm: 8,
      md: 12,
      lg: 16,
      xl: 24,
      pill: 999,
    },
    typography: {
      display: { fontSize: 32, fontWeight: '700' },
      sectionTitle: { fontSize: 24, fontWeight: '600' },
      pageSubtitle: { fontSize: 16 },
      button: { fontSize: 16, fontWeight: '600' },
    },
    shadows: {
      level1: {},
      level2: {},
      level3: {},
    },
  }),
  { virtual: true },
);

jest.mock(
  'react-native',
  () => ({
    Dimensions: { get: jest.fn(() => ({ width: 375, height: 812, scale: 2, fontScale: 1 })) },
    useWindowDimensions: jest.fn(() => ({ width: 375, height: 812, scale: 2, fontScale: 1 })),
    StyleSheet: { create: (obj: any) => obj },
    Platform: { OS: 'ios', select: jest.fn((obj) => obj.ios || obj.default) },
  }),
  { virtual: true },
);

const mockUseWindowDimensions = jest.requireMock('react-native').useWindowDimensions as jest.Mock;

describe('useBreakpoint', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns phone dimensions for small phone (<= 360px)', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 320, height: 568, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.width).toBe(320);
    expect(result.current.height).toBe(568);
    expect(result.current.isSmallPhone).toBe(true);
    expect(result.current.isTablet).toBe(false);
    expect(result.current.isLargePhone).toBe(false);
    expect(result.current.contentHorizontalPadding).toBe(12);
    expect(result.current.sectionVerticalSpacing).toBe(24);
    expect(result.current.cardsPerRow).toBe(2);
  });

  it('returns phone dimensions for standard phone (375px)', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.width).toBe(375);
    expect(result.current.height).toBe(812);
    expect(result.current.isSmallPhone).toBe(false);
    expect(result.current.isTablet).toBe(false);
    expect(result.current.isLargePhone).toBe(false);
    expect(result.current.contentHorizontalPadding).toBe(12);
    expect(result.current.sectionVerticalSpacing).toBe(24);
    expect(result.current.cardsPerRow).toBe(2);
  });

  it('returns phone dimensions for large phone (414px)', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 414, height: 896, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.isLargePhone).toBe(true);
    expect(result.current.isTablet).toBe(false);
    expect(result.current.isSmallPhone).toBe(false);
    expect(result.current.contentHorizontalPadding).toBe(12);
    expect(result.current.sectionVerticalSpacing).toBe(24);
    expect(result.current.cardsPerRow).toBe(2);
  });

  it('returns tablet dimensions (>= 768px)', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 1024, height: 768, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.isTablet).toBe(true);
    expect(result.current.isLargePhone).toBe(false);
    expect(result.current.isSmallPhone).toBe(false);
    expect(result.current.contentHorizontalPadding).toBe(32);
    expect(result.current.sectionVerticalSpacing).toBe(32);
    expect(result.current.cardsPerRow).toBe(3);
  });

  it('returns portrait orientation when height > width', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.orientation).toBe('portrait');
  });

  it('returns landscape orientation when width > height', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 812, height: 375, scale: 2, fontScale: 1 });

    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.orientation).toBe('landscape');
  });

  it('updates values when dimensions change', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });
    const { result, rerender } = renderHook(() => useBreakpoint());

    expect(result.current.isTablet).toBe(false);
    expect(result.current.width).toBe(375);

    act(() => {
      mockUseWindowDimensions.mockReturnValue({ width: 1024, height: 768, scale: 2, fontScale: 1 });
      rerender(undefined);
    });

    expect(result.current.isTablet).toBe(true);
    expect(result.current.width).toBe(1024);
    expect(result.current.orientation).toBe('landscape');
  });

  it('returns correct spacing values for phone', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });
    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.contentHorizontalPadding).toBe(12);
    expect(result.current.sectionVerticalSpacing).toBe(24);
  });

  it('returns correct spacing values for tablet', () => {
    mockUseWindowDimensions.mockReturnValue({ width: 1024, height: 768, scale: 2, fontScale: 1 });
    const { result } = renderHook(() => useBreakpoint());

    expect(result.current.contentHorizontalPadding).toBe(32);
    expect(result.current.sectionVerticalSpacing).toBe(32);
  });
});

import { renderHook } from '@testing-library/react-native';
import { useBreakpoint } from '@/hooks/useBreakpoint';

// Mock Dimensions.get so responsive.ts's scale() computes base values against
// iPhone X width (375), matching our useWindowDimensions default. Must be
// mocked before any imports that load responsive.ts.
jest.mock('react-native/Libraries/Utilities/Dimensions', () => {
  const mock = {
    get: jest.fn(() => ({ width: 375, height: 812, scale: 2, fontScale: 1 })),
    addEventListener: jest.fn(() => ({ remove: jest.fn() })),
    removeEventListener: jest.fn(),
  };
  return { __esModule: true, default: mock };
});

// Mock useWindowDimensions at the module useBreakpoint.ts imports from RN.
// The RN index.js getter resolves it via:
//   require('./Libraries/Utilities/useWindowDimensions').default
jest.mock('react-native/Libraries/Utilities/useWindowDimensions', () => ({
  __esModule: true,
  default: jest.fn(() => ({ width: 375, height: 812, scale: 2, fontScale: 1 })),
}));

// Re-import to get the mock function reference
import useWindowDimensions from 'react-native/Libraries/Utilities/useWindowDimensions';
const mockUseWindowDimensions = useWindowDimensions as jest.Mock;

describe('useBreakpoint', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseWindowDimensions.mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });
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

    mockUseWindowDimensions.mockReturnValue({ width: 1024, height: 768, scale: 2, fontScale: 1 });
    rerender(undefined);

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

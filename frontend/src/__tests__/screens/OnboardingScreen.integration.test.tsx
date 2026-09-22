import React from 'react';
import { screen, fireEvent } from '@testing-library/react-native';
import OnboardingScreen from '@/screens/OnboardingScreen';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';

const mockNavigate = jest.fn();

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: jest.fn(() => ({ navigate: mockNavigate })),
  };
});

jest.mock('@/hooks/useBreakpoint', () => ({
  useBreakpoint: () => ({
    width: 375,
    height: 812,
    orientation: 'portrait',
    isTablet: false,
    isLargePhone: false,
    isSmallPhone: false,
    contentHorizontalPadding: 16,
    sectionVerticalSpacing: 24,
    cardsPerRow: 2,
  }),
}));

jest.mock('@/hooks/useDecryptedImage', () => ({
  __esModule: true,
  default: (src: string | null | undefined) => src ?? undefined,
}));

describe('OnboardingScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const renderScreen = () =>
    renderWithProviders(<OnboardingScreen />, {
      providerOverrides: {
        withNavigation: false,
      },
    });

  it('renders the StockLens branding', async () => {
    await renderScreen();
    expect(screen.getByText('StockLens')).toBeTruthy();
  });

  it('renders subtitle text', async () => {
    await renderScreen();
    expect(screen.getByText('Scan your Spending')).toBeTruthy();
    expect(screen.getByText('See your missed Investing')).toBeTruthy();
  });

  it('renders the Get Started button', async () => {
    await renderScreen();
    expect(screen.getByText("Let's Get Started")).toBeTruthy();
  });

  it('navigates to Login when Get Started is pressed', async () => {
    await renderScreen();
    await fireEvent.press(screen.getByText("Let's Get Started"));
    expect(mockNavigate).toHaveBeenCalledWith('Login');
  });
});

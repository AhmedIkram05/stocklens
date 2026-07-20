import React from 'react';
import { renderWithProviders } from '@/__tests__/utils';
import AppNavigator from '@/navigation/AppNavigator';

jest.mock('@/screens/HomeScreen', () => () => null);
jest.mock('@/screens/ScanScreen', () => () => null);
jest.mock('@/screens/SummaryScreen', () => () => null);
jest.mock('@/screens/SettingsScreen', () => () => null);
jest.mock('@/screens/LoginScreen', () => () => null);
jest.mock('@/screens/SignUpScreen', () => () => null);
jest.mock('@/screens/ReceiptDetailsScreen', () => () => null);
jest.mock('@/screens/OnboardingScreen', () => () => null);
jest.mock('@/screens/LockScreen', () => () => null);
jest.mock('@/screens/portfolio/PortfolioListScreen', () => () => null);
jest.mock('@/screens/portfolio/PortfolioDetailScreen', () => () => null);
jest.mock('@/screens/portfolio/CreatePortfolioScreen', () => () => null);
jest.mock('@/screens/portfolio/DepositScreen', () => () => null);
jest.mock('@/screens/portfolio/TradeScreen', () => () => null);
jest.mock('@/screens/portfolio/BenchmarkScreen', () => () => null);

jest.mock('@react-navigation/stack', () => {
  const Screen = ({ component: Component }: any) => (Component ? <Component /> : null);
  const Navigator = ({ children }: any) => children;
  return {
    createStackNavigator: () => ({ Navigator, Screen }),
    CardStyleInterpolators: { forHorizontalIOS: {} },
  };
});

jest.mock('@react-navigation/bottom-tabs', () => {
  const Screen = ({ component: Component }: any) => (Component ? <Component /> : null);
  const Navigator = ({ children }: any) => children;
  return {
    createBottomTabNavigator: () => ({ Navigator, Screen }),
  };
});

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    NavigationContainer: ({ children }: any) => children,
  };
});

describe('AppNavigator', () => {
  it('shows loading indicator when auth is loading', () => {
    const { getByTestId } = renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: { loading: true },
      },
    });
    expect(getByTestId('activity-indicator')).toBeTruthy();
  });

  it('does not show loading indicator when not loading', () => {
    const { queryByTestId } = renderWithProviders(<AppNavigator />, {
      providerOverrides: { withNavigation: false },
    });
    expect(queryByTestId('activity-indicator')).toBeNull();
  });

  it('calls unlockWithDeviceAuth when user exists and is locked', () => {
    const unlockMock = jest.fn().mockResolvedValue(true);
    renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          user: {
            id: 'test-user',
            email: 'test@test.com',
            display_name: 'Test',
            first_name: 'Test',
            last_name: 'User',
            created_at: '2024-01-01',
            updated_at: '2024-01-01',
          } as any,
          locked: true,
          unlockWithDeviceAuth: unlockMock,
          loading: false,
        },
      },
    });
    expect(unlockMock).toHaveBeenCalledTimes(1);
  });

  it('does not call unlockWithDeviceAuth when user is null', () => {
    const unlockMock = jest.fn().mockResolvedValue(true);
    renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          user: null,
          locked: true,
          unlockWithDeviceAuth: unlockMock,
          loading: false,
        },
      },
    });
    expect(unlockMock).not.toHaveBeenCalled();
  });

  it('does not call unlockWithDeviceAuth when not locked', () => {
    const unlockMock = jest.fn().mockResolvedValue(true);
    renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          user: { id: 'test-user' } as any,
          locked: false,
          unlockWithDeviceAuth: unlockMock,
          loading: false,
        },
      },
    });
    expect(unlockMock).not.toHaveBeenCalled();
  });

  it('renders without crash when user is authenticated and not locked', () => {
    const { queryByTestId } = renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: {
          user: { id: 'test-user' } as any,
          locked: false,
          loading: false,
        },
      },
    });
    expect(queryByTestId('activity-indicator')).toBeNull();
  });

  it('renders without crash when no user (auth screens)', () => {
    const { queryByTestId } = renderWithProviders(<AppNavigator />, {
      providerOverrides: {
        withNavigation: false,
        authValue: { user: null, loading: false, locked: false },
      },
    });
    expect(queryByTestId('activity-indicator')).toBeNull();
  });
});

/**
 * Comprehensive tests for `AppNavigator`.
 * Tests loading states, authentication flows, and lock/unlock behavior.
 */

import AppNavigator from '@/navigation/AppNavigator';
import { renderWithProviders } from '@/__tests__/utils/renderWithProviders';
import { useAuth } from '@/contexts/AuthContext';

jest.mock('@/contexts/AuthContext', () => {
  return {
    useAuth: jest.fn(),
    AuthContext: {
      Provider: ({ children }: { children?: React.ReactNode }) => children,
    },
  };
});

const mockedUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

describe('AppNavigator', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // Helper to render without wrapping in NavigationContainer (AppNavigator has its own)
  const renderNavigator = (overrides?: Parameters<typeof renderWithProviders>[1]) =>
    renderWithProviders(<AppNavigator />, {
      providerOverrides: { withNavigation: false, ...overrides?.providerOverrides },
      ...overrides,
    });

  it('shows loading indicator when auth is loading', () => {
    mockedUseAuth.mockReturnValue({
      loading: true,
      user: null,
      userProfile: null,
      locked: false,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth: jest.fn(),
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    const { getByTestId } = renderNavigator();
    expect(getByTestId('activity-indicator')).toBeTruthy();
  });

  it('shows onboarding screen when not authenticated', () => {
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: null,
      userProfile: null,
      locked: false,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth: jest.fn(),
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    const { getByText } = renderNavigator();
    // When not authenticated, we should see the onboarding/splash screen
    expect(() => getByText("Let's Get Started")).not.toThrow();
  });

  it('shows lock screen when authenticated but locked', () => {
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: { uid: 'test-user' } as any,
      userProfile: null as any,
      locked: true,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth: jest.fn().mockResolvedValue(undefined),
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    const { getByText } = renderNavigator();
    // LockScreen should be visible - it shows "Locked" as the title
    expect(getByText('Locked')).toBeTruthy();
  });

  it('shows main tabs when authenticated and unlocked', () => {
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: { uid: 'test-user' } as any,
      userProfile: null as any,
      locked: false,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth: jest.fn(),
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    // Mock the navigation containers to avoid complex nesting
    const { getByText } = renderNavigator();
    // Should show one of the tab icons or screen titles
    // We'll check for a common element that should be visible
    expect(() => getByText('Dashboard')).not.toThrow();
  });

  it('attempts to unlock with device auth when authenticated and locked on mount', () => {
    const unlockWithDeviceAuth = jest.fn();
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: { uid: 'test-user' } as any,
      userProfile: null as any,
      locked: true,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth,
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    renderNavigator();

    // The useEffect should have called unlockWithDeviceAuth
    expect(unlockWithDeviceAuth).toHaveBeenCalled();
  });

  it('does not attempt to unlock when not locked', () => {
    const unlockWithDeviceAct = jest.fn();
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: { uid: 'test-user' } as any,
      userProfile: null as any,
      locked: false,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth: unlockWithDeviceAct,
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    renderNavigator();

    // Should not call unlock when not locked
    expect(unlockWithDeviceAct).not.toHaveBeenCalled();
  });

  it('does not attempt to unlock when not authenticated', () => {
    const unlockWithDeviceAuth = jest.fn();
    mockedUseAuth.mockReturnValue({
      loading: false,
      user: null as any,
      userProfile: null as any,
      locked: false,
      signOutUser: jest.fn(),
      unlockWithDeviceAuth,
      unlockWithCredentials: jest.fn(),
      startLockGrace: jest.fn(),
      refreshUser: jest.fn(),
    });

    renderNavigator();

    // Should not call unlock when no user
    expect(unlockWithDeviceAuth).not.toHaveBeenCalled();
  });
});

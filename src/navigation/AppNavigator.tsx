/**
 * AppNavigator
 *
 * Root navigation (stack + bottom tabs) with auth and lock flow handling.
 */

import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator, CardStyleInterpolators } from '@react-navigation/stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import React from 'react';
import { View, ActivityIndicator, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import * as Haptics from 'expo-haptics';

import { useTheme } from '../contexts/ThemeContext';

import HomeScreen from '../screens/HomeScreen';
import ScanScreen from '../screens/ScanScreen';
import AnalysisScreen from '../screens/SummaryScreen';
import ProfileScreen from '../screens/SettingsScreen';
import LoginScreen from '../screens/LoginScreen';
import SignUpScreen from '../screens/SignUpScreen';
import ReceiptDetailsScreen from '../screens/ReceiptDetailsScreen';
import SplashScreen from '../screens/OnboardingScreen';
import { useAuth } from '../contexts/AuthContext';
import LockScreen from '../screens/LockScreen';
import PortfolioListScreen from '../screens/portfolio/PortfolioListScreen';
import PortfolioDetailScreen from '../screens/portfolio/PortfolioDetailScreen';
import CreatePortfolioScreen from '../screens/portfolio/CreatePortfolioScreen';
import DepositScreen from '../screens/portfolio/DepositScreen';
import TradeScreen from '../screens/portfolio/TradeScreen';
import BenchmarkScreen from '../screens/portfolio/BenchmarkScreen';

/** Root stack navigation parameter list - defines all stack screens and their params */
export type RootStackParamList = {
  /** Onboarding/splash screen shown before authentication */
  Splash: undefined;
  /** Login screen for existing users */
  Login: undefined;
  /** Registration screen for new users */
  SignUp: undefined;
  /** Device lock screen shown when app is locked */
  Lock: undefined;
  /** Main bottom tab navigator (post-auth) */
  MainTabs: undefined;
  /** Calculator screen (future feature, currently unused) */
  Calculator: undefined;
  /** Receipt details modal with projection calculator */
  ReceiptDetails: {
    receiptId: string;
    totalAmount: number;
    date: string;
    image?: string;
  };
};

/** Portfolio stack navigation parameter list - defines all portfolio screens */
export type PortfolioStackParamList = {
  PortfolioList: undefined;
  PortfolioDetail: { portfolioId: number; portfolioName?: string };
  CreatePortfolio: undefined;
  Deposit: { portfolioId: number };
  Trade: { portfolioId: number; mode: 'buy' | 'sell' };
  Benchmark: { portfolioId: number; benchmarkTicker?: string };
};

/** Bottom tab navigation parameter list - defines all tab screens */
export type MainTabParamList = {
  /** Home/dashboard tab showing receipt history */
  Dashboard: undefined;
  /** Portfolio tab for managing investment portfolios */
  Portfolio: undefined;
  /** Scan tab with camera for capturing receipts */
  Scan: undefined;
  /** Summary tab with analytics and insights */
  Summary: undefined;
  /** Settings tab with user preferences */
  Settings: undefined;
};

const Stack = createStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();
const PortfolioStack = createStackNavigator<PortfolioStackParamList>();

/**
 * PortfolioStackNavigator
 *
 * Stack navigator for the Portfolio tab with 6 screens:
 * PortfolioList, PortfolioDetail, CreatePortfolio, Deposit, Trade, Benchmark.
 * Uses horizontal iOS slide transitions matching the root stack style.
 */
function PortfolioStackNavigator() {
  const { theme } = useTheme();

  return (
    <View style={{ flex: 1, backgroundColor: theme.background }}>
      <PortfolioStack.Navigator
        screenOptions={{
          headerShown: false,
          cardStyleInterpolator: CardStyleInterpolators.forHorizontalIOS,
          transitionSpec: {
            open: { animation: 'timing', config: { duration: 200 } },
            close: { animation: 'timing', config: { duration: 200 } },
          },
        }}
      >
        <PortfolioStack.Screen name="PortfolioList" component={PortfolioListScreen} />
        <PortfolioStack.Screen name="PortfolioDetail" component={PortfolioDetailScreen} />
        <PortfolioStack.Screen name="CreatePortfolio" component={CreatePortfolioScreen} />
        <PortfolioStack.Screen name="Deposit" component={DepositScreen} />
        <PortfolioStack.Screen name="Trade" component={TradeScreen} />
        <PortfolioStack.Screen name="Benchmark" component={BenchmarkScreen} />
      </PortfolioStack.Navigator>
    </View>
  );
}

/**
 * MainTabNavigator
 *
 * Bottom tab bar with 5 tabs: Dashboard, Portfolio, Scan, Summary, Settings.
 * Uses Ionicons for tab icons (filled when active, outlined when inactive).
 * Features:
 * - iOS: Native blur effect with translucent background
 * - Android: Material Design elevation and shadows
 * - Native haptic feedback on tab press (light impact)
 * - Theme-aware styling with platform-specific adjustments
 */
function MainTabNavigator() {
  const { theme, isDark } = useTheme();

  // Haptic feedback on tab press (iOS & Android)
  const handleTabPress = () => {
    if (Platform.OS === 'ios' || Platform.OS === 'android') {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }
  };

  return (
    <Tab.Navigator
      screenOptions={{
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.textSecondary,
        tabBarShowLabel: true,
        tabBarStyle: {
          position: 'absolute',
          borderTopWidth: 0,
          elevation: Platform.OS === 'android' ? 8 : 0,
          backgroundColor: Platform.OS === 'ios' ? 'transparent' : theme.surface,
          ...(Platform.OS === 'android' && {
            shadowColor: '#000',
            shadowOffset: { width: 0, height: -2 },
            shadowOpacity: 0.1,
            shadowRadius: 8,
          }),
        },
        tabBarBackground: () =>
          Platform.OS === 'ios' ? (
            <BlurView
              intensity={isDark ? 80 : 95}
              tint={isDark ? 'dark' : 'light'}
              style={{ flex: 1 }}
            >
              <SafeAreaView edges={['bottom']} style={{ flex: 1 }} />
            </BlurView>
          ) : (
            <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: theme.surface }} />
          ),
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '600',
        },
      }}
      screenListeners={{
        tabPress: handleTabPress,
      }}
    >
      <Tab.Screen
        name="Dashboard"
        component={HomeScreen}
        options={{
          title: 'Dashboard',
          tabBarLabel: 'Dashboard',
          headerShown: false,
          tabBarIcon: ({
            focused,
            color,
            size,
          }: {
            focused: boolean;
            color: string;
            size: number;
          }) => <Ionicons name={focused ? 'grid' : 'grid-outline'} size={size} color={color} />,
        }}
      />
      <Tab.Screen
        name="Portfolio"
        component={PortfolioStackNavigator}
        options={{
          title: 'Portfolio',
          tabBarLabel: 'Portfolio',
          headerShown: false,
          tabBarIcon: ({
            focused,
            color,
            size,
          }: {
            focused: boolean;
            color: string;
            size: number;
          }) => (
            <Ionicons
              name={focused ? 'briefcase' : 'briefcase-outline'}
              size={size}
              color={color}
            />
          ),
        }}
      />
      <Tab.Screen
        name="Scan"
        component={ScanScreen}
        options={{
          title: 'Scan Receipt',
          tabBarLabel: 'Scan',
          headerShown: false,
          tabBarIcon: ({
            focused,
            color,
            size,
          }: {
            focused: boolean;
            color: string;
            size: number;
          }) => <Ionicons name={focused ? 'camera' : 'camera-outline'} size={size} color={color} />,
        }}
      />
      <Tab.Screen
        name="Summary"
        component={AnalysisScreen}
        options={{
          title: 'Summary',
          tabBarLabel: 'Summary',
          headerShown: false,
          tabBarIcon: ({
            focused,
            color,
            size,
          }: {
            focused: boolean;
            color: string;
            size: number;
          }) => (
            <Ionicons
              name={focused ? 'bar-chart' : 'bar-chart-outline'}
              size={size}
              color={color}
            />
          ),
        }}
      />
      <Tab.Screen
        name="Settings"
        component={ProfileScreen}
        options={{
          title: 'Settings',
          tabBarLabel: 'Settings',
          headerShown: false,
          tabBarIcon: ({
            focused,
            color,
            size,
          }: {
            focused: boolean;
            color: string;
            size: number;
          }) => (
            <Ionicons name={focused ? 'settings' : 'settings-outline'} size={size} color={color} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

/**
 * AppNavigator (Root Navigator)
 *
 * Main navigation component wrapped in NavigationContainer.
 * Handles authentication state and conditional rendering:
 * - Loading: Shows ActivityIndicator
 * - Unauthenticated: Shows Splash → Login/SignUp flow
 * - Authenticated & Locked: Shows LockScreen (device passcode gate)
 * - Authenticated & Unlocked: Shows MainTabs + ReceiptDetails modal
 *
 * Auto-unlock behavior:
 * - When user is authenticated but locked, automatically attempts a device-auth unlock
 * - Uses useEffect to trigger unlock on mount if conditions are met
 *
 * Transition animations:
 * - Horizontal iOS-style slide transitions
 * - 200ms duration for smooth navigation
 */
export default function AppNavigator() {
  const { user, loading, locked, unlockWithDeviceAuth } = useAuth();
  const { theme } = useTheme();

  React.useEffect(() => {
    (async () => {
      try {
        if (!loading && user && locked) {
          unlockWithDeviceAuth();
        }
      } catch (err) {}
    })();
  }, [loading, user, locked]);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator testID="activity-indicator" size="large" color={theme.primary} />
      </View>
    );
  }
  return (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          cardStyleInterpolator: CardStyleInterpolators.forHorizontalIOS,
          transitionSpec: {
            open: { animation: 'timing', config: { duration: 200 } },
            close: { animation: 'timing', config: { duration: 200 } },
          },
        }}
      >
        {user ? (
          locked ? (
            <Stack.Screen name="Lock" component={LockScreen} />
          ) : (
            <>
              <Stack.Screen name="MainTabs" component={MainTabNavigator} />
              <Stack.Screen name="ReceiptDetails" component={ReceiptDetailsScreen} />
            </>
          )
        ) : (
          <>
            <Stack.Screen name="Splash" component={SplashScreen} />
            <Stack.Screen name="Login" component={LoginScreen} />
            <Stack.Screen name="SignUp" component={SignUpScreen} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

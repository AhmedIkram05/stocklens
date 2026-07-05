import { StatusBar } from 'expo-status-bar';
import AppNavigator from './src/navigation/AppNavigator';
import { AuthProvider } from './src/contexts/AuthContext';
import { ThemeProvider, useTheme } from './src/contexts/ThemeContext';

/**
 * App entrypoint.
 *
 * Provides `ThemeProvider` and `AuthProvider` around `AppNavigator`.
 */

/**
 * Internal app content.
 */
function AppContent() {
  const { isDark } = useTheme();

  return (
    <>
      <AppNavigator />
      <StatusBar style={isDark ? 'light' : 'dark'} />
    </>
  );
}

/**
 * Root App component.
 *
 * Wraps the app with `ThemeProvider` and `AuthProvider`.
 */
export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </ThemeProvider>
  );
}

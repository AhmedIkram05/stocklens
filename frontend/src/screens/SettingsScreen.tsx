/**
 * SettingsScreen
 *
 * User preferences and account management screen.
 */

import React, { useState, useCallback } from 'react';
import { View, Text, StyleSheet, Alert, Switch, ScrollView, RefreshControl } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import SettingRow from '../components/SettingRow';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import * as deviceAuth from '../hooks/useDeviceAuth';
import { receiptService } from '../services/receipts';
import { spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';

/** Settings screen. */
export default function SettingsScreen() {
  const { signOutUser } = useAuth();
  const { setMode, isDark, theme } = useTheme();
  const [deviceAuthEnabled, setDeviceAuthEnabled] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const { isSmallPhone, isTablet } = useBreakpoint();

  const handleSignOut = async () => {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign Out',
        style: 'destructive',
        onPress: async () => {
          try {
            await signOutUser();
          } catch (error) {
            Alert.alert('Error', 'Failed to sign out');
          }
        },
      },
    ]);
  };

  const loadDeviceAuth = useCallback(async () => {
    const mounted = true;
    try {
      // First check if device authentication is available on the device
      const available = await deviceAuth.isDeviceAuthAvailable();

      if (!available) {
        // If device auth not available, ensure toggle is OFF and disable the setting
        if (mounted) setDeviceAuthEnabled(false);
        await deviceAuth.setDeviceEnabled(false);
        return;
      }

      // If available, load the saved preference
      const enabled = await deviceAuth.isDeviceEnabled();
      if (mounted) setDeviceAuthEnabled(enabled);
    } catch (err) {
      if (mounted) setDeviceAuthEnabled(false);
    } finally {
      if (mounted) setRefreshing(false);
    }
  }, []);

  React.useEffect(() => {
    loadDeviceAuth();
  }, [loadDeviceAuth]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadDeviceAuth();
  }, [loadDeviceAuth]);

  const handleToggleDeviceAuth = async (val: boolean) => {
    if (!val) {
      // Disabling device auth - clear flag and credentials
      setDeviceAuthEnabled(false);
      try {
        await deviceAuth.setDeviceEnabled(false);
        await deviceAuth.clearDeviceCredentials();
      } catch (err) {}
      return;
    }

    // Enabling device auth - check availability first
    try {
      const available = await deviceAuth.isDeviceAuthAvailable();
      if (!available) {
        Alert.alert(
          'Device authentication unavailable',
          'Device authentication is not available or not configured. Ensure a device passcode or biometrics are set up in system settings.',
          [{ text: 'OK', onPress: () => setDeviceAuthEnabled(false) }],
        );
        setDeviceAuthEnabled(false);
        return;
      }

      // Verify with native device auth prompt
      const { success, error } = await deviceAuth.authenticateDevice(
        'Authenticate to enable device passcode login',
      );
      if (!success) {
        Alert.alert(
          'Authentication failed',
          error ||
            'Could not verify your identity. Try again or check your device security settings.',
          [{ text: 'OK', onPress: () => setDeviceAuthEnabled(false) }],
        );
        setDeviceAuthEnabled(false);
        return;
      }

      // Successfully authenticated - enable device login
      await deviceAuth.setDeviceEnabled(true);
      setDeviceAuthEnabled(true);
      Alert.alert(
        'Enabled',
        'Device passcode login enabled. You can now unlock the app with your device credentials.',
      );
    } catch (err) {
      Alert.alert('Error', 'Failed to enable device login. Please try again.');
      setDeviceAuthEnabled(false);
    }
  };

  const handleToggleDarkMode = (value: boolean) => {
    setMode(value ? 'dark' : 'light');
  };

  const handleClearData = () => {
    Alert.alert(
      'Clear All Data',
      'Are you sure you want to delete all scanned receipts stored on this device? This action cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await receiptService.deleteAll();
              Alert.alert(
                'Data cleared',
                'All scanned receipts stored on this device have been permanently deleted.',
              );
            } catch (err: any) {
              Alert.alert(
                'Error',
                err?.message || 'Failed to clear scanned data. Please try again later.',
              );
            }
          },
        },
      ],
    );
  };
  return (
    <ScreenContainer>
      <ScrollView
        contentContainerStyle={[styles.scrollContent]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={theme.primary}
            colors={[theme.primary]}
          />
        }
      >
        <PageHeader>
          <View>
            <Text style={[styles.title, { color: theme.text }]}>Settings</Text>
          </View>
          <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
            Manage your preferences and security
          </Text>
        </PageHeader>

        <View
          style={[
            styles.section,
            isSmallPhone && styles.sectionCompact,
            isTablet && styles.sectionWide,
          ]}
        >
          <Text style={[styles.sectionLabel, { color: theme.textSecondary }]}>Security</Text>

          <SettingRow
            icon={deviceAuthEnabled ? 'lock-closed' : 'lock-open'}
            iconBgColor={theme.secondary}
            title="Device Passcode Unlock"
            subtitle="Secure login with your device credentials"
            right={
              <Switch
                value={deviceAuthEnabled}
                onValueChange={handleToggleDeviceAuth}
                trackColor={{ false: theme.border, true: theme.primary }}
                thumbColor="#ffffff"
              />
            }
          />

          <SettingRow
            icon="shield-checkmark"
            iconBgColor={theme.border}
            title="Secure Cloud Storage"
            subtitle="Data stored securely on AWS with encryption"
          />
        </View>

        <View
          style={[
            styles.section,
            isSmallPhone && styles.sectionCompact,
            isTablet && styles.sectionWide,
          ]}
        >
          <Text style={[styles.sectionLabel, { color: theme.textSecondary }]}>Preferences</Text>

          <SettingRow
            icon={'moon'}
            iconBgColor={theme.secondary}
            title="Dark Mode"
            subtitle="Reduce glare & save battery"
            right={
              <Switch
                value={isDark}
                onValueChange={handleToggleDarkMode}
                trackColor={{ false: theme.border, true: theme.primary }}
                thumbColor="#ffffff"
              />
            }
          />
        </View>

        <View
          style={[
            styles.section,
            isSmallPhone && styles.sectionCompact,
            isTablet && styles.sectionWide,
          ]}
        >
          <Text style={[styles.sectionLabel, { color: theme.textSecondary }]}>Account</Text>

          <SettingRow
            icon="log-out"
            iconBgColor={theme.error}
            title="Log Out"
            subtitle="Return to login screen"
            destructive
            onPress={handleSignOut}
            right={<Text style={[styles.arrow, { color: theme.textSecondary }]}>›</Text>}
          />
        </View>

        <View
          style={[
            styles.section,
            isSmallPhone && styles.sectionCompact,
            isTablet && styles.sectionWide,
          ]}
        >
          <Text style={[styles.sectionLabel, { color: theme.textSecondary }]}>Data Management</Text>

          <SettingRow
            icon="trash"
            iconBgColor={theme.error}
            title="Clear All Data"
            subtitle="Delete all scanned receipts"
            destructive
            onPress={handleClearData}
            right={<Text style={[styles.arrow, { color: theme.textSecondary }]}>›</Text>}
          />
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  scrollContent: {
    paddingBottom: spacing.xxl,
  },
  title: {
    ...typography.pageTitle,
    marginBottom: spacing.sm,
  },
  subtitle: {
    ...typography.pageSubtitle,
  },
  section: {
    paddingVertical: spacing.md,
  },
  sectionCompact: {
    paddingVertical: spacing.sm,
  },
  sectionWide: {
    paddingVertical: spacing.lg,
  },
  sectionLabel: {
    ...typography.overline,
    marginBottom: spacing.md,
  },
  arrow: {
    ...typography.bodyStrong,
  },
});

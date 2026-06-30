/**
 * LockScreen
 *
 * Device-passcode unlock screen shown when returning from background.
 */

import React, { useState } from 'react';
import { View, Text, StyleSheet, Alert, TouchableOpacity } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import FormInput from '../components/FormInput';
import PrimaryButton from '../components/PrimaryButton';
import SecondaryButton from '../components/SecondaryButton';
import { useAuth } from '../contexts/AuthContext';
import { useBreakpoint } from '../hooks/useBreakpoint';
import PageHeader from '../components/PageHeader';
import Logo from '../components/Logo';
import { authService } from '../services/auth';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useTheme } from '../contexts/ThemeContext';

/** Lock screen for device/passcode unlock. */
export default function LockScreen() {
  const { unlockWithDeviceAuth, unlockWithCredentials, user, userProfile } = useAuth();
  const { contentHorizontalPadding, sectionVerticalSpacing } = useBreakpoint();
  const { theme } = useTheme();
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const accountEmail = (user && user.email) || userProfile?.email || '';
  const [forgotDisabled, setForgotDisabled] = useState(false);
  const handleForgotFromLock = async () => {
    if (forgotDisabled) return;
    if (!accountEmail) {
      Alert.alert(
        'No Account',
        'No account email available. Please sign in again from the Sign In screen.',
      );
      return;
    }
    Alert.alert('Send Reset Link?', `Send a password reset link to ${accountEmail}?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Send',
        onPress: async () => {
          setForgotDisabled(true);
          try {
            await authService.forgotPassword(accountEmail);
            Alert.alert(
              'Password Reset',
              "If an account exists for that email, we'll send a reset link. Check your inbox and spam folder.",
            );
          } catch (err: any) {
            Alert.alert(
              'Error',
              `Could not send reset email. ${err?.message || 'Try again later.'}`,
            );
          } finally {
            setTimeout(() => setForgotDisabled(false), 30000);
          }
        },
      },
    ]);
  };

  const handleDeviceAuth = async () => {
    setLoading(true);
    try {
      const ok = await unlockWithDeviceAuth();
      if (!ok) {
        Alert.alert(
          'Unlock Failed',
          'Could not unlock using your device credentials. Please try again or use your password.',
        );
      }
    } catch (err) {
      Alert.alert('Error', 'Device authentication failed. Please use your password.');
    } finally {
      setLoading(false);
    }
  };

  const handleManual = async () => {
    const emailAddr = user?.email || userProfile?.email;
    if (!emailAddr) {
      Alert.alert(
        'No Account',
        'No account email available. Please sign in again from the Sign In screen.',
      );
      return;
    }
    if (!password) {
      Alert.alert('Missing Password', 'Please enter your account password');
      return;
    }
    setLoading(true);
    const ok = await unlockWithCredentials(emailAddr, password);
    if (!ok) {
      Alert.alert('Unlock Failed', 'Invalid password. Please try again.');
    }
    setLoading(false);
  };

  return (
    <ScreenContainer
      contentStyle={{
        paddingHorizontal: contentHorizontalPadding,
        paddingVertical: sectionVerticalSpacing,
      }}
    >
      <View style={[styles.inner, { paddingHorizontal: 0 }]}>
        <View style={styles.logoContainer}>
          <Logo />
        </View>

        <PageHeader>
          <Text style={[styles.title, { color: theme.text }]}>Locked</Text>
          <Text style={[styles.subtitle, { color: theme.textSecondary }]}>Unlock to continue</Text>
          {accountEmail ? (
            <Text
              style={[styles.accountEmail, { color: theme.textSecondary }]}
              numberOfLines={1}
              ellipsizeMode="middle"
            >
              {accountEmail}
            </Text>
          ) : null}
        </PageHeader>

        <SecondaryButton
          onPress={handleDeviceAuth}
          disabled={loading}
          accessibilityLabel="Unlock with device passcode"
          style={styles.deviceButton}
          textStyle={{ color: brandColors.white }}
        >
          {loading ? 'Unlocking…' : 'Unlock with Device Passcode'}
        </SecondaryButton>

        <Text style={[styles.or, { color: theme.textSecondary }]}>
          Or enter your account password
        </Text>

        <FormInput
          placeholder="Password"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoCapitalize="none"
        />

        <PrimaryButton
          style={styles.unlockButton}
          onPress={handleManual}
          disabled={loading}
          accessibilityLabel="Unlock with password"
        >
          Unlock
        </PrimaryButton>
        <TouchableOpacity
          onPress={handleForgotFromLock}
          disabled={forgotDisabled}
          style={styles.forgotContainer}
          accessibilityLabel="Forgot password"
        >
          <Text style={[styles.forgotText, forgotDisabled && { opacity: 0.5 }]}>
            Forgot password?
          </Text>
        </TouchableOpacity>
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  inner: { padding: spacing.lg, flex: 1, justifyContent: 'center' },
  title: { ...typography.pageTitle, marginBottom: spacing.sm, textAlign: 'center' },
  subtitle: { ...typography.body, marginBottom: spacing.lg, textAlign: 'center' },
  logoContainer: {
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  deviceButton: {
    backgroundColor: brandColors.green,
    padding: spacing.md,
    borderRadius: radii.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  or: { textAlign: 'center', marginVertical: spacing.md },
  unlockButton: {
    backgroundColor: brandColors.blue,
    padding: spacing.md,
    borderRadius: radii.md,
    alignItems: 'center',
  },
  forgotContainer: { alignItems: 'center', marginTop: spacing.sm, marginBottom: spacing.md },
  forgotText: { ...typography.body, color: brandColors.blue },
  accountEmail: { ...typography.body, marginTop: spacing.xs, textAlign: 'center' },
});

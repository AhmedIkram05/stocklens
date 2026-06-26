/**
 * LoginScreen
 *
 * Sign-in screen for existing users.
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Alert,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import ScreenContainer from '../components/ScreenContainer';
import PageHeader from '../components/PageHeader';
import PrimaryButton from '../components/PrimaryButton';
import Logo from '../components/Logo';
import FormInput from '../components/FormInput';
import AuthFooter from '../components/AuthFooter';
import { authService, SignInData } from '../services/authService';
import { promptEnableDeviceAuth } from '../utils/deviceAuthPrompt';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';

/** Login screen. */
export default function LoginScreen() {
  const navigation = useNavigation();
  const { contentHorizontalPadding, isSmallPhone, sectionVerticalSpacing, isTablet, orientation } =
    useBreakpoint();
  const { startLockGrace } = useAuth();
  const { theme } = useTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = async () => {
    if (!email || !password) {
      Alert.alert('Missing information', 'Please enter both your email and password to continue.');
      return;
    }

    try {
      const signInData: SignInData = { email, password };
      await authService.signIn(signInData);

      startLockGrace();

      try {
        await promptEnableDeviceAuth(email, password);
      } catch (e) {}
    } catch (error: any) {
      let errorMessage = 'An error occurred signing in. Please try again.';
      if (error.code === 'auth/user-not-found') {
        errorMessage = 'No account found for that email address.';
      } else if (error.code === 'auth/wrong-password') {
        errorMessage = 'Incorrect password. Please try again.';
      } else if (error.code === 'auth/invalid-email') {
        errorMessage = 'That does not look like a valid email address.';
      }
      Alert.alert('Sign In Error', errorMessage);
    }
  };

  const handleSignUp = () => {
    navigation.navigate('SignUp' as never);
  };

  const [forgotDisabled, setForgotDisabled] = useState(false);
  const handleForgot = async () => {
    if (forgotDisabled) return;
    const target = email.trim();
    if (!target) {
      Alert.alert(
        'Email required',
        'Enter the email address for your account to receive a password reset link.',
      );
      return;
    }
    setForgotDisabled(true);
    try {
      const mod = await import('../services/authService');
      if (!mod || !mod.authService || typeof mod.authService.sendPasswordReset !== 'function') {
        throw new Error('authService.sendPasswordReset is not available');
      }
      await mod.authService.sendPasswordReset(target);
      Alert.alert(
        'Password reset',
        "If an account exists for that email, we'll send a reset link. Check your inbox (and spam) for the message.",
      );
    } catch (err: any) {
      Alert.alert(
        'Error',
        `Could not send reset email. ${err?.code || ''} ${err?.message || 'Try again later.'}`,
      );
    } finally {
      setTimeout(() => setForgotDisabled(false), 30000);
    }
  };

  return (
    <ScreenContainer
      contentStyle={{
        paddingHorizontal: contentHorizontalPadding,
        paddingVertical: sectionVerticalSpacing,
      }}
    >
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          showsHorizontalScrollIndicator={false}
        >
          <View style={styles.content}>
            <View style={styles.logoContainer}>
              <Logo />
            </View>

            <PageHeader>
              <View style={[styles.titleContainer, isSmallPhone && styles.titleContainerCompact]}>
                {(() => {
                  const titleMarginTop = isSmallPhone
                    ? spacing.lg
                    : isTablet
                      ? orientation === 'landscape'
                        ? spacing.md
                        : spacing.lg
                      : spacing.xl;
                  const titleMarginBottom = isSmallPhone
                    ? spacing.xs
                    : isTablet
                      ? spacing.sm
                      : spacing.md;
                  return (
                    <Text
                      style={[
                        styles.title,
                        {
                          color: theme.text,
                          marginTop: titleMarginTop,
                          marginBottom: titleMarginBottom,
                        },
                      ]}
                    >
                      Welcome to Stock
                      <Text style={[styles.titleLens, { color: theme.primary }]}>Lens</Text>
                    </Text>
                  );
                })()}
              </View>
              <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
                Scan your spending{'\n'}See your missed investing
              </Text>
            </PageHeader>

            <View
              style={[
                styles.formContainer,
                isSmallPhone && styles.formContainerCompact,
                // On tablet landscape, push form content down so inputs sit lower on screen
                isTablet && orientation === 'landscape'
                  ? { justifyContent: 'flex-start', paddingTop: spacing.xl }
                  : undefined,
              ]}
            >
              <FormInput
                placeholder="Email"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
              />

              <FormInput
                placeholder="Password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                showPasswordToggle
              />

              <PrimaryButton
                onPress={handleLogin}
                style={styles.loginButton}
                textStyle={styles.loginButtonText}
                accessibilityLabel="Login"
              >
                Login
              </PrimaryButton>

              <TouchableOpacity
                onPress={handleForgot}
                disabled={forgotDisabled}
                style={styles.forgotContainer}
                accessibilityLabel="Forgot password"
              >
                <Text style={[styles.forgotText, forgotDisabled && { opacity: 0.5 }]}>
                  Forgot password?
                </Text>
              </TouchableOpacity>

              <AuthFooter
                prompt={"Don't have an account?"}
                actionText="Sign Up"
                onPress={handleSignUp}
                style={styles.signUpContainer}
              />
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  content: {
    flex: 1,
    justifyContent: 'space-between',
  },
  formContainerCompact: {
    paddingBottom: spacing.lg,
  },
  logoContainer: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  titleContainer: {
    alignItems: 'center',
  },
  titleContainerCompact: {
    marginBottom: spacing.sm,
  },
  title: {
    ...typography.pageTitle,
    textAlign: 'center',
  },
  titleLens: {
    ...typography.pageTitle,
    textAlign: 'center',
  },
  subtitle: {
    ...typography.pageSubtitle,
    textAlign: 'center',
    paddingBottom: spacing.xl,
  },
  formContainer: {
    flex: 1,
    justifyContent: 'center',
  },
  loginButton: {
    backgroundColor: brandColors.green,
    borderRadius: radii.md,
    padding: spacing.md,
    alignItems: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.xl,
  },
  loginButtonText: {
    ...typography.button,
  },
  signUpContainer: {
    alignItems: 'center',
  },
  forgotContainer: {
    alignItems: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  forgotText: {
    ...typography.body,
    color: brandColors.blue,
  },
});

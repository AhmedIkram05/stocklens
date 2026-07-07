/**
 * SignUpScreen
 *
 * Registration screen for new users.
 */

import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Alert, ScrollView } from 'react-native';
import ScreenContainer from '../components/ScreenContainer';
import FormInput from '../components/FormInput';
import PrimaryButton from '../components/PrimaryButton';
import AuthFooter from '../components/AuthFooter';
import { useNavigation } from '@react-navigation/native';
import IconButton from '../components/IconButton';
import { authService } from '../services/auth';
import { ApiError } from '../services/api';
import { promptEnableDeviceAuth } from '../utils/deviceAuthPrompt';
import { useAuth } from '../contexts/AuthContext';
import { brandColors } from '../contexts/ThemeContext';
import { radii, spacing, typography } from '../styles/theme';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useTheme } from '../contexts/ThemeContext';

/** Sign-up screen. */
export default function SignUpScreen() {
  const navigation = useNavigation();
  const { contentHorizontalPadding, sectionVerticalSpacing, isSmallPhone } = useBreakpoint();
  const { startLockGrace, refreshUser } = useAuth();
  const { theme } = useTheme();
  const [firstName, setFirstName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isFormValid, setIsFormValid] = useState(false);

  useEffect(() => {
    const isValid =
      firstName.trim().length > 0 &&
      email.trim().length > 0 &&
      password.length >= 6 &&
      confirmPassword.length >= 6 &&
      password === confirmPassword;

    setIsFormValid(isValid);
  }, [firstName, email, password, confirmPassword]);

  const handleSignUp = async () => {
    if (!isFormValid) {
      Alert.alert('Error', 'Please fill in all fields correctly');
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      Alert.alert('Error', 'Please enter a valid email address');
      return;
    }

    try {
      await authService.signUp({ fullName: firstName, email, password });

      await refreshUser();
      startLockGrace();

      try {
        await promptEnableDeviceAuth(email, password);
      } catch (e) {}
    } catch (error: unknown) {
      let errorMessage = 'An error occurred during sign up';
      if (__DEV__) console.error('signup error:', error);
      if (error instanceof ApiError) {
        if (error.status === 409) {
          errorMessage = 'An account with this email already exists';
        } else if (error.status === 422) {
          errorMessage = 'Please check your input and try again.';
        } else {
          errorMessage = error.message;
        }
      }
      Alert.alert('Sign Up Error', errorMessage);
    }
  };

  const handleLogin = () => {
    navigation.navigate('Login' as never);
  };

  const handleBack = () => {
    if (navigation.canGoBack()) {
      navigation.goBack();
    } else {
      navigation.navigate('Login' as never);
    }
  };

  return (
    <ScreenContainer
      contentStyle={{
        paddingHorizontal: contentHorizontalPadding,
        paddingVertical: sectionVerticalSpacing,
      }}
    >
      <ScrollView
        style={styles.scrollView}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={[styles.content, { paddingBottom: sectionVerticalSpacing }]}
      >
        <View style={[styles.headerRow, isSmallPhone && styles.headerRowCompact]}>
          <IconButton name="chevron-back" onPress={handleBack} accessibilityLabel="Go back" />
        </View>

        <View style={[styles.titleContainer, isSmallPhone && styles.titleContainerCompact]}>
          <Text style={[styles.title, { color: theme.text }]}>Create your account</Text>
          <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
            Start discovering your missed investment opportunities
          </Text>
        </View>

        <View style={[styles.formContainer, isSmallPhone && styles.formContainerCompact]}>
          <FormInput
            placeholder="First Name"
            value={firstName}
            onChangeText={setFirstName}
            autoCapitalize="words"
            autoCorrect={false}
          />

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

          <FormInput
            placeholder="Confirm Password"
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            showPasswordToggle
          />

          <PrimaryButton
            onPress={handleSignUp}
            style={[styles.createAccountButton, !isFormValid && { backgroundColor: theme.border }]}
            disabled={!isFormValid}
            accessibilityLabel="Create account"
          >
            Create Account
          </PrimaryButton>

          <AuthFooter
            prompt="Already have an account?"
            actionText="Login"
            onPress={handleLogin}
            style={styles.loginContainer}
          />
        </View>
      </ScrollView>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  scrollView: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    paddingBottom: spacing.xxl,
  },
  titleContainer: {
    alignItems: 'center',
    marginBottom: spacing.xxl,
  },
  titleContainerCompact: {
    marginBottom: spacing.xl,
  },
  title: {
    ...typography.pageTitle,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  subtitle: {
    ...typography.pageSubtitle,
    textAlign: 'center',
  },
  formContainer: {
    flex: 1,
  },
  formContainerCompact: {
    paddingBottom: spacing.lg,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'flex-start',
    marginTop: spacing.md,
    marginBottom: spacing.lg,
  },
  headerRowCompact: {
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  createAccountButton: {
    backgroundColor: brandColors.green,
    borderRadius: radii.md,
    padding: spacing.md,
    alignItems: 'center',
    marginTop: spacing.lg,
    marginBottom: spacing.xl,
  },
  loginContainer: {
    alignItems: 'center',
  },
});

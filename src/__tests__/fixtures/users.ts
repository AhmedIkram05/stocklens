/**
 * Test fixtures for user profiles.
 * Provides `createUserProfile` and `sampleUser` used across auth and settings tests.
 */

import { UserProfile } from '@/contexts/AuthContext';

const userSequence = 1;

export const createUserProfile = (overrides: Partial<UserProfile> = {}): UserProfile => {
  const now = new Date().toISOString();

  const base: UserProfile = {
    id: overrides.id ?? `test-id-${userSequence}`,
    uid: overrides.uid ?? `test-uid-${userSequence}`,
    display_name: overrides.display_name ?? overrides.first_name ?? 'TestUser',
    first_name: overrides.first_name ?? overrides.display_name ?? 'TestUser',
    email: overrides.email ?? 'user@example.com',
    created_at: overrides.created_at ?? now,
    updated_at: overrides.updated_at ?? now,
  };

  return { ...base, ...overrides };
};

export const sampleUser = createUserProfile();

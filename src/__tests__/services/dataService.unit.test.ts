jest.mock('@/services/database', () => ({
  databaseService: {
    executeNonQuery: jest.fn(),
    executeQuery: jest.fn(),
  },
}));

jest.mock('@/services/eventBus', () => ({
  emit: jest.fn(),
}));

// Mock crypto helpers so encryption is deterministic in tests
jest.mock('@/utils/crypto', () => ({
  isEncryptedPayload: jest.fn((s: any) => typeof s === 'string' && s.startsWith('enc:')),
  encryptString: jest.fn(async (s: string) => `enc:${s}`),
  decryptString: jest.fn(async (s: string) =>
    typeof s === 'string' && s.startsWith('enc:') ? s.slice(4) : s,
  ),
}));

// Mock file-level encryption to avoid touching filesystem
jest.mock('@/utils/fileCrypto', () => ({
  encryptImageFile: jest.fn(async (uri: string) => `enc-${uri}`),
  decryptImageToTemp: jest.fn(async (uri: string) =>
    typeof uri === 'string' && uri.startsWith('enc-') ? uri.replace('enc-', 'tmp-') : uri,
  ),
}));

// Mock key manager to return a stable key
jest.mock('@/services/keyManager', () => ({
  getOrCreateKey: jest.fn(async () => 'test-key'),
}));

import { databaseService } from '@/services/database';
import { emit } from '@/services/eventBus';
import { receiptService, settingsService, userService } from '@/services/dataService';
import { createReceipt, createUserProfile } from '../fixtures';

/**
 * Tests for `dataService` (receipt/user/settings persistence).
 * Exercises receipt CRUD, settings upsert, user upsert with UNIQUE handling,
 * and event emissions on data changes.
 */

const mockedDb = databaseService as jest.Mocked<typeof databaseService>;
const mockedEmit = emit as jest.MockedFunction<typeof emit>;

describe('receiptService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('creates receipts with default values and returns insert id', async () => {
    mockedDb.executeNonQuery.mockResolvedValueOnce(42);

    const receiptData = createReceipt({
      user_id: 'uid-123',
      image_uri: 'file:///foo.jpg',
      total_amount: 12.5,
      ocr_data: '£12.50',
    });

    const id = await receiptService.create({
      user_id: receiptData.user_id,
      image_uri: receiptData.image_uri,
      total_amount: receiptData.total_amount,
      ocr_data: receiptData.ocr_data,
    });

    expect(id).toBe(42);
    expect(mockedDb.executeNonQuery).toHaveBeenCalledWith(
      expect.stringContaining('INSERT INTO receipts'),
      expect.arrayContaining(['uid-123']),
    );
  });

  it('updates only provided fields', async () => {
    await receiptService.update(7, { total_amount: 99.9 });
    expect(mockedDb.executeNonQuery).toHaveBeenCalledWith(
      expect.stringContaining('UPDATE receipts SET total_amount = ?'),
      ['enc:99.9', 7],
    );
  });

  it('deletes all receipts for a user and emits event', async () => {
    await receiptService.deleteAll('uid-abc');
    expect(mockedDb.executeNonQuery).toHaveBeenCalledWith(
      'DELETE FROM receipts WHERE user_id = ?',
      ['uid-abc'],
    );
    expect(mockedEmit).toHaveBeenCalledWith('receipts-changed', { userId: 'uid-abc' });
  });
});

describe('settingsService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('upserts settings with defaults when fields missing', async () => {
    await settingsService.upsert({ user_id: 'uid-settings' } as any);
    expect(mockedDb.executeNonQuery).toHaveBeenCalledWith(
      expect.stringContaining('INSERT OR REPLACE INTO user_settings'),
      ['uid-settings', 'enc:light', 0],
    );
  });
});

describe('userService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('upserts user profiles via executeNonQuery', async () => {
    mockedDb.executeNonQuery.mockResolvedValueOnce(1);

    const user = createUserProfile({ uid: 'uid', first_name: 'Alice', email: 'alice@example.com' });

    const result = await userService.upsert(user.uid, user.first_name!, user.email!);

    expect(result).toBe(1);
    expect(mockedDb.executeNonQuery).toHaveBeenCalledTimes(1);
    expect(mockedDb.executeNonQuery.mock.calls[0][0]).toContain('INSERT INTO users');
  });

  it('handles UNIQUE email conflicts by updating existing rows', async () => {
    mockedDb.executeNonQuery.mockRejectedValueOnce(
      new Error('UNIQUE constraint failed: users.email'),
    );
    mockedDb.executeNonQuery.mockResolvedValueOnce(2);

    const user = createUserProfile({
      uid: 'uid-new',
      first_name: 'Bob',
      email: 'duplicate@example.com',
    });

    const result = await userService.upsert(user.uid, user.first_name!, user.email!);

    expect(result).toBe(2);
    expect(mockedDb.executeNonQuery.mock.calls[1][0]).toContain('UPDATE users');
  });
});

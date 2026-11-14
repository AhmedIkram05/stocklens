/**
 * Tests for `useDecryptedImage` (unit).
 * Verifies decryption, caching, error fallback, and unmount behaviour.
 */

import { renderHook, waitFor } from '@testing-library/react-native';
import useDecryptedImage from '@/hooks/useDecryptedImage';

jest.mock('@/utils/fileCrypto', () => ({
  __esModule: true,
  default: {
    decryptImageToTemp: jest.fn(),
  },
}));

const mockedDecrypt = jest.requireMock('@/utils/fileCrypto').default
  .decryptImageToTemp as jest.Mock;

describe('useDecryptedImage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns undefined when no src provided', async () => {
    const { result } = await renderHook(() => useDecryptedImage(null));
    expect(result.current).toBeUndefined();
  });

  it('returns undefined when src is undefined', async () => {
    const { result } = await renderHook(() => useDecryptedImage(undefined));
    expect(result.current).toBeUndefined();
  });

  it('decrypts image and returns temp path', async () => {
    mockedDecrypt.mockResolvedValue('file://tmp/decrypted.jpg');

    const { result } = await renderHook(() => useDecryptedImage('file://enc-1.enc'));

    await waitFor(() => {
      expect(result.current).toBe('file://tmp/decrypted.jpg');
    });
    expect(mockedDecrypt).toHaveBeenCalledWith('file://enc-1.enc');
  });

  it('returns cached value on subsequent renders', async () => {
    mockedDecrypt.mockResolvedValue('file://tmp/decrypted.jpg');

    const { result, rerender } = await renderHook(
      (props: { src: string }) => useDecryptedImage(props.src),
      { initialProps: { src: 'file://enc-cache.enc' } },
    );

    await waitFor(() => {
      expect(result.current).toBe('file://tmp/decrypted.jpg');
    });

    expect(mockedDecrypt).toHaveBeenCalledTimes(1);

    await rerender({ src: 'file://enc-cache.enc' });

    expect(result.current).toBe('file://tmp/decrypted.jpg');
    expect(mockedDecrypt).toHaveBeenCalledTimes(1);
  });

  it('falls back to original src on decryption error', async () => {
    mockedDecrypt.mockRejectedValue(new Error('Decryption failed'));

    const { result } = await renderHook(() => useDecryptedImage('file://enc-err.enc'));

    await waitFor(() => {
      expect(result.current).toBe('file://enc-err.enc');
    });
  });

  it('handles unmount without setting state', async () => {
    let resolvePromise: (v: string) => void;
    mockedDecrypt.mockReturnValue(
      new Promise<string>((resolve) => {
        resolvePromise = resolve;
      }),
    );

    const { result, unmount } = await renderHook(() => useDecryptedImage('file://enc-unmount.enc'));

    await unmount();

    resolvePromise!('file://tmp/decrypted.jpg');
    await new Promise((r) => setImmediate(r));

    expect(result.current).toBe('file://enc-unmount.enc');
  });

  it('returns original src when decryption returns empty string', async () => {
    mockedDecrypt.mockResolvedValue('');

    const { result } = await renderHook(() => useDecryptedImage('file://enc-empty.enc'));

    await waitFor(() => {
      expect(result.current).toBe('file://enc-empty.enc');
    });
  });

  it('evicts the oldest entry once the cache limit is reached', async () => {
    mockedDecrypt.mockResolvedValue('file://tmp/evict.jpg');

    // Fill past the 50-entry cap. Let each async effect settle before unmount.
    for (let i = 0; i < 55; i++) {
      const { unmount } = await renderHook(() => useDecryptedImage(`file://evict-${i}.enc`));
      await new Promise((r) => setImmediate(r));
      unmount();
    }
    expect(mockedDecrypt).toHaveBeenCalledTimes(55);

    // The first entry was evicted, so it decrypts again.
    const { unmount: unmountFirst } = await renderHook(() =>
      useDecryptedImage('file://evict-0.enc'),
    );
    await new Promise((r) => setImmediate(r));
    unmountFirst();
    expect(mockedDecrypt).toHaveBeenCalledTimes(56);

    // A recent entry is still cached — no extra decrypt.
    const { unmount: unmountRecent } = await renderHook(() =>
      useDecryptedImage('file://evict-54.enc'),
    );
    await new Promise((r) => setImmediate(r));
    unmountRecent();
    expect(mockedDecrypt).toHaveBeenCalledTimes(56);
  });
});

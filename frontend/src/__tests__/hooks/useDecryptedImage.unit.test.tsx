import { renderHook, waitFor } from '@testing-library/react-native';
import fileCrypto from '@/utils/fileCrypto';
import useDecryptedImage from '@/hooks/useDecryptedImage';

jest.mock('@/utils/fileCrypto', () => ({
  decryptImageToTemp: jest.fn(),
}));

const mockFileCrypto = fileCrypto as jest.Mocked<typeof fileCrypto>;

describe('useDecryptedImage', () => {
  beforeEach(() => {
    mockFileCrypto.decryptImageToTemp.mockReset();
    // Clear the module-level cache
    const useDecryptedImageModule = require('@/hooks/useDecryptedImage');
    if (useDecryptedImageModule.cache) {
      useDecryptedImageModule.cache.clear();
    }
  });

  it('returns undefined when src is undefined', () => {
    const { result } = renderHook(() => useDecryptedImage(undefined));
    expect(result.current).toBeUndefined();
  });

  it('returns undefined when src is null', () => {
    const { result } = renderHook(() => useDecryptedImage(null));
    expect(result.current).toBeUndefined();
  });

  it('returns decrypted path when decryption succeeds', async () => {
    const src = 'file:///encrypted/image.enc';
    const decryptedPath = 'file:///tmp/decrypted/image.jpg';
    mockFileCrypto.decryptImageToTemp.mockResolvedValue(decryptedPath);

    const { result } = renderHook(() => useDecryptedImage(src));

    await waitFor(
      () => {
        expect(result.current).toBe(decryptedPath);
      },
      { timeout: 2000 },
    );

    expect(mockFileCrypto.decryptImageToTemp).toHaveBeenCalledWith(src);
  });

  it('returns original src when decryption throws', async () => {
    const src = 'file:///encrypted/image-throw.enc';
    mockFileCrypto.decryptImageToTemp.mockRejectedValue(new Error('Decryption failed'));

    const { result } = renderHook(() => useDecryptedImage(src));

    expect(result.current).toBe(src);

    await waitFor(
      () => {
        expect(mockFileCrypto.decryptImageToTemp).toHaveBeenCalledWith(src);
      },
      { timeout: 2000 },
    );
  });

  it('returns original src when decryption returns undefined', async () => {
    const src = 'file:///encrypted/image-undefined.enc';
    mockFileCrypto.decryptImageToTemp.mockResolvedValue(undefined as any);

    const { result } = renderHook(() => useDecryptedImage(src));

    expect(result.current).toBe(src);

    await waitFor(
      () => {
        expect(mockFileCrypto.decryptImageToTemp).toHaveBeenCalledWith(src);
      },
      { timeout: 2000 },
    );
  });

  it('re-decrypts when src changes', async () => {
    const src1 = 'file:///encrypted/image1.enc';
    const src2 = 'file:///encrypted/image2.enc';
    const decrypted1 = 'file:///tmp/decrypted/image1.jpg';
    const decrypted2 = 'file:///tmp/decrypted/image2.jpg';

    mockFileCrypto.decryptImageToTemp
      .mockResolvedValueOnce(decrypted1)
      .mockResolvedValueOnce(decrypted2);

    const { result, rerender } = renderHook(
      ({ source }: { source: string }) => useDecryptedImage(source),
      { initialProps: { source: src1 } },
    );

    await waitFor(
      () => {
        expect(result.current).toBe(decrypted1);
      },
      { timeout: 2000 },
    );

    rerender({ source: src2 });

    await waitFor(
      () => {
        expect(result.current).toBe(decrypted2);
      },
      { timeout: 2000 },
    );
    expect(mockFileCrypto.decryptImageToTemp).toHaveBeenCalledTimes(2);
  });

  it('returns undefined when src is empty string', async () => {
    const { result } = renderHook(() => useDecryptedImage(''));

    await waitFor(
      () => {
        expect(result.current).toBeUndefined();
      },
      { timeout: 2000 },
    );
    expect(mockFileCrypto.decryptImageToTemp).not.toHaveBeenCalled();
  });
});

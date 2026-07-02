import { useEffect, useState } from 'react';
import fileCrypto from '@/utils/fileCrypto';

// simple in-memory cache for decrypted temp paths
const cache = new Map<string, string>();

/**
 * useDecryptedImage
 *
 * Decrypts an encrypted image URI to a temporary local file and caches the result.
 */
export default function useDecryptedImage(src?: string | null) {
  const [resolved, setResolved] = useState<string | undefined>(undefined);

  useEffect(() => {
    let mounted = true;
    if (!src) {
      setResolved(undefined);
      return;
    }

    // if cached, return immediately
    const cached = cache.get(src);
    if (cached) {
      setResolved(cached);
      return;
    }

    (async () => {
      try {
        const dec = await fileCrypto.decryptImageToTemp(src);
        if (!mounted) return;
        cache.set(src, dec);
        setResolved(dec);
      } catch (e) {
        if (!mounted) return;
        setResolved(src);
      }
    })();

    return () => {
      mounted = false;
    };
  }, [src]);

  return resolved || src || undefined;
}

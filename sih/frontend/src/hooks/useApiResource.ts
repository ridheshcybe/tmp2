// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — REST resource hook
// ══════════════════════════════════════════════════════════════════════════════
//
// Every panel that shows backend state (missions, faults, reports, residuals,
// simulation status) needs the same three things: the last good payload, an
// error when the call fails, and a refresh loop. This hook owns that once.
//
//   const { data, error, loading, reload } = useApiResource(
//     () => api.missions.list(),
//     { intervalMs: 5000, deps: [missionId] }
//   );
//
// A failed poll keeps the previous payload on screen and surfaces `error`,
// so a transient backend hiccup does not blank a dashboard mid-demo.
// ══════════════════════════════════════════════════════════════════════════════

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../services/api';

export interface ApiResource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** Reload immediately (e.g. after a mutation). */
  reload: () => Promise<void>;
}

export interface UseApiResourceOptions {
  /** Poll every N ms. Omit for a one-shot fetch. */
  intervalMs?: number;
  /** Extra dependencies that should restart the fetch/poll loop. */
  deps?: unknown[];
  /** Skip fetching entirely (e.g. no mission selected yet). */
  enabled?: boolean;
}

/** Human-readable message for anything thrown by the API client. */
export function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return err.message;
    return err.detail ? `${err.message}: ${err.detail}` : err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

export function useApiResource<T>(
  loader: () => Promise<T>,
  options: UseApiResourceOptions = {}
): ApiResource<T> {
  const { intervalMs, deps = [], enabled = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Keep the latest loader without making it a dependency, so callers can pass
  // an inline arrow function without restarting the poll every render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const fetchNow = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (!mounted.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (!mounted.current) return;
      setError(describeApiError(err));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    void fetchNow();

    if (!intervalMs || intervalMs <= 0) return;
    const timer = setInterval(() => void fetchNow(), intervalMs);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, fetchNow, ...deps]);

  return { data, error, loading, reload: fetchNow };
}

export default useApiResource;

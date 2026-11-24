"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBlob } from "./api";

/** Fetch data and optionally re-fetch on an interval (a number, or a function of the latest data). */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[],
  intervalMs?: number | null | ((data: T | null) => number | null),
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const intervalRef = useRef(intervalMs);
  intervalRef.current = intervalMs;

  const reload = useCallback(async () => {
    try {
      const result = await fnRef.current();
      setData(result);
      setError(null);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const result = await reload();
      if (cancelled) return;
      const iv = typeof intervalRef.current === "function" ? intervalRef.current(result) : (intervalRef.current ?? null);
      if (iv) timer = setTimeout(tick, iv);
    };
    setLoading(true);
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/** Authenticated image/file -> object URL (an <img> tag cannot send the Authorization header). */
export function useBlobUrl(path: string | null): { url: string | null; error: string | null } {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setUrl(null);
      return;
    }
    let stale = false;
    let objectUrl: string | null = null;
    setError(null);
    apiBlob(path)
      .then((blob) => {
        if (stale) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
    return () => {
      stale = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  return { url, error };
}

/**
 * useLocalStorage — generic hook for reading/writing values to localStorage
 * with SSR guard and JSON parse/stringify error handling.
 *
 * @param key        — localStorage key
 * @param initialValue — fallback when key is absent or parse fails
 *                      (also accepts a lazy initializer like useState)
 */
import { useState, useCallback, useEffect, useRef } from 'react';

type SetValue<T> = T | ((prev: T) => T);

function useLocalStorage<T>(
  key: string,
  initialValue: T | (() => T),
): [T, (value: SetValue<T>) => void] {
  // Track whether the initial value came from localStorage or is a fresh default
  // Using a ref instead of state — no re-render needed, just a flag to avoid
  // re-writing the initial value on subsequent renders.
  const wasInStorageRef = useRef((() => {
    if (typeof window === 'undefined') return true; // SSR: don't write
    try {
      return window.localStorage.getItem(key) !== null;
    } catch {
      return true;
    }
  })());

  // Lazy initializer — read from localStorage once on mount
  const [storedValue, setStoredValue] = useState<T>(() => {
    // SSR guard
    if (typeof window === 'undefined') {
      return typeof initialValue === 'function'
        ? (initialValue as () => T)()
        : initialValue;
    }

    try {
      const item = window.localStorage.getItem(key);
      if (item !== null) {
        return JSON.parse(item) as T;
      }
    } catch (error) {
      console.warn(
        `Error reading localStorage key "${key}":`,
        error,
      );
    }

    return typeof initialValue === 'function'
      ? (initialValue as () => T)()
      : initialValue;
  });

  // Persist initial value to localStorage if it wasn't there before
  useEffect(() => {
    if (!wasInStorageRef.current && typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(key, JSON.stringify(storedValue));
      } catch (error) {
        console.warn(
          `Error setting localStorage key "${key}":`,
          error,
        );
      }
      wasInStorageRef.current = true;
    }
  }, [key, storedValue]);

  const setValue = useCallback(
    (value: SetValue<T>) => {
      try {
        setStoredValue((prev) => {
          const valueToStore =
            value instanceof Function ? value(prev) : value;

          // SSR guard before writing
          if (typeof window !== 'undefined') {
            window.localStorage.setItem(
              key,
              JSON.stringify(valueToStore),
            );
          }

          return valueToStore;
        });
      } catch (error) {
        // Quota exceeded or private browsing
        console.warn(
          `Error setting localStorage key "${key}":`,
          error,
        );
      }
    },
    [key],
  );

  return [storedValue, setValue];
}

export default useLocalStorage;

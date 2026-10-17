import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'theme';
const darkQuery = '(prefers-color-scheme: dark)';

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function systemTheme() {
  return window.matchMedia(darkQuery).matches ? 'dark' : 'light';
}

// The stored choice is applied before React loads by the inline script in
// index.html; without one, the CSS follows prefers-color-scheme.
export default function useTheme() {
  const [theme, setTheme] = useState(() => readStored() || systemTheme());

  useEffect(() => {
    if (readStored()) return undefined;
    const media = window.matchMedia(darkQuery);
    const onChange = () => setTheme(systemTheme());
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // storage unavailable (private mode): the choice lasts until reload
    }
    setTheme(next);
  }, [theme]);

  return { theme, toggleTheme };
}

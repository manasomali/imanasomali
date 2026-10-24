import { useCallback, useEffect, useState } from 'react';
import { chooseTheme, readStoredTheme, systemTheme, watchSystemTheme } from '../lib/theme';

// Tema atual e a troca. A escolha salva já foi aplicada por public/theme-init.js antes do React;
// sem escolha, acompanha o tema do sistema até a pessoa escolher um
export default function useTheme() {
  const [stored, setStored] = useState(readStoredTheme);
  const [system, setSystem] = useState(systemTheme);

  useEffect(() => {
    if (stored) return undefined;
    return watchSystemTheme(setSystem);
  }, [stored]);

  const theme = stored ?? system;

  const toggleTheme = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark';
    chooseTheme(next);
    setStored(next);
  }, [theme]);

  return { theme, toggleTheme };
}

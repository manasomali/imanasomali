import { useCallback, useEffect, useRef, useState } from 'react';

const TICK_MS = 1000;

/**
 * Contagem regressiva em segundos inteiros: `[restantes, iniciar(segundos)]`. Conta pelo relógio
 * (Date.now) e não pelo número de ticks, então uma aba em segundo plano, com timers atrasados,
 * não estica a espera.
 */
export default function useCountdown() {
  const [remaining, setRemaining] = useState(0);
  const deadline = useRef(0);
  const running = remaining > 0;

  const start = useCallback((seconds) => {
    deadline.current = Date.now() + seconds * 1000;
    setRemaining(seconds);
  }, []);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => {
      setRemaining(Math.max(0, Math.ceil((deadline.current - Date.now()) / 1000)));
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [running]);

  return [remaining, start];
}

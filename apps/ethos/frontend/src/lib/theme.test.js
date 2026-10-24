import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFrontendFile } from '../test/files';
import { readItem, writeItem } from './storage';
import { THEME_KEY, chooseTheme, readStoredTheme, systemTheme, watchSystemTheme } from './theme';

const themeInit = readFrontendFile('public/theme-init.js');

function runThemeInit() {
  // Roda o arquivo como o navegador roda um <script> clássico
  window.eval(themeInit);
}

function mockMatchMedia(matches) {
  const listeners = new Set();
  const media = {
    matches,
    addEventListener: vi.fn((_type, listener) => listeners.add(listener)),
    removeEventListener: vi.fn((_type, listener) => listeners.delete(listener)),
  };
  window.matchMedia = vi.fn(() => media);
  return {
    media,
    change(value) {
      media.matches = value;
      for (const listener of listeners) listener();
    },
  };
}

afterEach(() => {
  delete window.matchMedia;
  vi.restoreAllMocks();
});

describe('public/theme-init.js', () => {
  it('applies the theme saved by the site before React loads', () => {
    window.localStorage.setItem(THEME_KEY, 'dark');

    runThemeInit();

    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('leaves the system theme alone when nothing was chosen', () => {
    runThemeInit();

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('ignores values outside the contract', () => {
    window.localStorage.setItem(THEME_KEY, '"><img>');

    runThemeInit();

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('survives blocked storage', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });

    expect(runThemeInit).not.toThrow();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});

describe('theme', () => {
  it('reads only light or dark from the shared key', () => {
    expect(readStoredTheme()).toBeNull();
    window.localStorage.setItem(THEME_KEY, 'light');
    expect(readStoredTheme()).toBe('light');
    window.localStorage.setItem(THEME_KEY, 'sepia');
    expect(readStoredTheme()).toBeNull();
  });

  it('applies and saves a choice', () => {
    chooseTheme('dark');

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem(THEME_KEY)).toBe('dark');
  });

  it('refuses an unknown theme', () => {
    expect(() => chooseTheme('sepia')).toThrow(RangeError);
  });

  it('follows the system without matchMedia support as light', () => {
    expect(systemTheme()).toBe('light');
    expect(watchSystemTheme(() => {})).toBeTypeOf('function');
  });

  it('reads and watches the system theme', () => {
    const system = mockMatchMedia(true);
    const callback = vi.fn();

    expect(systemTheme()).toBe('dark');
    const stop = watchSystemTheme(callback);
    system.change(false);
    expect(callback).toHaveBeenCalledWith('light');

    stop();
    expect(system.media.removeEventListener).toHaveBeenCalled();
    system.change(true);
    expect(callback).toHaveBeenCalledTimes(1);
  });
});

describe('storage', () => {
  it('reads and writes', () => {
    expect(writeItem('ethos:x', '1')).toBe(true);
    expect(readItem('ethos:x')).toBe('1');
  });

  it('never throws when storage is blocked', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });

    expect(readItem('theme')).toBeNull();
    expect(writeItem('theme', 'dark')).toBe(false);
    expect(() => chooseTheme('dark')).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});

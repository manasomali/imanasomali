import { describe, expect, it } from 'vitest';
import { pageLocation } from './location';

describe('pageLocation', () => {
  // O jsdom só navega dentro da página (âncora); o resto é o window.location do navegador
  it('replaces the location', () => {
    pageLocation.replace('#entrou');

    expect(window.location.hash).toBe('#entrou');
  });
});

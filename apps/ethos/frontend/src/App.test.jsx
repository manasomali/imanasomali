import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from './App';
import { axe } from './test/axe';

describe('App', () => {
  it('renders the app name as the main heading', () => {
    render(<App />);

    expect(screen.getByRole('heading', { level: 1, name: 'ethos' })).toBeDefined();
  });

  it('has no axe violations', async () => {
    const { container } = render(<App />);

    expect(await axe(container)).toHaveNoViolations();
  });
});

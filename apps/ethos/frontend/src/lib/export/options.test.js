import { describe, expect, it } from 'vitest';
import { habitFixture } from '../../test/habits';
import { ALL_OPTIONS, DEFAULT_OPTIONS, REPORT_FIELDS, normalizeOptions, visibleFields } from './options';

describe('report options', () => {
  it('starts with everything but the notes', () => {
    expect(Object.keys(DEFAULT_OPTIONS).sort()).toEqual([...REPORT_FIELDS].sort());
    expect(DEFAULT_OPTIONS.note).toBe(false);
    expect(REPORT_FIELDS.filter((field) => field !== 'note').every((field) => DEFAULT_OPTIONS[field])).toBe(true);
    expect(Object.values(ALL_OPTIONS).every(Boolean)).toBe(true);
  });

  it('keeps only known fields, as booleans', () => {
    expect(normalizeOptions({ score: true, cost: 'yes', extra: true })).toEqual({
      score: true,
      reward: false,
      punishment: false,
      cost: false,
      duration: false,
      note: false,
      author: false,
    });
    expect(normalizeOptions()).toEqual(normalizeOptions({}));
  });

  it('shows a field only when chosen and turned on in the habit', () => {
    const off = habitFixture();
    expect(visibleFields(off, ALL_OPTIONS)).toEqual({
      score: false,
      reward: false,
      punishment: false,
      cost: false,
      duration: false,
      note: false,
      author: true,
    });

    const on = habitFixture({
      score_enabled: true,
      cost_enabled: true,
      duration_enabled: true,
      duration_minutes: 10,
      notes_enabled: true,
    });
    expect(Object.values(visibleFields(on, ALL_OPTIONS)).every(Boolean)).toBe(true);
    expect(visibleFields(on, normalizeOptions({ score: true }))).toEqual({
      score: true,
      reward: false,
      punishment: false,
      cost: false,
      duration: false,
      note: false,
      author: false,
    });
  });
});

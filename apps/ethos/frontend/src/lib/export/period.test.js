import { describe, expect, it } from 'vitest';
import {
  MAX_REPORT_YEARS,
  PERIOD_PRESETS,
  addYears,
  checkPeriod,
  daysBetween,
  periodChunks,
  presetPeriod,
  rangeEnd,
  yearsOf,
} from './period';

describe('report period', () => {
  it('adds years, moving 29 February to 1 March in common years', () => {
    expect(addYears('2026-03-04', 1)).toBe('2027-03-04');
    expect(addYears('2024-02-29', 1)).toBe('2025-03-01');
    expect(addYears('2024-02-29', 4)).toBe('2028-02-29');
    expect(addYears('2026-03-04', -5)).toBe('2021-03-04');
  });

  it('follows the backend rule of at most 5 years', () => {
    expect(MAX_REPORT_YEARS).toBe(5);
    expect(rangeEnd('2021-01-01')).toBe('2026-01-01');
    expect(checkPeriod('2021-01-01', '2025-12-31')).toBeNull();
    expect(checkPeriod('2021-01-01', '2026-01-01')).toBe('too_long');
    expect(checkPeriod('2024-02-29', '2029-02-28')).toBeNull();
    expect(checkPeriod('2024-02-29', '2029-03-01')).toBe('too_long');
    expect(checkPeriod('2026-03-04', '2026-03-04')).toBeNull();
  });

  it('refuses inverted and invalid periods', () => {
    expect(checkPeriod('2026-03-05', '2026-03-04')).toBe('order');
    expect(checkPeriod('', '2026-03-04')).toBe('invalid');
    expect(checkPeriod('2026-02-30', '2026-03-04')).toBe('invalid');
    expect(checkPeriod('2026-03-04', 'tomorrow')).toBe('invalid');
  });

  it('splits a long period in chunks the API accepts', () => {
    expect(periodChunks('2026-03-01', '2026-03-31')).toEqual([
      { from: '2026-03-01', to: '2026-03-31' },
    ]);
    const chunks = periodChunks('1950-06-01', '2026-10-24');
    expect(chunks[0]).toEqual({ from: '1950-06-01', to: '1954-12-31' });
    expect(chunks[1]).toEqual({ from: '1955-01-01', to: '1959-12-31' });
    expect(chunks[chunks.length - 1]).toEqual({ from: '2025-01-01', to: '2026-10-24' });
    for (const [index, chunk] of chunks.entries()) {
      expect(checkPeriod(chunk.from, chunk.to)).toBeNull();
      if (index > 0) expect(daysBetween(chunks[index - 1].to, chunk.from)).toBe(1);
    }
  });

  it('refuses to split an invalid period', () => {
    expect(() => periodChunks('2026-03-05', '2026-03-04')).toThrow(RangeError);
    expect(() => periodChunks('2026-13-01', '2026-03-04')).toThrow(RangeError);
    expect(() => periodChunks('2026-03-01', 'x')).toThrow(RangeError);
  });

  it('lists the calendar years and counts days', () => {
    expect(yearsOf('2024-12-31', '2026-01-01')).toEqual([2024, 2025, 2026]);
    expect(yearsOf('2026-03-01', '2026-03-02')).toEqual([2026]);
    expect(yearsOf('2026-03-01', '2025-03-02')).toEqual([]);
    expect(daysBetween('2026-03-01', '2026-03-31')).toBe(30);
    expect(daysBetween('2024-01-01', '2025-01-01')).toBe(366);
    expect(daysBetween('2026-03-02', '2026-03-01')).toBe(-1);
  });

  it('has quick periods ending today, all within 5 years', () => {
    // A semana começa no domingo, como no calendário: 24/10/2026 é sábado
    expect(presetPeriod('week', '2026-10-24')).toEqual({ from: '2026-10-18', to: '2026-10-24' });
    expect(presetPeriod('week', '2026-10-25')).toEqual({ from: '2026-10-25', to: '2026-10-25' });
    expect(presetPeriod('week', '2026-11-03')).toEqual({ from: '2026-11-01', to: '2026-11-03' });
    expect(presetPeriod('week', '2026-01-01')).toEqual({ from: '2025-12-28', to: '2026-01-01' });
    expect(presetPeriod('month', '2026-10-24')).toEqual({ from: '2026-10-01', to: '2026-10-24' });
    expect(presetPeriod('year', '2026-10-24')).toEqual({ from: '2026-01-01', to: '2026-10-24' });
    expect(presetPeriod('12_months', '2026-10-24')).toEqual({ from: '2025-10-25', to: '2026-10-24' });
    expect(presetPeriod('5_years', '2026-10-24')).toEqual({ from: '2021-10-25', to: '2026-10-24' });
    for (const today of ['2026-10-24', '2028-02-29', '2025-02-28', '2025-03-01']) {
      for (const preset of PERIOD_PRESETS) {
        const { from, to } = presetPeriod(preset, today);
        expect(checkPeriod(from, to), `${preset} ${today}`).toBeNull();
      }
    }
    expect(() => presetPeriod('decade', '2026-10-24')).toThrow(RangeError);
  });
});

import { describe, expect, it } from 'vitest';
import { reportPath } from '../../paths';
import { parseReportSearch } from './params';

const TODAY = '2026-10-24';

function parse(search) {
  return parseReportSearch(new URLSearchParams(search), TODAY);
}

describe('report state in the URL', () => {
  it('reads the period and the habits', () => {
    expect(parse('from=2026-01-01&to=2026-03-31&habit_id=5&habit_id=3&habit_id=5')).toEqual({
      from: '2026-01-01',
      to: '2026-03-31',
      habitIds: [3, 5],
    });
  });

  it('uses this year and every habit by default', () => {
    expect(parse('')).toEqual({ from: '2026-01-01', to: TODAY, habitIds: null });
  });

  it('falls back to the default period when it is invalid', () => {
    const fallback = { from: '2026-01-01', to: TODAY, habitIds: null };
    expect(parse('from=2026-02-30&to=2026-03-01')).toEqual(fallback);
    expect(parse('from=2026-03-02&to=2026-03-01')).toEqual(fallback);
    expect(parse('from=2020-01-01&to=2025-01-01')).toEqual(fallback);
    expect(parse('from=2026-01-01')).toEqual(fallback);
  });

  it('ignores invalid habit ids', () => {
    expect(parse('habit_id=0&habit_id=-1&habit_id=abc&habit_id=1e3&habit_id=99999999999999999').habitIds).toBeNull();
    expect(parse('habit_id=abc&habit_id=7').habitIds).toEqual([7]);
  });

  it('round-trips through reportPath', () => {
    const state = { from: '2026-01-01', to: '2026-03-31', habitIds: [3, 5] };
    const path = reportPath(state);

    expect(path).toBe('/relatorio?from=2026-01-01&to=2026-03-31&habit_id=3&habit_id=5');
    expect(parse(path.split('?')[1])).toEqual(state);
    expect(reportPath()).toBe('/relatorio');
    expect(reportPath({ habitIds: [] })).toBe('/relatorio');
    expect(reportPath({ habitIds: [3] })).toBe('/relatorio?habit_id=3');
  });
});

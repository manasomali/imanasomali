import { describe, expect, it } from 'vitest';
import { HABIT_SECTION, PATHS, habitPath, parseHabitId } from './paths';
import { readFrontendFile } from './test/files';

describe('habit paths', () => {
  it('builds the path of each section, with the query', () => {
    expect(habitPath(3)).toBe('/habits/3');
    expect(habitPath(3, HABIT_SECTION.settings)).toBe('/habits/3/settings');
    expect(habitPath(3, undefined, { day: '2026-03-04', year: null })).toBe('/habits/3?day=2026-03-04');
    expect(() => habitPath(0)).toThrow(TypeError);
    expect(() => habitPath('3')).toThrow(TypeError);
  });

  it('reads the id from the path', () => {
    expect(parseHabitId('42')).toBe(42);
    expect(parseHabitId('0')).toBeNull();
    expect(parseHabitId('07')).toBeNull();
    expect(parseHabitId('1.5')).toBeNull();
    expect(parseHabitId('99999999999999999')).toBeNull();
    expect(parseHabitId(undefined)).toBeNull();
  });

  it('keeps the alerts route where the alert email points', () => {
    const templates = readFrontendFile('../backend/app/mail/templates.py');
    const match = /^ALERT_SETTINGS_PATH = "(.+)"$/m.exec(templates);

    expect(match).not.toBeNull();
    expect(`${PATHS.habit}/${HABIT_SECTION.alerts}`.replace(':habitId', '{habit_id}')).toBe(match[1]);
  });
});

import { describe, expect, it } from 'vitest';
import {
  CALENDAR_VIEWS,
  DEFAULT_CALENDAR_VIEW,
  VIEW_STORAGE_KEY,
  parseCalendarView,
  resolveView,
} from './calendarView';

describe('calendar view', () => {
  it('has the grid as the default and its own storage key', () => {
    expect(CALENDAR_VIEWS).toEqual(['grid', 'columns']);
    expect(DEFAULT_CALENDAR_VIEW).toBe('grid');
    expect(VIEW_STORAGE_KEY).toBe('ethos:calendar-view');
    expect(VIEW_STORAGE_KEY).not.toBe('ethos:calendar-range');
  });

  it.each([
    ['grid', 'grid'],
    ['columns', 'columns'],
    ['Columns', null],
    ['list', null],
    ['', null],
    [null, null],
    [undefined, null],
  ])('parses %j as %j', (value, expected) => {
    expect(parseCalendarView(value)).toBe(expected);
  });

  it.each([
    ['columns', 'grid', 'columns'],
    ['grid', 'columns', 'grid'],
    [null, 'columns', 'columns'],
    ['bad', 'columns', 'columns'],
    [null, null, 'grid'],
    ['bad', 'worse', 'grid'],
  ])('URL %j and stored %j show %j', (param, stored, expected) => {
    expect(resolveView(param, stored)).toBe(expected);
  });
});

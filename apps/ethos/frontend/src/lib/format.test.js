import { describe, expect, it } from 'vitest';
import {
  calendarWeekdayNames,
  formatDate,
  formatDateTime,
  formatLongDay,
  formatMonth,
  formatShortDay,
  formatTime,
  weekdayNames,
} from './format';

describe('dates for the screen', () => {
  it('formats a local day without shifting it by the time zone', () => {
    expect(formatLongDay('2026-03-04', 'en')).toBe('Wednesday, March 4, 2026');
    expect(formatLongDay('2026-03-04', 'pt')).toBe('quarta-feira, 4 de março de 2026');
    expect(formatLongDay('2026-01-01', 'en')).toBe('Thursday, January 1, 2026');
  });

  it('formats a short local day', () => {
    expect(formatShortDay('2026-03-04', 'en')).toBe('Mar 4, 2026');
    expect(formatShortDay('2026-03-04', 'pt')).toBe('4 de mar. de 2026');
  });

  it('names months and weekdays, starting on Monday', () => {
    expect(formatMonth(3, 'en')).toBe('March');
    expect(formatMonth(12, 'pt')).toBe('dezembro');

    const weekdays = weekdayNames('en');
    expect(weekdays.map((day) => day.long)).toEqual([
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ]);
    expect(weekdays[0].short).toBe('M');
  });

  it('heads the calendar from Sunday to Saturday, in pt and en', () => {
    expect(calendarWeekdayNames('en').map((day) => day.long)).toEqual([
      'Sunday',
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
    ]);
    expect(calendarWeekdayNames('en').map((day) => day.short).join('')).toBe('SMTWTFS');
    expect(calendarWeekdayNames('pt').map((day) => day.long)).toEqual([
      'domingo',
      'segunda-feira',
      'terça-feira',
      'quarta-feira',
      'quinta-feira',
      'sexta-feira',
      'sábado',
    ]);
    expect(calendarWeekdayNames('pt').map((day) => day.short).join('')).toBe('DSTQQSS');
  });

  it('shows instants in the viewer time zone', () => {
    const instant = '2026-03-04T15:05:00Z';

    expect(formatTime(instant, 'America/Sao_Paulo', 'pt')).toBe('12:05');
    expect(formatTime(instant, 'Asia/Tokyo', 'en')).toBe('12:05 AM');
    expect(formatDateTime(instant, 'America/Sao_Paulo', 'en')).toBe('Mar 4, 2026, 12:05 PM');
    expect(formatDate(instant, 'America/Sao_Paulo', 'en')).toBe('Mar 4, 2026');
    // 15:05 UTC já é o dia seguinte em Tóquio
    expect(formatDate(instant, 'Asia/Tokyo', 'en')).toBe('Mar 5, 2026');
  });
});

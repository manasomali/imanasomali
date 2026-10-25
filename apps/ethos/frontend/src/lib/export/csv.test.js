import { beforeAll, describe, expect, it } from 'vitest';
import { habitFixture, markFixture } from '../../test/habits';
import { fullHabit, fullMark, progressItem, reportData, translator } from '../../test/report';
import { centsToDecimal, csvCell, csvColumns, csvText, toCsv } from './csv';
import { ALL_OPTIONS, DEFAULT_OPTIONS } from './options';
import { buildReport } from './report';

const TODAY = '2026-03-20';
let t;

beforeAll(async () => {
  t = await translator('en');
});

/** Linhas do CSV (sem o BOM), cada uma como texto. */
function lines(text) {
  expect(text.startsWith('﻿')).toBe(true);
  expect(text.endsWith('\r\n')).toBe(true);
  return text.slice(1, -2).split('\r\n');
}

function report(habits, options = ALL_OPTIONS) {
  return buildReport(reportData({ habits }), options, { today: TODAY });
}

describe('csv cells', () => {
  it('quotes commas, quotes and line breaks', () => {
    expect(csvCell('plain')).toBe('plain');
    expect(csvCell('a, b')).toBe('"a, b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('line 1\nline 2')).toBe('"line 1\nline 2"');
    expect(csvCell('line 1\r\nline 2')).toBe('"line 1\r\nline 2"');
    expect(csvCell(null)).toBe('');
    expect(csvCell(undefined)).toBe('');
    expect(csvCell(30)).toBe('30');
  });

  it('neutralizes formulas with a leading quote', () => {
    expect(csvCell('=SOMA()')).toBe("'=SOMA()");
    expect(csvCell('=SOMA(A1,B1)')).toBe('"\'=SOMA(A1,B1)"');
    expect(csvCell('+5511999999999')).toBe("'+5511999999999");
    expect(csvCell('-2')).toBe("'-2");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell('\t=1')).toBe("'\t=1");
    expect(csvCell('=HYPERLINK("http://x")')).toBe('"\'=HYPERLINK(""http://x"")"');
    // Só no começo da célula
    expect(csvCell('a=b')).toBe('a=b');
    expect(csvCell("'=1")).toBe("'=1");
  });

  it('writes the file with BOM and CRLF', () => {
    expect(csvText([['a', 'b'], ['1', '=2']])).toBe("﻿a,b\r\n1,'=2\r\n");
  });

  it('writes cents with a dot and two decimals', () => {
    expect(centsToDecimal(0)).toBe('0.00');
    expect(centsToDecimal(5)).toBe('0.05');
    expect(centsToDecimal(123450)).toBe('1234.50');
    expect(centsToDecimal(10 ** 12)).toBe('10000000000.00');
    expect(() => centsToDecimal(-1)).toThrow(TypeError);
    expect(() => centsToDecimal(1.5)).toThrow(TypeError);
  });
});

describe('toCsv', () => {
  it('writes one safe row per mark, with commas, quotes, line breaks and formulas', () => {
    const habit = fullHabit({ name: 'Run, "fast"' });
    const marks = [
      fullMark({ id: 1, marked_at: '2026-03-02T15:00:00Z', note: '=SOMA()' }),
      fullMark({
        id: 2,
        marked_at: '2026-03-03T18:05:00Z',
        author: null,
        duration_minutes: null,
        cost_cents: null,
        note: 'felt "great",\nreally',
      }),
    ];

    const text = toCsv(report([progressItem(habit, { marks })]), { t });

    expect(text).toBe(
      '﻿Habit,Date,Time,Author,Duration (min),Cost,Note\r\n'
        + '"Run, ""fast""",2026-03-02,12:00,ana@example.com,30,12.50,\'=SOMA()\r\n'
        + '"Run, ""fast""",2026-03-03,15:05,Removed user,,,"felt ""great"",\nreally"\r\n',
    );
  });

  it('drops the columns of information that was not chosen', () => {
    const items = [progressItem(fullHabit(), { marks: [fullMark()] })];

    const all = toCsv(report(items), { t });
    const withoutCost = toCsv(report(items, { ...ALL_OPTIONS, cost: false }), { t });
    const minimal = toCsv(report(items, { ...ALL_OPTIONS, cost: false, duration: false, note: false, author: false }), { t });

    expect(lines(all)[0]).toBe('Habit,Date,Time,Author,Duration (min),Cost,Note');
    expect(lines(withoutCost)[0]).toBe('Habit,Date,Time,Author,Duration (min),Note');
    expect(lines(withoutCost)[1]).toBe('Running,2026-03-02,12:00,ana@example.com,30,Good run');
    expect(lines(minimal)).toEqual(['Habit,Date,Time', 'Running,2026-03-02,12:00']);
  });

  it('drops the columns of features off in every habit, and empties the cells of the others', () => {
    const plain = habitFixture({ id: 2, name: 'Read' });
    const plainMark = markFixture({ id: 9, habit_id: 2, duration_minutes: 15, cost_cents: 100, note: 'hidden' });

    const onlyPlain = report([progressItem(plain, { marks: [plainMark] })]);
    expect(csvColumns(onlyPlain)).toEqual(['habit', 'date', 'time', 'author']);
    // Recurso desligado no hábito: os valores guardados não saem
    expect(lines(toCsv(onlyPlain, { t }))[1]).toBe('Read,2026-03-02,12:00,ana@example.com');

    const mixed = report([
      progressItem(fullHabit(), { marks: [fullMark()] }),
      progressItem(plain, { marks: [plainMark] }),
    ]);
    expect(lines(toCsv(mixed, { t }))).toEqual([
      'Habit,Date,Time,Author,Duration (min),Cost,Note',
      'Running,2026-03-02,12:00,ana@example.com,30,12.50,Good run',
      'Read,2026-03-02,12:00,ana@example.com,,,',
    ]);
  });

  it('keeps the notes out by default and writes the header in Portuguese', async () => {
    const pt = await translator('pt');
    const text = toCsv(report([progressItem(fullHabit(), { marks: [fullMark()] })], DEFAULT_OPTIONS), { t: pt });

    expect(lines(text)[0]).toBe('Hábito,Data,Horário,Autor,Duração (min),Custo');
  });

  it('writes only the header without marks', () => {
    expect(lines(toCsv(report([progressItem(habitFixture(), { marks: [] })]), { t }))).toEqual([
      'Habit,Date,Time,Author',
    ]);
  });
});

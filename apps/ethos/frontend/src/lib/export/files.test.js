import { describe, expect, it } from 'vitest';
import { progressItem, readFileText as text, reportData, translator } from '../../test/report';
import { csvFile, exportFilename, jsonFile, reportFilename } from './files';
import { ALL_OPTIONS } from './options';
import { buildReport } from './report';

describe('export files', () => {
  it('builds safe file names', () => {
    expect(reportFilename('2026-01-01', '2026-12-31', 'csv')).toBe('ethos-2026-01-01_2026-12-31.csv');
    expect(exportFilename('../ethos /é?', 'json')).toBe('ethos.json');
    expect(exportFilename('.hidden', 'csv')).toBe('hidden.csv');
    expect(exportFilename('***', 'png')).toBe('ethos.png');
  });

  it('wraps the CSV and the JSON in files', async () => {
    const t = await translator('en');
    const report = buildReport(reportData({ habits: [progressItem()] }), ALL_OPTIONS, { today: '2026-03-20' });

    const csv = csvFile(report, { t });
    expect(csv.name).toBe('ethos-2026-03-01_2026-03-31.csv');
    expect(csv.type).toBe('text/csv;charset=utf-8');
    expect(await text(csv)).toBe('﻿Habit,Date,Time,Author\r\n');

    const json = jsonFile(report, { generatedAt: new Date('2026-03-20T15:00:00Z') });
    expect(json.name).toBe('ethos-2026-03-01_2026-03-31.json');
    expect(json.type).toBe('application/json');
    expect(JSON.parse(await text(json))).toMatchObject({ version: 1, habits: [{ id: 1 }] });
  });
});

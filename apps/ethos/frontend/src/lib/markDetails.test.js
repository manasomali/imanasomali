import { describe, expect, it } from 'vitest';
import { habitFixture, markFixture } from '../test/habits';
import { dayHasDetails, markHasDetails } from './markDetails';

const ALL_ON = {
  notes_enabled: true,
  duration_enabled: true,
  duration_minutes: 30,
  cost_enabled: true,
  cost_level: 'mark',
  cost_cents: 800,
};

describe('markHasDetails', () => {
  it('is false for a mark with only the defaults of the habit', () => {
    const habit = habitFixture(ALL_ON);
    expect(markHasDetails(habit, markFixture({ duration_minutes: 30, cost_cents: 800, note: null }))).toBe(false);
    expect(markHasDetails(habitFixture(), markFixture())).toBe(false);
  });

  it('counts a note, but not a blank one or one of a habit without notes', () => {
    expect(markHasDetails(habitFixture({ notes_enabled: true }), markFixture({ note: 'leg day' }))).toBe(true);
    expect(markHasDetails(habitFixture({ notes_enabled: true }), markFixture({ note: '  ' }))).toBe(false);
    expect(markHasDetails(habitFixture({ notes_enabled: false }), markFixture({ note: 'hidden' }))).toBe(false);
  });

  it('counts a duration other than the default, only with duration on', () => {
    const habit = habitFixture({ duration_enabled: true, duration_minutes: 30 });
    expect(markHasDetails(habit, markFixture({ duration_minutes: 45 }))).toBe(true);
    expect(markHasDetails(habit, markFixture({ duration_minutes: 30 }))).toBe(false);
    expect(markHasDetails(habit, markFixture({ duration_minutes: null }))).toBe(false);
    // Sem padrão, qualquer duração foi escolhida por alguém
    const noDefault = habitFixture({ duration_enabled: true, duration_minutes: null });
    expect(markHasDetails(noDefault, markFixture({ duration_minutes: 1 }))).toBe(true);
    expect(markHasDetails(habitFixture({ duration_enabled: false }), markFixture({ duration_minutes: 45 }))).toBe(false);
  });

  it('counts a cost other than the default, only with the cost per mark', () => {
    const perMark = habitFixture({ cost_enabled: true, cost_level: 'mark', cost_cents: 800 });
    expect(markHasDetails(perMark, markFixture({ cost_cents: 1250 }))).toBe(true);
    expect(markHasDetails(perMark, markFixture({ cost_cents: 0 }))).toBe(true);
    expect(markHasDetails(perMark, markFixture({ cost_cents: 800 }))).toBe(false);
    expect(markHasDetails(perMark, markFixture({ cost_cents: null }))).toBe(false);
    // Fixo no hábito: volta igual ao marcar de novo
    const perHabit = habitFixture({ cost_enabled: true, cost_level: 'habit', cost_cents: 800 });
    expect(markHasDetails(perHabit, markFixture({ cost_cents: 1250 }))).toBe(false);
    expect(markHasDetails(habitFixture({ cost_enabled: false, cost_level: 'mark' }), markFixture({ cost_cents: 5 }))).toBe(false);
  });

  it('ignores fields missing from a mark', () => {
    const habit = habitFixture(ALL_ON);
    expect(markHasDetails(habit, { id: 1 })).toBe(false);
  });
});

describe('dayHasDetails', () => {
  it('is true when any mark of the day has details', () => {
    const habit = habitFixture({ notes_enabled: true });
    expect(dayHasDetails(habit, undefined)).toBe(false);
    expect(dayHasDetails(habit, [])).toBe(false);
    expect(dayHasDetails(habit, [markFixture({ id: 1 }), markFixture({ id: 2, note: 'x' })])).toBe(true);
    expect(dayHasDetails(habit, [markFixture({ id: 1 })])).toBe(false);
  });
});

import { describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { habitFixture } from '../test/habits';
import { historyKeys, seenHistoryAuthors } from './history';
import { afterMarksChanged } from './marks';

const ANA = { id: 1, email: 'ana@example.com' };
const BIA = { id: 2, email: 'bia@example.com' };

function page(events, next = null) {
  return { events, next_cursor: next };
}

describe('history cache', () => {
  it('collects the authors of every history in the cache, without the removed ones', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(historyKeys.list({}), {
      pages: [page([{ id: 3, author: ANA }, { id: 2, author: null }], 'next'), page([{ id: 1, author: BIA }])],
      pageParams: [null, 'next'],
    });
    queryClient.setQueryData(historyKeys.list({ user_id: 2 }), { pages: [page([{ id: 1, author: BIA }])] });

    expect(seenHistoryAuthors(queryClient)).toEqual([ANA, BIA, BIA]);
    expect(seenHistoryAuthors(new QueryClient())).toEqual([]);
  });

  it('is marked stale when the marks of a habit change, with or without the score', () => {
    for (const habit of [habitFixture(), habitFixture({ score_enabled: true })]) {
      const queryClient = new QueryClient();
      queryClient.setQueryData(historyKeys.list({ habit_id: 1 }), { pages: [page([])], pageParams: [null] });

      afterMarksChanged(queryClient, habit);

      expect(queryClient.getQueryState(historyKeys.list({ habit_id: 1 })).isInvalidated).toBe(true);
    }
  });
});

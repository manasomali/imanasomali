import { useEffect, useId, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { useMe } from '../../api/auth';
import { useHabits } from '../../api/habits';
import { seenHistoryAuthors, useHistory } from '../../api/history';
import { useMembers } from '../../api/sharing';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import {
  authorOptions,
  historyQuery,
  historySearch,
  isInvertedRange,
  pageEvents,
  parseHistoryFilters,
} from '../../lib/history';
import EventItem from './EventItem';
import Filters from './Filters';
import styles from './styles.module.css';

const NONE = [];

// Histórico dos hábitos que o usuário acessa (GET /history), do mais recente ao mais antigo, com
// filtros de hábito, pessoa, evento e período na URL (`?habit_id=3&user_id=2&event=mark_created
// &from=2026-03-01&to=2026-03-31`): o voltar do navegador e o link compartilhado mostram o mesmo.
// Horários e datas no fuso da conta. "Carregar mais" segue o next_cursor
export default function History() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  // RequireSession só desenha as rotas com o usuário carregado
  const me = useMe().data;
  const timeZone = me.timezone;
  const [params, setParams] = useSearchParams();
  const search = params.toString();
  const filters = useMemo(() => parseHistoryFilters(new URLSearchParams(search)), [search]);
  const query = useMemo(() => historyQuery(filters), [filters]);
  const inverted = isInvertedRange(filters);
  const history = useHistory(query, { enabled: !inverted });
  const habits = useHabits().data ?? NONE;
  const archived = useHabits({ archived: true }).data ?? NONE;
  const members = useMembers(filters.habitId, { enabled: filters.habitId !== null }).data?.members ?? NONE;
  const events = useMemo(() => pageEvents(history.data?.pages), [history.data]);
  const queryClient = useQueryClient();
  const id = useId();
  const listRef = useRef(null);
  // Índice do primeiro evento da página pedida em "carregar mais": recebe o foco quando chegar
  const focusFrom = useRef(null);
  const title = t('history.title');

  // Quem já apareceu como autor nos históricos carregados nesta visita: o filtro de pessoa não perde
  // as opções quando um filtro as esconde. Lido do cache a cada desenho, que acontece quando a lista
  // atual muda (e é ela que traz autores novos)
  const seenAuthors = seenHistoryAuthors(queryClient);
  const memberPeople = useMemo(() => members.map((member) => member.user), [members]);
  const people = new Map(
    authorOptions(me, [memberPeople, seenAuthors]).map((person) => [person.id, person.email]),
  );
  const colors = useMemo(
    () => new Map([...habits, ...archived].map((habit) => [habit.id, habit.color])),
    [habits, archived],
  );

  useEffect(() => {
    const from = focusFrom.current;
    if (from === null || events.length <= from) return;
    focusFrom.current = null;
    listRef.current?.children[from]?.focus();
  }, [events.length]);

  // Cada aplicação de filtros que muda algo empilha uma entrada no histórico do navegador
  const apply = (next) => {
    const nextParams = historySearch(next);
    if (nextParams.toString() === historySearch(filters).toString()) return;
    focusFrom.current = null;
    setParams(nextParams, { preventScrollReset: true });
  };

  // Uma página por vez, e nunca durante a busca da lista (filtro novo ou atualização)
  const loadMore = () => {
    if (history.isFetching) return;
    focusFrom.current = events.length;
    history.fetchNextPage();
  };

  const context = { t, language, timeZone, people };
  // Filtro novo: a lista anterior fica na tela até a nova chegar
  const busy = history.isPlaceholderData;

  let content;
  if (inverted) {
    content = <p className={styles.muted}>{t('history.filters.invalid_range')}</p>;
  } else if (history.isPending) {
    content = <p role="status">{t('common.loading')}</p>;
  } else if (history.isError && !history.isFetchNextPageError) {
    content = <ErrorMessage error={history.error} onRetry={() => history.refetch()} />;
  } else {
    content = (
      <>
        <p role="status" className={styles.status}>
          {busy ? t('common.loading') : t('history.count', { count: events.length })}
        </p>
        {events.length === 0 ? (
          <p className={styles.muted}>{t('history.empty')}</p>
        ) : (
          <ol ref={listRef} className={styles.list} aria-busy={busy} aria-labelledby={`${id}-results`}>
            {events.map((entry) => (
              <EventItem
                key={entry.id}
                entry={entry}
                color={colors.get(entry.habit.id)}
                context={context}
              />
            ))}
          </ol>
        )}
        {history.isFetchNextPageError && (
          <ErrorMessage error={history.error} onRetry={loadMore} />
        )}
        {history.hasNextPage && !history.isFetchNextPageError && (
          <button
            type="button"
            className={styles.more}
            disabled={history.isFetching}
            onClick={loadMore}
          >
            {history.isFetchingNextPage ? t('common.loading') : t('history.load_more')}
          </button>
        )}
      </>
    );
  }

  return (
    <>
      <PageTitle title={title} />
      <h1 className={styles.title}>{title}</h1>

      <Filters
        initial={filters}
        me={me}
        habits={habits}
        archived={archived}
        seenAuthors={seenAuthors}
        onApply={apply}
      />

      <section className={styles.section} aria-labelledby={`${id}-results`}>
        <h2 id={`${id}-results`} className={styles.subtitle}>
          {t('history.results')}
        </h2>
        {content}
      </section>
    </>
  );
}

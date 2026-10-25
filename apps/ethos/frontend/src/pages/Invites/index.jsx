import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMe } from '../../api/auth';
import { habitKeys } from '../../api/habits';
import { acceptInvite, declineInvite, sharingKeys, useReceivedInvites } from '../../api/sharing';
import ErrorMessage from '../../components/ErrorMessage';
import HabitSwatch from '../../components/HabitSwatch';
import PageTitle from '../../components/PageTitle';
import { ApiError } from '../../lib/api';
import { formatDate } from '../../lib/format';
import { habitPath } from '../../paths';
import styles from '../sharing.module.css';

/** Tira o convite `inviteId` do cache do GET /invites (o menu conta dali). */
function dropInvite(queryClient, inviteId) {
  queryClient.setQueryData(sharingKeys.received, (data) =>
    data ? { ...data, invites: data.invites.filter((item) => item.id !== inviteId) } : data,
  );
}

// Caixa de convites recebidos (`/convites`): aceitar ou recusar. Aceitar invalida `habitKeys.all`,
// para o hábito aparecer na lista e nas abas. Ao abrir, a lista é sempre buscada de novo (o menu
// pode estar com a cópia de alguns minutos atrás). Uma ação por vez; o resultado e os erros
// aparecem no topo, porque o cartão do convite some
export default function Invites() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const title = t('invites.title');
  // RequireSession só desenha as rotas com o usuário carregado
  const timeZone = useMe().data.timezone;
  const received = useReceivedInvites({ fresh: true });
  const [notice, setNotice] = useState(null);
  const titleRef = useRef(null);

  const answer = useMutation({
    mutationFn: ({ invite, accept }) => (accept ? acceptInvite(invite.id) : declineInvite(invite.id)),
    onMutate: () => setNotice(null),
    onSuccess: (habit, { invite, accept }) => {
      dropInvite(queryClient, invite.id);
      if (accept) {
        queryClient.invalidateQueries({ queryKey: habitKeys.all });
        setNotice({ text: t('invites.accepted', { name: habit.name }), habitId: habit.id });
      } else {
        setNotice({ text: t('invites.declined', { name: invite.habit.name }) });
      }
      titleRef.current?.focus();
    },
    onError: (error, { invite }) => {
      // O convite não existe mais (cancelado pelo dono, ou respondido em outra aba)
      if (error instanceof ApiError && error.status === 404) dropInvite(queryClient, invite.id);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: sharingKeys.received }),
  });

  let body;
  if (received.data === undefined) {
    body = received.isPending ? (
      <p role="status">{t('common.loading')}</p>
    ) : (
      <ErrorMessage error={received.error} onRetry={() => received.refetch()} />
    );
  } else if (received.data.length === 0) {
    body = <p className={styles.muted}>{t('invites.empty')}</p>;
  } else {
    body = (
      <ul className={styles.list}>
        {received.data.map((invite) => (
          <li key={invite.id} className={styles.item}>
            <h2 className={styles.itemTitle}>
              <HabitSwatch className={styles.swatch} color={invite.habit.color} />
              {invite.habit.name}
            </h2>
            <p>
              {t('invites.from', { email: invite.owner.email })}{' '}
              <span className={styles.badge}>{t(`sharing.role.${invite.role}`)}</span>
            </p>
            <p className={styles.meta}>
              {t('invites.received_on', {
                date: formatDate(invite.created_at, timeZone, i18n.resolvedLanguage),
              })}
            </p>
            <div
              className={styles.buttons}
              role="group"
              aria-label={t('invites.actions', { name: invite.habit.name })}
            >
              <button
                type="button"
                className={styles.primary}
                disabled={answer.isPending}
                onClick={() => answer.mutate({ invite, accept: true })}
              >
                {t('invites.accept')}
              </button>
              <button
                type="button"
                className={styles.button}
                disabled={answer.isPending}
                onClick={() => answer.mutate({ invite, accept: false })}
              >
                {t('invites.decline')}
              </button>
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className={styles.page}>
      <PageTitle title={title} />
      <div className={styles.section}>
        <h1 ref={titleRef} tabIndex={-1} className={styles.title}>
          {title}
        </h1>
        <p className={styles.muted}>{t('invites.hint')}</p>
        <p role="status" className={styles.status}>
          {notice?.text}
          {notice?.habitId && (
            <>
              {' '}
              <Link to={habitPath(notice.habitId)}>{t('invites.open_habit')}</Link>
            </>
          )}
        </p>
        {answer.error && <ErrorMessage error={answer.error} />}
      </div>
      {body}
    </div>
  );
}

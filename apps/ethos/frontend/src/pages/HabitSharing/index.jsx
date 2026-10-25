import { useCallback, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMe } from '../../api/auth';
import { forgetHabit } from '../../api/habits';
import { markKeys } from '../../api/marks';
import {
  cancelInvite,
  leaveHabit,
  sharingKeys,
  useHabitInvites,
  useMembers,
} from '../../api/sharing';
import ErrorMessage from '../../components/ErrorMessage';
import { WithHelp } from '../../components/HelpLink';
import useHabitContext from '../../hooks/useHabitContext';
import { formatDate } from '../../lib/format';
import { guestSlots } from '../../lib/sharing';
import { PATHS } from '../../paths';
import styles from '../sharing.module.css';
import ConfirmPanel from './ConfirmPanel';
import InviteForm from './InviteForm';
import MemberItem from './MemberItem';

// Seção "compartilhamento" da aba do hábito (`/habits/:habitId/sharing`). Todo papel vê quem tem
// acesso. O dono convida (com o contador de vagas), troca papel, remove e cancela convites
// pendentes; editor e viewer podem sair do hábito. Esconder os controles é conveniência: quem
// garante é a API (403). Em hábito arquivado só convidar é recusado (409 habit_archived), então só
// o formulário some
export default function HabitSharing() {
  const { t } = useTranslation();
  const { habit, timeZone } = useHabitContext();
  const isOwner = habit.role === 'owner';
  // RequireSession só desenha as rotas com o usuário carregado
  const meId = useMe().data.id;
  const members = useMembers(habit.id);
  const invites = useHabitInvites(habit.id, { enabled: isOwner });
  const [status, setStatus] = useState('');
  const titleId = useId();
  const membersRef = useRef(null);
  const invitesRef = useRef(null);

  const clearStatus = useCallback(() => setStatus(''), []);

  // Quem saiu da lista leva o foco para o título dela (o botão que estava focado sumiu)
  const onMemberDone = useCallback((message, { removed = false } = {}) => {
    setStatus(message);
    if (removed) membersRef.current?.focus();
  }, []);

  const onInviteCanceled = useCallback((message) => {
    setStatus(message);
    invitesRef.current?.focus();
  }, []);

  const slots =
    isOwner && members.data && invites.data
      ? guestSlots(members.data.members, invites.data, members.data.guest_limit)
      : null;

  let memberList;
  if (members.data === undefined) {
    memberList = members.isPending ? (
      <p role="status">{t('common.loading')}</p>
    ) : (
      <ErrorMessage error={members.error} onRetry={() => members.refetch()} />
    );
  } else {
    memberList = (
      <>
        {isOwner && members.data.members.length === 1 && (
          <p className={styles.muted}>{t('sharing.members.only_you')}</p>
        )}
        <ul className={styles.list}>
          {members.data.members.map((member) => (
            <MemberItem
              key={member.user.id}
              habitId={habit.id}
              member={member}
              isSelf={member.user.id === meId}
              manage={isOwner && member.role !== 'owner'}
              timeZone={timeZone}
              onDone={onMemberDone}
            />
          ))}
        </ul>
      </>
    );
  }

  return (
    <section className={styles.page} aria-labelledby={titleId}>
      <div className={styles.section}>
        <WithHelp section="sharing" topic={t('sharing.title')}>
          <h2 id={titleId} className={styles.subtitle}>
            {t('sharing.title')}
          </h2>
        </WithHelp>
        <p role="status" className={styles.status}>
          {status}
        </p>
      </div>

      {isOwner &&
        (habit.status === 'archived' ? (
          <p className={styles.muted}>{t('sharing.invite.archived')}</p>
        ) : (
          <InviteForm habitId={habit.id} slots={slots} onSending={clearStatus} onSent={setStatus} />
        ))}

      <section className={styles.section} aria-labelledby={`${titleId}-members`}>
        <h3 id={`${titleId}-members`} ref={membersRef} tabIndex={-1} className={styles.heading}>
          {t('sharing.members.title')}
        </h3>
        {memberList}
      </section>

      {isOwner && (
        <PendingInvites
          habitId={habit.id}
          query={invites}
          timeZone={timeZone}
          headingRef={invitesRef}
          onCanceled={onInviteCanceled}
        />
      )}

      {!isOwner && <LeaveHabit habit={habit} />}
    </section>
  );
}

// Convites pendentes do hábito (só o dono). Cancelar não pede confirmação: dá para convidar de novo
function PendingInvites({ habitId, query, timeZone, headingRef, onCanceled }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const headingId = useId();

  const cancel = useMutation({
    mutationFn: (invite) => cancelInvite(habitId, invite.id),
    onSuccess: (_, invite) => {
      queryClient.setQueryData(sharingKeys.invites(habitId), (data) =>
        data ? { ...data, invites: data.invites.filter((item) => item.id !== invite.id) } : data,
      );
      onCanceled(t('sharing.invites.canceled', { email: invite.email }));
    },
    // Também no erro: o convite pode ter sido aceito ou recusado nesse meio-tempo (404)
    onSettled: () => queryClient.invalidateQueries({ queryKey: sharingKeys.invites(habitId) }),
  });

  let body;
  if (query.data === undefined) {
    body = query.isPending ? (
      <p role="status">{t('common.loading')}</p>
    ) : (
      <ErrorMessage error={query.error} onRetry={() => query.refetch()} />
    );
  } else if (query.data.length === 0) {
    body = <p className={styles.muted}>{t('sharing.invites.empty')}</p>;
  } else {
    body = (
      <ul className={styles.list}>
        {query.data.map((invite) => (
          <li key={invite.id} className={styles.item}>
            <p className={styles.itemTitle}>
              <span>{invite.email}</span>
              <span className={styles.badge}>{t(`sharing.role.${invite.role}`)}</span>
            </p>
            <p className={styles.meta}>
              {t('sharing.invites.sent_on', {
                date: formatDate(invite.created_at, timeZone, i18n.resolvedLanguage),
              })}
            </p>
            <div className={styles.buttons}>
              <button
                type="button"
                className={styles.button}
                aria-label={t('sharing.invites.cancel_label', { email: invite.email })}
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(invite)}
              >
                {t('sharing.invites.cancel')}
              </button>
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h3 id={headingId} ref={headingRef} tabIndex={-1} className={styles.heading}>
        {t('sharing.invites.title')}
      </h3>
      <p className={styles.hint}>{t('sharing.invites.hint')}</p>
      {cancel.error && <ErrorMessage error={cancel.error} />}
      {body}
    </section>
  );
}

// Editor e viewer saem sozinhos, com confirmação. Depois de sair, a aba do hábito não existe mais
// para a pessoa: volta para a tela inicial e só então tira o hábito do cache (antes, a aba ainda
// montada buscaria o hábito de novo e levaria um 404)
function LeaveHabit({ habit }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const panelId = useId();
  const headingId = useId();
  const openerRef = useRef(null);
  const [confirming, setConfirming] = useState(false);

  const leave = useMutation({
    mutationFn: () => leaveHabit(habit.id),
    onSuccess: async () => {
      await navigate(PATHS.home, { replace: true });
      for (const queryKey of [sharingKeys.habit(habit.id), markKeys.habit(habit.id)]) {
        queryClient.removeQueries({ queryKey });
      }
      forgetHabit(queryClient, habit.id);
    },
  });

  const close = () => {
    setConfirming(false);
    leave.reset();
    openerRef.current?.focus();
  };

  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h3 id={headingId} className={styles.heading}>
        {t('sharing.leave.title')}
      </h3>
      <p className={styles.muted}>{t('sharing.leave.warning')}</p>
      <div className={styles.buttons}>
        <button
          ref={openerRef}
          type="button"
          className={styles.button}
          aria-expanded={confirming}
          aria-controls={confirming ? panelId : undefined}
          disabled={leave.isPending}
          onClick={confirming ? close : () => setConfirming(true)}
        >
          {t('sharing.leave.button')}
        </button>
      </div>
      {confirming && (
        <ConfirmPanel
          id={panelId}
          title={t('sharing.leave.confirm_title', { name: habit.name })}
          confirmLabel={t('sharing.leave.confirm')}
          pending={leave.isPending}
          error={leave.error}
          onConfirm={() => leave.mutate()}
          onCancel={close}
        />
      )}
    </section>
  );
}

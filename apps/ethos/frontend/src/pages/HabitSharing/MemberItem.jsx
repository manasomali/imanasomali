import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { changeMemberRole, removeMember, sharingKeys } from '../../api/sharing';
import ErrorMessage from '../../components/ErrorMessage';
import { formatDate } from '../../lib/format';
import styles from '../sharing.module.css';
import ConfirmPanel from './ConfirmPanel';

const OTHER_ROLE = { editor: 'viewer', viewer: 'editor' };

/** Tira (`member` null) ou troca o membro `userId` no cache do GET /habits/{id}/members. */
function updateMembers(queryClient, habitId, userId, member) {
  queryClient.setQueryData(sharingKeys.members(habitId), (data) => {
    if (!data) return data;
    const members = member
      ? data.members.map((item) => (item.user.id === userId ? member : item))
      : data.members.filter((item) => item.user.id !== userId);
    return { ...data, members };
  });
}

// Uma pessoa com acesso ao hábito. Com `manage` (quem vê é o dono, e a pessoa não é o dono):
// trocar o papel (um clique, sem confirmação) e remover (pede confirmação). `onDone(mensagem,
// {removed})` avisa a seção, que mostra a mensagem e, se a pessoa saiu da lista, leva o foco
export default function MemberItem({ habitId, member, isSelf, manage, timeZone, onDone }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const panelId = useId();
  const removeRef = useRef(null);
  const [confirming, setConfirming] = useState(false);
  const { email, id: userId } = member.user;

  const roleChange = useMutation({
    mutationFn: (role) => changeMemberRole(habitId, userId, role),
    onSuccess: (updated) => {
      updateMembers(queryClient, habitId, userId, updated);
      onDone(t(`sharing.members.role_changed.${updated.role}`, { email }));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: sharingKeys.members(habitId) }),
  });

  const removal = useMutation({
    mutationFn: () => removeMember(habitId, userId),
    onSuccess: () => {
      updateMembers(queryClient, habitId, userId, null);
      onDone(t('sharing.members.removed', { email }), { removed: true });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: sharingKeys.members(habitId) }),
  });

  const busy = roleChange.isPending || removal.isPending;

  const openConfirm = () => {
    roleChange.reset();
    removal.reset();
    setConfirming(true);
  };

  const closeConfirm = () => {
    setConfirming(false);
    removal.reset();
    removeRef.current?.focus();
  };

  return (
    <li className={styles.item}>
      <p className={styles.itemTitle}>
        <span className="user-text">{email}</span>
        <span className={styles.badge}>{t(`sharing.role.${member.role}`)}</span>
        {isSelf && <span className={styles.badge}>{t('sharing.members.you')}</span>}
      </p>
      <p className={styles.meta}>
        {t(member.role === 'owner' ? 'sharing.members.owner_since' : 'sharing.members.since', {
          date: formatDate(member.joined_at, timeZone, i18n.resolvedLanguage),
        })}
      </p>

      {manage && (
        <>
          <div className={styles.buttons} role="group" aria-label={t('sharing.members.actions', { email })}>
            <button
              type="button"
              className={styles.button}
              disabled={busy}
              onClick={() => {
                removal.reset();
                roleChange.mutate(OTHER_ROLE[member.role]);
              }}
            >
              {t(`sharing.members.make.${OTHER_ROLE[member.role]}`)}
            </button>
            <button
              ref={removeRef}
              type="button"
              className={styles.button}
              aria-expanded={confirming}
              aria-controls={confirming ? panelId : undefined}
              disabled={busy}
              onClick={confirming ? closeConfirm : openConfirm}
            >
              {t('sharing.members.remove')}
            </button>
          </div>
          {roleChange.error && <ErrorMessage error={roleChange.error} />}
          {confirming && (
            <ConfirmPanel
              id={panelId}
              title={t('sharing.members.remove_title', { email })}
              confirmLabel={t('sharing.members.remove_confirm')}
              pending={removal.isPending}
              error={removal.error}
              onConfirm={() => removal.mutate()}
              onCancel={closeConfirm}
            >
              <p>{t('sharing.members.remove_warning')}</p>
            </ConfirmPanel>
          )}
        </>
      )}
    </li>
  );
}

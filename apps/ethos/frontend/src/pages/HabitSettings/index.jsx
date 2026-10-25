import { useEffect, useId, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { forgetHabit, useDeleteHabit, useHabitStatus, useUpdateHabit } from '../../api/habits';
import ErrorMessage from '../../components/ErrorMessage';
import HabitForm from '../../components/HabitForm';
import useHabitContext from '../../hooks/useHabitContext';
import { PATHS, habitPath } from '../../paths';
import styles from './styles.module.css';

// Ações de status que cada status oferece (as outras a API recusa ou não mudam nada)
const STATUS_ACTIONS = {
  active: ['pause', 'archive'],
  paused: ['resume', 'archive'],
  archived: ['unarchive'],
};

// Configuração do hábito (`/habits/:habitId/settings`), só para o dono: o formulário, pausar,
// retomar, arquivar, desarquivar e apagar. Quem não é dono volta para o calendário (o link nem
// aparece no submenu; a API também recusa, com 403)
export default function HabitSettings() {
  const { habit } = useHabitContext();
  if (habit.role !== 'owner') return <Navigate to={habitPath(habit.id)} replace />;
  return <SettingsScreen habit={habit} />;
}

function SettingsScreen({ habit }) {
  const { t } = useTranslation();
  const update = useUpdateHabit(habit.id);
  const archived = habit.status === 'archived';
  const titleId = useId();

  return (
    <>
      <section className={styles.section} aria-labelledby={titleId}>
        <h2 id={titleId} className={styles.title}>
          {t('habit_settings.title')}
        </h2>
        {archived && <p className={styles.notice}>{t('habit_settings.archived_notice')}</p>}
        <HabitForm
          habit={habit}
          disabled={archived}
          pending={update.isPending}
          error={update.error}
          submitLabel={t('habit_settings.save')}
          onSubmit={(values) => update.mutate(values)}
          onEdit={() => {
            if (update.isSuccess) update.reset();
          }}
        />
        <p className={styles.status} role="status">
          {update.isSuccess ? t('habit_settings.saved') : ''}
        </p>
      </section>
      <StatusActions habit={habit} />
      <DeleteHabit habit={habit} />
    </>
  );
}

function StatusActions({ habit }) {
  const { t } = useTranslation();
  const titleId = useId();
  const status = useHabitStatus(habit.id);
  const actions = STATUS_ACTIONS[habit.status] ?? [];
  const listRef = useRef(null);
  // Status de quando a ação foi pedida (null: nenhuma em andamento)
  const statusBefore = useRef(null);

  // O botão clicado some quando o status muda (pausar vira retomar): quando o status novo chega e
  // os botões voltam a funcionar, o foco vai para a primeira ação dele, em vez de cair no começo
  // da página. A resposta e o fim da escrita podem chegar em renders diferentes
  useEffect(() => {
    if (statusBefore.current === null || status.isPending) return;
    if (status.isError) {
      statusBefore.current = null;
      return;
    }
    if (habit.status === statusBefore.current) return;
    statusBefore.current = null;
    listRef.current?.querySelector('button')?.focus();
  }, [habit.status, status.isPending, status.isError]);

  const run = (action) => {
    statusBefore.current = habit.status;
    status.mutate(action);
  };

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        {t('habit_settings.status.title')}
      </h2>
      <p className={styles.muted}>{t(`habit_settings.status.current.${habit.status}`)}</p>
      <ul ref={listRef} className={styles.actions}>
        {actions.map((action) => (
          <li key={action}>
            <button
              type="button"
              className={styles.button}
              disabled={status.isPending}
              onClick={() => run(action)}
            >
              {t(`habit_settings.status.${action}`)}
            </button>
            <p className={styles.hint}>{t(`habit_settings.status.${action}_hint`)}</p>
          </li>
        ))}
      </ul>
      {status.error && <ErrorMessage error={status.error} />}
      <p className={styles.status} role="status">
        {status.isSuccess ? t(`habit_settings.status.${status.variables}_done`) : ''}
      </p>
    </section>
  );
}

// Apagar pede confirmação num segundo passo, com o aviso de que as marcações de todos (inclusive
// dos convidados) somem junto. Depois, volta para a tela inicial
function DeleteHabit({ habit }) {
  const { t } = useTranslation();
  const titleId = useId();
  const confirmTitleId = useId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const remove = useDeleteHabit(habit.id);
  const [confirming, setConfirming] = useState(false);
  const panelRef = useRef(null);
  const openRef = useRef(null);
  const reopened = useRef(false);

  // Ao abrir a confirmação, o foco vai para ela (o leitor de tela lê o aviso); ao cancelar, volta
  // para o botão que a abriu
  useEffect(() => {
    if (confirming) panelRef.current?.focus();
    else if (reopened.current) openRef.current?.focus();
  }, [confirming]);

  const cancel = () => {
    reopened.current = true;
    remove.reset();
    setConfirming(false);
  };

  const confirm = () => {
    remove.mutate(undefined, {
      onSuccess: async () => {
        await navigate(PATHS.home, { replace: true });
        forgetHabit(queryClient, habit.id);
      },
    });
  };

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        {t('habit_settings.delete.title')}
      </h2>
      {!confirming ? (
        <>
          <p className={styles.muted}>{t('habit_settings.delete.hint')}</p>
          <div>
            <button ref={openRef} type="button" className={styles.button} onClick={() => setConfirming(true)}>
              {t('habit_settings.delete.open')}
            </button>
          </div>
        </>
      ) : (
        <div
          ref={panelRef}
          className={styles.confirm}
          role="group"
          aria-labelledby={confirmTitleId}
          tabIndex={-1}
        >
          <h3 id={confirmTitleId} className={styles.confirmTitle}>
            {t('habit_settings.delete.confirm_title', { habit: habit.label })}
          </h3>
          <p>{t('habit_settings.delete.warning')}</p>
          {remove.error && <ErrorMessage error={remove.error} />}
          <div className={styles.buttons}>
            <button type="button" className={styles.danger} disabled={remove.isPending} onClick={confirm}>
              {remove.isPending ? t('habit_settings.delete.deleting') : t('habit_settings.delete.confirm')}
            </button>
            <button type="button" className={styles.button} disabled={remove.isPending} onClick={cancel}>
              {t('habit_settings.delete.cancel')}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

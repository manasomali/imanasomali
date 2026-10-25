import { Link, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useCreateHabit } from '../../api/habits';
import HabitForm from '../../components/HabitForm';
import HabitTabs from '../../components/HabitTabs';
import PageTitle from '../../components/PageTitle';
import { PATHS, habitPath } from '../../paths';
import page from '../page.module.css';
import styles from './styles.module.css';

// Criar um hábito (`/habits/new`), com o mesmo formulário da configuração. Criado, abre a aba
// dele. No limite de hábitos ativos e pausados, a API responde 409 `habit_limit_reached` e a
// mensagem diz o que fazer (arquivar ou apagar um)
export default function NewHabit() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const create = useCreateHabit();
  const title = t('new_habit.title');

  const submit = (values) =>
    create.mutate(values, {
      onSuccess: (habit) => navigate(habitPath(habit.id)),
    });

  return (
    <>
      <PageTitle title={title} />
      <h1 className={page.title}>{title}</h1>
      <HabitTabs />
      <p className={styles.intro}>{t('new_habit.intro')}</p>
      <HabitForm
        pending={create.isPending}
        error={create.error}
        submitLabel={t('new_habit.create')}
        onSubmit={submit}
      />
      <p className={styles.back}>
        <Link to={PATHS.home}>{t('new_habit.back')}</Link>
      </p>
    </>
  );
}

import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import HabitSwatch from '../../components/HabitSwatch';
import { formatDateTime } from '../../lib/datetime';
import { describeEvent } from '../../lib/history';
import { habitPath } from '../../paths';
import styles from './styles.module.css';

// Um evento do histórico: quando (no fuso da conta), o hábito (link para a aba dele, com a cor
// quando o hábito está nas listas carregadas), o que aconteceu, os detalhes e quem fez ("usuário
// removido" quando a conta foi apagada). Focável pelo script (tabIndex -1): recebe o foco quando
// chega com "carregar mais"
export default function EventItem({ entry, color, context }) {
  const { t } = useTranslation();
  const { text, lines } = describeEvent(entry, context);
  const author = entry.author?.email ?? t('history.removed_user');

  return (
    <li className={styles.event} tabIndex={-1}>
      <div className={styles.meta}>
        <time dateTime={entry.created_at}>
          {formatDateTime(entry.created_at, context.timeZone, context.language)}
        </time>
        <Link to={habitPath(entry.habit.id)} className={`${styles.habit} user-text`}>
          <HabitSwatch className={styles.swatch} color={color} />
          {entry.habit.label}
        </Link>
      </div>
      <p className={styles.text}>{text}</p>
      {lines.length > 0 && (
        <ul className={`${styles.lines} user-text`}>
          {lines.map((line, index) => (
            // Linhas fixas de um evento que não muda: o índice basta como chave
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
      <p className={entry.author ? styles.author : `${styles.author} ${styles.removed}`}>
        {t('history.by', { person: author })}
      </p>
    </li>
  );
}

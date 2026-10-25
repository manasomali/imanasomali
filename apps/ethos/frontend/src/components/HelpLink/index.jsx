import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiHelpCircle } from 'react-icons/fi';
import { helpPath } from '../../paths';
import styles from './styles.module.css';

const ICON_SIZE = 20;

/**
 * Ícone de ajuda que abre a seção `section` da ajuda (um id de HELP_SECTIONS) em outra aba, para
 * não perder o que a pessoa está preenchendo. `topic` é o assunto no nome acessível ("Ajuda:
 * Alertas (abre em outra aba)"), normalmente o título da tela ou da seção ao lado.
 */
export default function HelpLink({ section, topic }) {
  const { t } = useTranslation();
  const label = t('help.link', { topic });

  return (
    <Link
      to={helpPath(section)}
      target="_blank"
      rel="noopener"
      className={styles.link}
      aria-label={label}
      title={label}
    >
      <FiHelpCircle aria-hidden size={ICON_SIZE} />
    </Link>
  );
}

/** Um título (`children`, o elemento do título) com o ícone de ajuda ao lado. */
export function WithHelp({ section, topic, children }) {
  return (
    <div className={styles.row}>
      {children}
      <HelpLink section={section} topic={topic} />
    </div>
  );
}

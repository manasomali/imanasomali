import { Link, NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiMoon, FiSun } from 'react-icons/fi';
import { useSignedInMe } from '../../api/account';
import useTheme from '../../hooks/useTheme';
import { LANGUAGES } from '../../i18n';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

const ICON_SIZE = 20;

// Topo de todas as telas: marca, links (conta, admin só para is_admin com os termos aceitos, volta
// ao site), idioma da tela e tema. O idioma daqui é só o da tela (chave i18nextLng compartilhada);
// o da conta, usado nos emails, muda na tela de conta. Não busca nada: lê o /me já carregado
export default function Header() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const me = useSignedInMe();
  const navClass = ({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`;

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link to={PATHS.account} className={styles.brand}>
          imago
        </Link>

        <nav aria-label={t('a11y.main_navigation')} className={styles.nav}>
          <ul className={styles.links}>
            <li>
              <NavLink to={PATHS.account} end className={navClass}>
                {t('menu.account')}
              </NavLink>
            </li>
            {/* Esconder o link é conveniência: a rota redireciona e o backend recusa (403) */}
            {me?.is_admin && !me.terms_pending && (
              <li>
                <NavLink to={PATHS.admin} className={navClass}>
                  {t('menu.admin')}
                </NavLink>
              </li>
            )}
            <li>
              {/* Fora do basename: link comum, recarrega a página no site */}
              <a href="/" className={`${styles.navLink} ${styles.site}`}>
                {t('menu.back_to_site')}
              </a>
            </li>
          </ul>
        </nav>

        <div className={styles.controls}>
          <div className={styles.languages} role="group" aria-label={t('a11y.language')}>
            {LANGUAGES.map((lng) => (
              <button
                key={lng}
                type="button"
                lang={lng}
                className={styles.language}
                aria-pressed={i18n.resolvedLanguage === lng}
                onClick={() => i18n.changeLanguage(lng)}
              >
                {lng}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={styles.iconButton}
            aria-label={theme === 'dark' ? t('a11y.light_theme') : t('a11y.dark_theme')}
            onClick={toggleTheme}
          >
            {theme === 'dark' ? <FiSun aria-hidden size={ICON_SIZE} /> : <FiMoon aria-hidden size={ICON_SIZE} />}
          </button>
        </div>
      </div>
    </header>
  );
}

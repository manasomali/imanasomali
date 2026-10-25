import { useEffect, useState } from 'react';
import { NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiArrowLeft, FiMenu, FiMoon, FiSun, FiX } from 'react-icons/fi';
import { useCachedMe } from '../../api/auth';
import { useReceivedInvites } from '../../api/sharing';
import useTheme from '../../hooks/useTheme';
import { LANGUAGES } from '../../i18n';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

const ICON_SIZE = 20;

const links = [
  { to: PATHS.home, i18nKey: 'menu.habits', end: true },
  { to: PATHS.report, i18nKey: 'menu.report' },
  { to: PATHS.invites, i18nKey: 'menu.invites', pending: true },
  { to: PATHS.account, i18nKey: 'menu.account' },
];

// Só para admin. Esconder o link é conveniência: a rota redireciona e o backend recusa (403)
const adminLink = { to: PATHS.admin, i18nKey: 'menu.admin' };

export default function Menu() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const me = useCachedMe();
  const visibleLinks = me?.is_admin ? [...links, adminLink] : links;
  // Convites pendentes: só com a sessão carregada e os termos aceitos (senão a API recusa). Falha
  // ao buscar não mostra nada; a tela de convites mostra o erro. Cache em src/api/sharing.js
  const received = useReceivedInvites({ enabled: Boolean(me) && !me.terms_pending });
  const pending = received.data?.length ?? 0;

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  const close = () => setOpen(false);
  const navClass = ({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`;

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <NavLink to={PATHS.home} end className={styles.brand} onClick={close}>
          ethos
        </NavLink>

        <button
          type="button"
          className={`${styles.iconButton} ${styles.toggle}`}
          aria-expanded={open}
          aria-controls="ethos-menu"
          aria-label={open ? t('a11y.close_menu') : t('a11y.open_menu')}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <FiX aria-hidden size={ICON_SIZE} /> : <FiMenu aria-hidden size={ICON_SIZE} />}
        </button>

        <div id="ethos-menu" className={styles.panel} data-open={open}>
          <nav aria-label={t('a11y.main_navigation')}>
            <ul className={styles.links}>
              {visibleLinks.map((link) => (
                <li key={link.to}>
                  <NavLink to={link.to} end={link.end} className={navClass} onClick={close}>
                    {t(link.i18nKey)}
                    {link.pending && pending > 0 && (
                      <>
                        <span className={styles.count} aria-hidden="true">
                          {pending}
                        </span>{' '}
                        <span className="visually-hidden">{t('menu.invites_pending', { count: pending })}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
              <li>
                {/* Fora do basename: link comum, recarrega a página no site */}
                <a href="/" className={`${styles.navLink} ${styles.site}`}>
                  <FiArrowLeft aria-hidden size={16} />
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
      </div>
    </header>
  );
}

import { useEffect, useState } from 'react';
import { NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import { FiArrowLeft, FiMenu, FiMoon, FiSun, FiX } from 'react-icons/fi';
import useTheme from '../../hooks/useTheme';
import { LANGUAGES } from '../../i18n';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

const ICON_SIZE = 20;

const links = [
  { to: PATHS.home, i18nKey: 'menu.habits', end: true },
  { to: PATHS.account, i18nKey: 'menu.account' },
];

export default function Menu() {
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const [open, setOpen] = useState(false);

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
              {links.map((link) => (
                <li key={link.to}>
                  <NavLink to={link.to} end={link.end} className={navClass} onClick={close}>
                    {t(link.i18nKey)}
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

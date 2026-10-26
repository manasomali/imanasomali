import { useEffect, useState } from 'react';
import { NavLink } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  FiMenu, FiMoon, FiSun, FiX,
} from 'react-icons/fi';
import useTheme from '../../hooks/useTheme';
import styles from './styles.module.css';

const links = [
  { to: '/about', i18nKey: 'menu.about' },
  { to: '/apps', i18nKey: 'menu.apps' },
  { to: '/projects', i18nKey: 'menu.projects' },
  { to: '/publications', i18nKey: 'menu.publications' },
];

const languages = ['pt', 'en'];

function Menu() {
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

  const navClass = ({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ''}`;

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <NavLink to="/" end className={navClass} onClick={() => setOpen(false)}>
          MATHEUS NASCIMENTO
        </NavLink>

        <button
          type="button"
          className={`${styles.iconButton} ${styles.toggle}`}
          aria-expanded={open}
          aria-controls="site-menu"
          aria-label={open ? t('a11y.close_menu') : t('a11y.open_menu')}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <FiX aria-hidden /> : <FiMenu aria-hidden />}
        </button>

        <div id="site-menu" className={styles.panel} data-open={open}>
          <nav aria-label={t('a11y.main_navigation')}>
            <ul className={styles.links}>
              {links.map((link) => (
                <li key={link.to}>
                  <NavLink to={link.to} className={navClass} onClick={() => setOpen(false)}>
                    {t(link.i18nKey)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <div className={styles.controls}>
            <div className={styles.languages} role="group" aria-label={t('a11y.language')}>
              {languages.map((lng) => (
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
              {theme === 'dark' ? <FiSun aria-hidden /> : <FiMoon aria-hidden />}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

export default Menu;

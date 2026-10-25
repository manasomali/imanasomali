import { NavLink, useMatch } from 'react-router';
import { useTranslation } from 'react-i18next';
import { PATHS } from '../../paths';
import styles from './admin.module.css';

// Abas do painel de admin: contas (com o conteúdo dos hábitos de cada uma) e banners
export default function AdminNav() {
  const { t } = useTranslation();
  // O conteúdo dos hábitos de uma conta fica sob a aba de contas
  const onAccount = useMatch(PATHS.adminUser) !== null;
  const tabClass = (active) => `${styles.tab} ${active ? styles.tabActive : ''}`;

  return (
    <nav aria-label={t('admin.navigation')} className={styles.nav}>
      <NavLink to={PATHS.admin} end className={({ isActive }) => tabClass(isActive || onAccount)}>
        {t('admin.nav.accounts')}
      </NavLink>
      <NavLink to={PATHS.adminBanners} className={({ isActive }) => tabClass(isActive)}>
        {t('admin.nav.banners')}
      </NavLink>
    </nav>
  );
}

import { useTranslation } from 'react-i18next';
import PageDefault from '../../components/PageDefault';
import Social from '../../components/Social';
import Avatar from '../../assets/avatar.jpg';
import styles from './styles.module.css';

function Main() {
  const { t } = useTranslation();

  return (
    <PageDefault centered>
      <div className={styles.hero}>
        <img className={styles.avatar} src={Avatar} alt="Matheus Nascimento" width="300" height="300" fetchPriority="high" />
        <Social />
        <div className={styles.identity}>
          <h1 className={styles.name}>Matheus Nascimento Soares Marques de Lima</h1>
          <p className={styles.occupation}>
            <span>{t('pages.main.ocupation1')}</span>
            <span>{t('pages.main.ocupation2')}</span>
          </p>
        </div>
      </div>
    </PageDefault>
  );
}

export default Main;

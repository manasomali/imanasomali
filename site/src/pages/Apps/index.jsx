import { useTranslation } from 'react-i18next';
import Title from '../../components/Title';
import Project from '../../components/Project';
import PageDefault from '../../components/PageDefault';
import apps from '../../data/apps';
import styles from './styles.module.css';

function Apps() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.apps.title')} width="wide">
      <Title>{t('pages.apps.title')}</Title>
      <div className={styles.grid}>
        {apps.map((item) => (
          <Project
            key={item.key}
            title={t(`pages.apps.items.${item.key}.title`)}
            subtitle={t(`pages.apps.items.${item.key}.subtitle`)}
            year={item.year}
            description={t(`pages.apps.items.${item.key}.description`)}
            link={item.link}
            image={item.image}
            imageAlt={t(`pages.apps.items.${item.key}.image_alt`)}
            sameTab
          />
        ))}
      </div>
    </PageDefault>
  );
}

export default Apps;

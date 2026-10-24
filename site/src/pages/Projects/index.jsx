import { useTranslation } from 'react-i18next';
import Title from '../../components/Title';
import Project from '../../components/Project';
import PageDefault from '../../components/PageDefault';
import projects from '../../data/projects';
import styles from './styles.module.css';

function Projects() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.projects.title')} width="wide">
      <Title>{t('pages.projects.title')}</Title>
      <div className={styles.grid}>
        {projects.map((item) => (
          <Project
            key={item.key}
            title={t(`pages.projects.items.${item.key}.title`)}
            description={t(`pages.projects.items.${item.key}.description`)}
            link={item.link}
            image={item.image}
          />
        ))}
      </div>
    </PageDefault>
  );
}

export default Projects;

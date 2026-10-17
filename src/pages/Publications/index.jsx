import { useTranslation } from 'react-i18next';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import ListPublications from '../../components/ListPublications';

function Publications() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.publications.title')} width="wide">
      <Title>{t('pages.publications.title')}</Title>
      <ListPublications />
    </PageDefault>
  );
}

export default Publications;

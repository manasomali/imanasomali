import { useTranslation } from 'react-i18next';
import PageDefault from '../../components/PageDefault';
import Summary from '../../components/Summary';
import Title from '../../components/Title';
import Experience from '../../components/Experience';

function About() {
  const { t } = useTranslation();
  return (
    <PageDefault title={t('pages.about.title')}>
      <Title>{t('pages.about.title')}</Title>
      <Summary />
      <Experience />
    </PageDefault>
  );
}

export default About;

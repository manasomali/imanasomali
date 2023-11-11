import React from 'react';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import ListPublications from '../../components/ListPublications';
import { useTranslation } from 'react-i18next';

function Publications() {
  const { t, i18n } = useTranslation();

  return (
    <>
        <PageDefault>
            <Title>
              {t('pages.publications.title')}
            </Title>
            <ListPublications />
        </PageDefault>
    </>
  );
}

export default Publications;
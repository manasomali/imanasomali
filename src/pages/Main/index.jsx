import React from 'react';
import ImageRound from '../../components/ImageRound';
import PageDefault from '../../components/PageDefault';
import Social from '../../components/Social';
import Name from '../../components/Name';
import Ocupation from '../../components/Ocupation';
import Avatar from '../../assets/avatar.jpg'
import { useTranslation } from 'react-i18next';

function Main() {
  const { t, i18n } = useTranslation();

  return (
    <>
      <PageDefault>
          <ImageRound src={Avatar}/>
          <Social />
          <Name>Matheus Nascimento Soares Marques de Lima</Name>
          <Ocupation>{t('pages.main.ocupation1')}</Ocupation>
          <Ocupation>{t('pages.main.ocupation2')}</Ocupation>
          <Ocupation></Ocupation>
      </PageDefault>
    </>
  );
}

export default Main;
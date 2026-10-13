import React from 'react';
import { Link as RouterLink } from 'react-router-dom';
import PageDefault from '../../components/PageDefault';
import Title from '../../components/Title';
import Link from '../../components/Link';
import Iframe from 'react-iframe';
import { useTranslation } from 'react-i18next';

function Page404() {
  const { t } = useTranslation();
  return (
    <>
        <PageDefault>
            <Title>{t('pages.page404.title')}</Title>
            <p>{t('pages.page404.message')}</p>
            <p><Link as={RouterLink} to="/" fontSize="18px">{t('pages.page404.back')}</Link></p>
            <Iframe url="https://media.tenor.com/2g8VHWu_d4UAAAAC/cake-i-do-not-want-cake.gif/"
            title="404"
            width = "100%"
            height = "384"
            />
        </PageDefault>
    </>
  );
}

export default Page404;

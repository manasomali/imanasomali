import React from 'react';
import PageDefault from '../../components/PageDefault';
import Summary from '../../components/Summary';
import Title from '../../components/Title';
import Experience from '../../components/Experience';
import { useTranslation } from 'react-i18next';

function About() {
    const { t, i18n } = useTranslation();
    return (
        <>
            <PageDefault>
                <Title>
                    {t('pages.about.title')}
                </Title>
                <Summary />
                <Experience />
            </PageDefault>
        </>
    );
}

export default About;
import React from 'react';
import styled from 'styled-components';
import { useTranslation } from 'react-i18next';

const Description = styled.div`
    text-align: justify;
    font-size: 18px;
    width: 100%;
    margin-left: 20px;
    margin-bottom: 20px;
`;

const SubTitle = styled.h2`
    text-align: left;
    display: block;
    font-size: 1.5em;
    margin-top: 0.83em;
    margin-bottom: 0.83em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    padding-top: 0;
    margin-bottom: 0;
    margin-left: 10px;
`;
const Ano = styled.h3`
    text-align: left;
    display: block;
    font-size: 1.17em;
    margin-top: 1em;
    margin-bottom: 1em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    margin-bottom: 0px;
    margin-left: 20px;
    margin-top:0;

`;
const Title = styled.h1`
    text-align: left;
    font-size: 2em;
    margin-top: 0.67em;
    margin-bottom: 0.67em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    padding-top: 40px;
    margin-top: 0;
`;

function Experience() {
    const { t, i18n } = useTranslation();

    return (
        <>
            <Title>{t('components.experience.title')}</Title>
            <SubTitle>{t('components.experience.role1')}</SubTitle>
            <Ano>{t('components.experience.year1')}</Ano>
            <Description>
            {t('components.experience.description1.description')}
                <i>
                <ul>
                    <li>{t('components.experience.description1.item1')}</li>
                    <li>{t('components.experience.description1.item2')}</li>
                    <li>{t('components.experience.description1.item3')}</li>
                    <li>{t('components.experience.description1.item4')}</li>
                </ul>
                </i>
            </Description>

            <SubTitle>{t('components.experience.role2')}</SubTitle>
            <Ano>{t('components.experience.year2')}</Ano>
            <Description>
                {t('components.experience.description2.description')}
                <i>
                <ul>
                    <li>{t('components.experience.description2.item1')}</li>
                    <li>{t('components.experience.description2.item2')}</li>
                    <li>{t('components.experience.description2.item3')}</li>
                    <li>{t('components.experience.description2.item4')}</li>
                </ul>
                </i>
            </Description>

            <SubTitle>{t('components.experience.role3')}</SubTitle>
            <Ano>{t('components.experience.year3')}</Ano>
            <Description>
            {t('components.experience.description3.description')}
                <i>
                <ul>
                    <li>{t('components.experience.description3.item1')}</li>
                    <li>{t('components.experience.description3.item2')}</li>
                    <li>{t('components.experience.description3.item3')}</li>
                    <li>{t('components.experience.description3.item4')}</li>
                    <li>{t('components.experience.description3.item5')}</li>
                    <li>{t('components.experience.description3.item6')}</li>
                    <li>{t('components.experience.description3.item7')}</li>
                </ul>
                </i>
            </Description>
            <SubTitle>{t('components.experience.role4')}</SubTitle>
            <Ano>{t('components.experience.description4.year1')}</Ano>
            <Description>{t('components.experience.description4.item1')}</Description>
            <Ano>{t('components.experience.description4.year2')}</Ano>
            <Description>{t('components.experience.description4.item2')}</Description>
            <Ano>{t('components.experience.description4.year3')}</Ano>
            <Description>{t('components.experience.description4.item3')}</Description>


        </>
    )
}
export default Experience

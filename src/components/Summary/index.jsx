import React from 'react';
import styled from 'styled-components';
import Link from '../Link';
import { useTranslation } from 'react-i18next';

const Description = styled.div`
    text-align: justify;
    font-size: 20px;
    width: 100%;
`;

function Summary() {
    const { t, i18n } = useTranslation();
    return (
        <>
            <Description>
                {t('components.summary.line1.sector1')}
                <Link fontSize="20px" href="http://florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line1.IFSC')}</Link>
                {t('components.summary.line1.sector2')}
                <Link fontSize="20px" href="https://gese.florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line1.GESE')}</Link>  
                {t('components.summary.line1.sector3')}
                <Link fontSize="20px" href="https://www.digitalhouse.com/br" target="_blank" rel="noopener noreferrer">{t('components.summary.line1.DH')}</Link>
                {t('components.summary.line1.sector4')}
                <Link fontSize="20px" href="https://www.opet.com.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line1.Opet')}</Link>
                <br />
                <br />
                {t('components.summary.line2.sector1')}
                <Link fontSize="20px" href="https://www.byne.com.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line2.BYNE')}</Link>
                {t('components.summary.line2.sector2')}
                <Link fontSize="20px" href="https://www.engie.com.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line2.engie')}</Link>
                {t('components.summary.line2.sector3')}
                <Link fontSize="20px" href="http://www.ons.org.br" target="_blank" rel="noopener noreferrer">{t('components.summary.line2.ONS')}</Link>
                {t('components.summary.line2.sector4')}
                <br />
                <br />
                {t('components.summary.line3')}
            </Description>
        </>
    )
}
export default Summary

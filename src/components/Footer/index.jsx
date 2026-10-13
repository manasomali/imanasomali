import React from 'react';
import Link from '../Link';
import {FooterBase} from './styles';
import { useTranslation } from 'react-i18next';

function Footer() {
  const { t, i18n } = useTranslation();
  return (
    <FooterBase>
        <div>{t('components.footer.line1')} Matheus Nascimento</div>
        <div>{t('components.footer.line2')} <Link href="https://vite.dev/" target="_blank" rel="noopener noreferrer">Vite</Link> + <Link href="https://react.dev/" target="_blank" rel="noopener noreferrer">React</Link></div>
        <div>{t('components.footer.line3')} <Link href="https://github.com/naro143/hugo-coder-portfolio" target="_blank" rel="noopener noreferrer">Yusuke Ishimi</Link></div>
    </FooterBase>
  );
}

export default Footer;
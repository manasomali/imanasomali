import React from 'react';
import Link from '../Link';
import {FooterBase} from './styles';
import { useTranslation } from 'react-i18next';

function Footer() {
  const { t, i18n } = useTranslation();
  return (
    <FooterBase>
        <div>{t('components.footer.line1')} Matheus Nascimento</div>
        <div>{t('components.footer.line2')} <Link href="https://vitejs.dev/" target="_blank">Vite</Link> + <Link href="https://pt-br.reactjs.org" target="_blank">React</Link></div>
        <div>{t('components.footer.line3')} <Link href="https://blog.naro143.com" target="_blank">Yusuke Ishimi</Link></div>
    </FooterBase>
  );
}

export default Footer;
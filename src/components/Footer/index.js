import React from 'react';
import Link from '../Link';
import {FooterBase} from './styles';

function Footer() {
  return (
    <FooterBase>
        <div>Desenvolvido por Matheus Nascimento</div>
        <div>Usando <Link href="https://pt-br.reactjs.org" target="_blank">React</Link></div>
        <div>Inspirado por <Link href="https://blog.naro143.com" target="_blank">Yusuke Ishimi</Link></div>
    </FooterBase>
  );
}

export default Footer;
import React from 'react';
import Link from '../Link';
import {FooterBase} from './styles';

function Footer() {
  return (
    <FooterBase>
        <div>Developed by Matheus Nascimento</div>
        <div>Using <Link href="https://pt-br.reactjs.org" target="_blank">React</Link></div>
        <div>2020</div>
    </FooterBase>
  );
}

export default Footer;
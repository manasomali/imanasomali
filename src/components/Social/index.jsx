import React from 'react';
import { Github } from '@styled-icons/simple-icons/Github';
import { Gmail } from '@styled-icons/simple-icons/Gmail';
import { GraduationCap } from '@styled-icons/fa-solid/GraduationCap';
import { Instagram } from '@styled-icons/simple-icons/Instagram';
import { Letterboxd } from '@styled-icons/simple-icons/Letterboxd';
import { Trakt } from '@styled-icons/simple-icons/Trakt';
import { Myanimelist } from '@styled-icons/simple-icons/Myanimelist';

import './Social.css'
import styled from 'styled-components';

const Icon = styled.a`
    cursor: pointer;
    &::after {
        content: '';
        display: block;
        width: 0;
        height: 2px;
        background: #000;
        transition: width .3s;
    }
    &:hover::after {
        width: 100%;
    }
`;

function Social() {
    return (
        <nav className="Social" >
            <Icon href="https://github.com/manasomali" rel="noopener noreferrer" target="_blank">
                <Github size="48" />
            </Icon>
            <Icon href="https://mail.google.com/mail/?view=cm&fs=1&to=matheus.nascimento.marques@gmail.com" className="wide" rel="noopener noreferrer" target="_blank">
                <Gmail size="48" />
            </Icon>
            <Icon href="http://lattes.cnpq.br/2299260238389056" className="wide" rel="noopener noreferrer" target="_blank">
                <GraduationCap size="48" />
            </Icon>
            <Icon href="https://www.instagram.com/mat.n96/" rel="noopener noreferrer" target="_blank">
                <Instagram size="48" />
            </Icon>
            <Icon href="https://letterboxd.com/manasomali/" rel="noopener noreferrer" target="_blank">
                <Letterboxd size="48" />
            </Icon>
            <Icon href="https://app.trakt.tv/profile/manasomali?share=lkXUvi1B6rPK" rel="noopener noreferrer" target="_blank">
                <Trakt size="48" />
            </Icon>
            <Icon href="https://myanimelist.net/profile/manasomali" rel="noopener noreferrer" target="_blank">
                <span className="badge"><Myanimelist size="48" /></span>
            </Icon>
        </nav>
    )
}
export default Social
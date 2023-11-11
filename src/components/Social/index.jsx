import React from 'react';
import { Github } from '@styled-icons/boxicons-logos/Github';
import { Gmail } from '@styled-icons/simple-icons/Gmail';
import { Linkedin } from '@styled-icons/boxicons-logos/Linkedin';
import { GraduationCap } from '@styled-icons/fa-solid/GraduationCap';
import { Instagram } from '@styled-icons/boxicons-logos/Instagram';
import { Letterboxd } from '@styled-icons/simple-icons/Letterboxd';
import { Tvtime } from '@styled-icons/simple-icons/Tvtime';
import { Myanimelist } from '@styled-icons/simple-icons/Myanimelist';

import './Social.css'
import styled from 'styled-components';

const Icon = styled.a`
    cursor: pointer;
    margin-right: 10px;
    margin-left: 10px;
    margin-bottom: 10px;
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
            <Icon href="https://mail.google.com/mail/?view=cm&fs=1&to=matheus.nascimento.marques@gmail.com" rel="noopener noreferrer" target="_blank">
                <Gmail size="48" />
            </Icon>
            <Icon href="https://www.linkedin.com/in/manasomali/" rel="noopener noreferrer" target="_blank">
                <Linkedin size="48" />
            </Icon>
            <Icon href="http://lattes.cnpq.br/2299260238389056" rel="noopener noreferrer" target="_blank">
                <GraduationCap size="48" />
            </Icon>
            <Icon href="https://www.instagram.com/mat.n96/" rel="noopener noreferrer" target="_blank">
                <Instagram size="48" />
            </Icon>
            <Icon href="https://letterboxd.com/manasomali/" rel="noopener noreferrer" target="_blank">
                <Letterboxd size="48" />
            </Icon>
            <Icon href="https://www.tvtime.com/pt_BR/user/1459743/profile" rel="noopener noreferrer" target="_blank">
                <Tvtime size="48" />
            </Icon>
            <Icon href="https://myanimelist.net/profile/manasomali" rel="noopener noreferrer" target="_blank">
                <Myanimelist size="48" />
            </Icon>
        </nav>
    )
}
export default Social
import React from 'react';
import { Github } from '@styled-icons/boxicons-logos/Github';
import { Gmail } from '@styled-icons/simple-icons/Gmail';
import { Linkedin } from '@styled-icons/boxicons-logos/Linkedin';
import { GraduationCap } from '@styled-icons/fa-solid/GraduationCap';
import './Social.css'
import styled from 'styled-components';

const Icone = styled.a`
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
            <Icone href="https://github.com/manasomali" rel="noopener noreferrer" target="_blank">
                <Github size="48" />
            </Icone>
            <Icone href="https://mail.google.com/mail/?view=cm&fs=1&to=matheus.nascimento.marques@gmail.com" rel="noopener noreferrer" target="_blank">
                <Gmail size="48" />
            </Icone>
            <Icone href="https://www.linkedin.com/in/matheus-nascimento-904698128/" rel="noopener noreferrer" target="_blank">
                <Linkedin size="48" />
            </Icone>
            <Icone href="http://lattes.cnpq.br/2299260238389056" rel="noopener noreferrer" target="_blank">
                <GraduationCap size="48" />
            </Icone>
        </nav>
    )
}
export default Social
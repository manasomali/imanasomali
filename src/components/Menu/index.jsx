import React from 'react'
import { NavLink } from 'react-router-dom';
import './Menu.css'
import styled from 'styled-components'
import Link from '../Link'
import { useTranslation } from 'react-i18next';

const ButtonMenu = styled(NavLink)`
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    margin: 0px 24px 0px 24px;
    font-style: normal;
    font-weight: bold;
    font-size: 19px;
    outline: none;
    text-decoration: none;
    display: inline-block;
    transition: opacity .3s;
    border-bottom: 2px solid white;
    &:hover {
        border-bottom: 2px solid black;
        text-decoration:none;
        color:black;
    }
    &.selected {
        border-bottom: 2px solid black;
    }
`;
const LanguageMenu = styled.div`
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    margin: auto;
    font-style: normal;
    font-weight: bold;
    font-size: 19px;
    outline: none;
    text-decoration: none;
    display: inline-grid;
    columns: auto 1;
    transition: opacity .3s;
    border-bottom: 2px solid white;
    &.selected {
        border-bottom: 2px solid black;
    }
    vertical-align: middle;
`;


function Menu() {
    const { t, i18n } = useTranslation();

    return (
        <nav className="Menu" >
            <div>
                <ButtonMenu as={NavLink} exact activeClassName="selected" to="/"> MATHEUS NASCIMENTO </ButtonMenu>
            </div>
            <div>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/about"> {t('menu.about')} </ButtonMenu>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/projects"> {t('menu.projects')} </ButtonMenu>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/publications"> {t('menu.publications')} </ButtonMenu>
                <LanguageMenu>
                    <Link onClick={() => i18n.changeLanguage('pt')}>pt</Link>
                    <Link onClick={() => i18n.changeLanguage('en')}>en</Link>
                </LanguageMenu>
            </div>
        </nav>
    )
}
export default Menu
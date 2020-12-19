import React from 'react'
import { NavLink } from 'react-router-dom';
import './Menu.css'
import styled from 'styled-components'

const ButtonMenu = styled(NavLink)`
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    margin: 0px 24px 0px 24px;
    font-style: normal;
    font-weight: bold;
    font-size: 20px;
    outline: none;
    text-decoration: none;
    display: inline-block;
    transition: opacity .3s;
    border-bottom: 2px solid white;
    padding-bottom: 5px;
    padding-top: 5px;
    &:hover {
        border-bottom: 2px solid black;
    }
    &.selected {
        border-bottom: 2px solid black;
    }
`;

function Menu() {
    return (
        <nav className="Menu" >
            <div>
                <ButtonMenu as={NavLink} exact activeClassName="selected" to="/"> MATHEUS NASCIMENTO </ButtonMenu>
            </div>
            <div>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/sobre"> SOBRE </ButtonMenu>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/projetos"> PROJETOS </ButtonMenu>
                <ButtonMenu as={NavLink} activeClassName="selected" to="/publicacoes"> PUBLICAÇÕES </ButtonMenu>
            </div>
        </nav>
    )
}
export default Menu
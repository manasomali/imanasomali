import React from 'react'
import { NavLink } from 'react-router-dom';
import './Menu.css'
import styled from 'styled-components'

const ButtonMenu = styled(NavLink)`
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    padding: 16px 24px;
    font-style: normal;
    font-weight: bold;
    font-size: 20px;
    outline: none;
    border-radius: 5px;
    text-decoration: none;
    display: inline-block;
    transition: opacity .3s;
    &:hover,
    &:focus {
        opacity: .6;
        text-decoration: underline;
    }
    &.selected {
    text-decoration: underline;
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
                <ButtonMenu as={NavLink} activeClassName="selected" to="/portfolio"> PORTFÓLIO </ButtonMenu>
            </div>
        </nav>
    )
}
export default Menu
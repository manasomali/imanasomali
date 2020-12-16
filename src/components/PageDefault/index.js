import React from 'react'
import Menu from '../Menu'
import Footer from '../Footer'
import styled from 'styled-components';

const Body = styled.body`
  background-color: var(--white);
  color: var(--black);
  flex: 1;
  padding-top: 50px;
  padding-left: 5%;
  padding-right: 5%;
`;

function PageDefault({children}) {
    return (
        <>
            <Menu />
            <Body>
                {children}
            </Body>
            <Footer />
        </>
    )
}
export default PageDefault
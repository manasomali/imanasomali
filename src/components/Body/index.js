import React from 'react';
import styled from 'styled-components';

const Main = styled.main`
  background-color: var(--white);
  color: var(--black);
  flex: 1;
  padding-top: 50px;
  padding-left: 5%;
  padding-right: 5%;
`;


function Body() {
  return (
    <Main>
          Teste
    </Main>
  );
}

export default Body;
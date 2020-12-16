import React from 'react';
import Iframe from 'react-iframe';
import styled from 'styled-components';

const Center = styled.div`
    position: absolute;
    height: 100%;
    width: 90%;
    margin-left: auto;
    margin-right: auto;
`;

function Game() {
    return (
      <Center>
          <Iframe url="https://manasomali.github.io/jogo-redsquare/"
            width = "100%"
            height = "507px"
            />
      </Center>
    );
  }
  
  export default Game;
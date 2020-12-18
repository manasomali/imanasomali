import React from 'react';
import PageDefault from '../../components/PageDefault';
import Iframe from 'react-iframe';

function Pagina404() {
  return (
    <>
        <PageDefault>
            <Iframe url="https://manasomali.github.io/jogo-redsquare/"
            width = "100%"
            height = "384"
            />
        </PageDefault>
    </>
  );
}

export default Pagina404;
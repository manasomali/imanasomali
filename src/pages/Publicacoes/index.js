import React from 'react';
import PageDefault from '../../components/PageDefault';
import Titulo from '../../components/Titulo';
import ListaPublicacoes from '../../components/ListaPublicacoes';

function Publicacoes() {
  return (
    <>
        <PageDefault>
            <Titulo>
              Publicações
            </Titulo>
            <ListaPublicacoes />
        </PageDefault>
    </>
  );
}

export default Publicacoes;
import React from 'react';
import ImageRound from '../../components/ImageRound';
import PageDefault from '../../components/PageDefault';
import Social from '../../components/Social';
import Nome from '../../components/Nome';
import Ocupacao from '../../components/Ocupacao';
import Avatar from '../../images/avatar.jpg'

function Main() {
  return (
    <>
      <PageDefault>
          <ImageRound src={Avatar}/>
          <Social />
          <Nome>Matheus Nascimento Soares Marques de Lima</Nome>
          <Ocupacao>Engenheiro Eletricista</Ocupacao>
          <Ocupacao>Desenvolvedor Web e Mobile</Ocupacao>
          <Ocupacao></Ocupacao>
      </PageDefault>
    </>
  );
}

export default Main;
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
          <Ocupacao>Estudante e Pesquisador no Instituto Federal de Santa Catarina (IFSC)</Ocupacao>
          <Ocupacao>Desenvolvedor Web e Mobile</Ocupacao>
          <Ocupacao>Assistente de Projetos P&D na ENGIE Brasil</Ocupacao>
      </PageDefault>
    </>
  );
}

export default Main;
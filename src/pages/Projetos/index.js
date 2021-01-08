import React from 'react';
import Titulo from '../../components/Titulo';
import Projeto from '../../components/Projeto';
import PageDefault from '../../components/PageDefault';
import CardColumns from 'react-bootstrap/CardColumns';

function Projetos() {
  const projetos = [
    {
      titulo: 'Preço de Indiferença - PI',
      descricao: 'O Preço de Indiferença, busca o preço médio mínimo para o custo da energia elétrica buscando viabilizar uma possível migração do Ambiente de Contratação Regulado (ACR) para o Ambiente de Contração Livre (ACL).',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/pi/',
      imagedir: '/pi.png'
    },
    {
      titulo: 'Aplicativo para Alocação de Contratos - APLAC',
      descricao: 'Analisa o histórico de consumo de energia do usuário e retorna um relatório contendo o melhor cenário possível de contração no ambiente livre considerando um portfólio de contratos bilaterais, que podem ser escolhidos pelo próprio usuário. Juntamente com esse cenário a ferramenta calcula o preço mínimo (preço de indiferença) podendo podendo viabilizar uma possível migração ao ambiente livre.',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/aplac/#!/',
      imagedir: '/aplac.png'
    },
    {
      titulo: 'Preço de Indiferença - PI',
      descricao: 'Aplicação web tem como objetivo, recomendar os valores de corte de geração de conjuntos eólicos, em função do limite de fluxo na LT de 525 kV Nova Santa Rita/Povo Novo.',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/simulador/',
      imagedir: '/simulador.png'
    }
  ];
  return (
    <>
        <PageDefault>
          <Titulo>
            Projetos
          </Titulo>
          <CardColumns>
            {projetos.map(item => <Projeto  key={item.titulo} titulo={item.titulo} descricao={item.descricao} link={item.link} imagedir={item.imagedir}/>)}
          </CardColumns>
        </PageDefault>
    </>
  );
}

export default Projetos;
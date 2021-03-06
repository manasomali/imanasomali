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
      titulo: 'Simulador para controle de geração Eólica',
      descricao: 'Aplicação web tem como objetivo, recomendar os valores de corte de geração de conjuntos eólicos, em função do limite de fluxo na LT de 525 kV Nova Santa Rita/Povo Novo.',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/simulador/',
      imagedir: '/simulador.png'
    },
    {
      titulo: 'Sistema de Registro de Transcrição de Voz para Operação',
      descricao: 'Aplicação web para registro de informações a partir da transcrição de voz de operadores do setor elétrico no formato de um produto minimamente viável que prova o conceito de que o registro de informações por meio da voz do operador é algo vantajoso para o setor de operação e pós operação do setor elétrico.',
      link: 'https://manasomalidev.cf',
      imagedir: '/transcricao.png'
    },
    {
      titulo: 'Jogo RedSquare',
      descricao: 'Jogo desenvolvido com a engine Construct 2 durante a formação do curso técnico de Programação de Jogos Digitais',
      link: 'https://play.google.com/store/apps/details?id=com.redsquare.manasomali',
      imagedir: '/redsquare.png'
    },
    {
      titulo: 'App TimeLineList',
      descricao: 'App desenvolvido durante a formação do curso de Desenvolvimento Mobile (Android), para cadastro de filmes e séries com registro de nota, status e reações',
      link: 'https://play.google.com/store/apps/details?id=com.manasomali.timelinelist',
      imagedir: '/timelinelist.jpg'
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
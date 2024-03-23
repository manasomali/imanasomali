import React from 'react';
import Title from '../../components/Title';
import Projeto from '../../components/Project';
import PageDefault from '../../components/PageDefault';
import CardColumns from 'react-bootstrap/CardColumns';
import { useTranslation } from 'react-i18next';

function Projects() {
  const projects = [
    {
      titulo: 'Preço de Indiferença - PI',
      description: 'O Preço de Indiferença, busca o preço médio mínimo para o custo da energia elétrica buscando viabilizar uma possível migração do Ambiente de Contratação Regulado (ACR) para o Ambiente de Contração Livre (ACL).',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/pi/',
      imagedir: '/pi.png'
    },
    {
      titulo: 'Aplicativo para Alocação de Contratos - APLAC',
      description: 'Analisa o histórico de consumo de energia do usuário e retorna um relatório contendo o melhor cenário possível de contração no ambiente livre considerando um portfólio de contratos bilaterais, que podem ser escolhidos pelo próprio usuário. Juntamente com esse cenário a ferramenta calcula o preço mínimo (preço de indiferença) podendo podendo viabilizar uma possível migração ao ambiente livre.',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/aplac/#!/',
      imagedir: '/aplac.png'
    },
    {
      titulo: 'Simulador para controle de geração Eólica',
      description: 'Aplicação web tem como objetivo, recomendar os valores de corte de geração de conjuntos eólicos, em função do limite de fluxo na LT de 525 kV Nova Santa Rita/Povo Novo.',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/simulador/',
      imagedir: '/simulador.png'
    },
    {
      titulo: 'Sistema de Registro de Transcrição de Voz para Operação',
      description: 'Aplicação web para registro de informações a partir da transcrição de voz de operadores do setor elétrico no formato de um produto minimamente viável que prova o conceito de que o registro de informações por meio da voz do operador é algo vantajoso para o setor de operação e pós operação do setor elétrico.',
      link: 'https://github.com/manasomali/poc-transcritor-pi3',
      imagedir: '/transcricao.png'
    },
    {
      titulo: 'Jogo RedSquare',
      description: 'Jogo desenvolvido com a engine Construct 2 durante a formação do curso técnico de Programação de Jogos Digitais',
      link: 'https://play.google.com/store/apps/details?id=com.redsquare.manasomali',
      imagedir: '/redsquare.png'
    },
    {
      titulo: 'App TimeLineList',
      description: 'App desenvolvido durante a formação do curso de Desenvolvimento Mobile (Android), para cadastro de filmes e séries com registro de nota, status e reações',
      link: 'https://play.google.com/store/apps/details?id=com.manasomali.timelinelist',
      imagedir: '/timelinelist.jpg'
    },
    {
      titulo: 'Legendas TV Organizer',
      description: 'Utilitário feito com Python que seleciona e organiza a legenda correta automaticamente. Basta executar o utilitário em uma pasta com o file de video e o .zip do legendas.tv que os files são organizados automaticamente.',
      link: 'https://github.com/manasomali/legendas-tv-organizer',
      imagedir: '/legendas-tv-organizer.gif'
    },
    {
      titulo: 'Automatic Renamer',
      description: 'Utilitário feito com Python que realiza a renomeação de files ou pastas seguindo uma lógica dependendo do tipo do file (série, filme ou anime). Possui interface gráfica',
      link: 'https://github.com/manasomali/automatic-renamer',
      imagedir: '/automatic-renamer.gif'
    },
    {
      titulo: 'Sistema para classificação da Comunicação Verbal na Operação do Setor Elétrico',
      description: 'Sistema desenvolvido com Python destinado a classificação da operação do setor elétrico com múltiplos modelos de aprendizado de máquina capazes de resolver problemas de classificação multiclasse. A entrada de dados pode ser no formato de texto ou de áudio (transcrição de fala ou de um file).',
      link: 'https://gese.florianopolis.ifsc.edu.br/classificador-operacao/',
      imagedir: '/classificador.png'
    },
    {
      titulo: 'Legendas TV Viewer App',
      description: 'App para visualização do site legendas.tv',
      link: 'https://github.com/manasomali/start-project-react-native',
      imagedir: '/legendas-tv-viewer.png'
    },
    {
      titulo: 'Movie Graber',
      description: 'Executável para download de filmes do site topdezfilmes',
      link: 'https://github.com/manasomali/movie-grabber',
      imagedir: '/movie-graber.png'
    }
  ];
  const { t, i18n } = useTranslation();
  return (
    <>
        <PageDefault>
          <Title>
              {t('pages.projects.title')}
          </Title>
          <CardColumns>
            {projects.map(item => <Projeto  key = {item.titulo} titulo = {item.titulo} description = {item.description} link = {item.link} imagedir = {item.imagedir}/>)}
          </CardColumns>
        </PageDefault>
    </>
  );
}

export default Projects;

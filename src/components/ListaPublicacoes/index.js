import React from 'react';
import Publicacoes from '../Publicacoes';
import styled from 'styled-components';

const Filter = styled.a`
  color: var(--black);
  box-sizing: border-box;
  cursor: pointer;
  padding: 16px 24px;
  font-style: normal;
  font-weight: bold;
  font-size: 20px;
  outline: none;
  border-radius: 5px;
  text-decoration: none;
  display: inline-block;
  text-align: center;
  transition: opacity .3s;
  &::after {
      content: '';
      display: block;
      width: 0;
      height: 2px;
      background: #000;
      transition: width .3s;
  }
  &:hover::after {
      width: 100%;
  }
  &:hover {
    text-decoration:none;
    color:black;
  }
`;

class ListaPublicacoes extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      publis: [
        {
          id: '13',
          tipo: 'Artigo Completo',
          titulo: 'Processamento de Arquivos de Áudios e Texto Relacionados a Comunicação Verbal da Operação do Setor Elétrico',
          autores: 'LIMA, M. N. S. M.; Coelho, B. H.; TAKIGAWA, F. Y. K.',
          local: 'Rio de Janeiro',
          revista: '',
          evento: 'XXVI SNPTEE - XXVI Seminário Nacional de Produção e Transmissão de Energia Elétrica',
          ano: '2022',
          link: 'https://xxvisnptee.com.br/',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Snptee_2022.pdf'
        },
        {
          id: '12',
          tipo: 'Artigo Completo',
          titulo: 'Evaluation of Machine Learning Algorithms for Multiclass Classification of Voice Calls from Power Systems Operations',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          local: 'Istanbul',
          revista: 'Anais do 7th International Conference on Engineering and Emerging Technologies',
          evento: '7th International Conference on Engineering and Emerging Technologies',
          ano: '2021',
          link: 'https://ieeexplore.ieee.org/document/9659723',
          doi: '10.1109/ICEET53442.2021.9659723',
          issn: '',
          isbn: '',
          arquivo: 'documents/Iceet_2021.pdf'
        },
        {
          id: '11',
          tipo: 'Trabalho de Conclusão e Curso',
          titulo: 'Processamento, Transcrição e Classificação Automatizada da Comunicação Verbal na Operação do Setor Elétrico Aplicando Técnicas de Aprendizado De Máquina e Processamento de Linguagem Natural',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          local: 'Florianópolis',
          revista: 'Trabalho de Conclusão e Curso',
          evento: '',
          ano: '2021',
          link: '',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Tcc_2021.pdf'
        },
        {
          id: '10',
          tipo: 'Artigo Completo',
          titulo: 'Ferramentas e recursos disponíveis para reconhecimento de fala em Português Brasileiro',
          autores: 'LIMA, M. N. S. M.; COELHO, B. H. ; TAKIGAWA, F. Y. K.',
          local: 'Online',
          revista: 'Anais do Computer on the Beach 2021. p.475--479',
          evento: 'Computer on the Beach 2021',
          ano: '2021',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/17441',
          doi: '10.14210/cotb.v12.p475-479',
          issn: '2358-0852',
          isbn: '',
          arquivo: 'documents/Cotb_2021.pdf'
        },
        {
          id: '9',
          tipo: 'Capítulo de Livro',
          titulo: 'Desenvolvimento de uma Ferramenta web para o controle de geração na região de Nova Santa Rita - Povo Novo',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K. ; FLORINDO, T. P. ; PAULA, W. R. ; SCHMITT, M. R.',
          local: '',
          revista: 'Gestão do conhecimento na indústria 4.0 p.103-117',
          evento: '',
          ano: '2020',
          link: 'https://www.uniedusul.com.br/publicacao/gestao-do-conhecimento-na-industria-4-0/',
          doi: '10.29327/514128-8',
          issn: '',
          isbn: '978-65-86010-07-7',
          arquivo: 'documents/Uniedusul_2020.pdf'
        },
        {
          id: '8',
          tipo: 'Artigo Completo',
          titulo: 'Aplicação web para corte de geração eólica na região de Nova Santa Rita - Povo Novo',
          autores: 'LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; PAULA, W. R. ; FLORINDO, T. P.',
          local: 'Evento Online',
          revista: 'Anais do I Congresso Brasileiro Interdisciplinar em Ciência e Tecnologia',
          evento: 'I Congresso Brasileiro Interdisciplinar de Ciência e Tecnologia',
          ano: '2020',
          link: 'www.even3.com.br/Anais/icobicet2020/269309-APLICACAO-WEB-PARA-CORTE-DE-GERACAO-EOLICA-NA-REGIAO-DE-NOVA-SANTA-RITA---POVO-NOVO',
          doi: '',
          issn: '',
          isbn: '978-65-88243-19-0',
          arquivo: 'documents/Cobicet_2020.pdf'
        },
        {
          id: '7',
          tipo: 'Artigo Completo',
          titulo: 'Análise da ferramenta web para alocação de contratos de energia para consumidores (potencialmente) livres',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; PAULA, W. R.',
          local: 'Foz do Iguaçu',
          revista: 'Anais do XVIII ERIAC',
          evento: 'XVIII ERIAC - ENCONTRO REGIONAL IBERO-AMERICANO DO CIGRE',
          ano: '2019',
          link: 'http://www.xviiieriac.com.br/',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Eriac_2019.pdf'
        },
        {
          id: '6',
          tipo: 'Artigo Completo',
          titulo: 'Principais etapas do desenvolvimento da ferramenta Web para alocação de contratos de energia',
          autores: 'LIMA, M. N. S. M.; PAULA, W. R. ; TAKIGAWA, F. Y. K.',
          local: 'Camboriú',
          revista: 'Anais do I Workshop em Sistemas de Informação do IFC',
          evento: 'I Workshop em Sistemas de Informação do IFC',
          ano: '2018',
          link: 'http://www.etic.ifc-camboriu.edu.br/2018/wsi.html',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Etic_2018.pdf'
        },
        {
          id: '5',
          tipo: 'Artigo Completo',
          titulo: 'A Disponibilidade da Ferramenta Web Preço de Indiferença (PI) para Cursos de Graduação',
          autores: 'LIMA, M. N. S. M.; LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; SCUZZIATO, M. R. ; FERNANDES, R. C.',
          local: 'Buenos Aires',
          revista: 'Anais CIDEL 2018',
          evento: 'CIDEL – Congreso Internacional de Distribucíon Eléctric',
          ano: '2018',
          link: 'https://www.cidel2018.com/recap.asp',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cidel_2018.pdf'
        },
        {
          id: '4',
          tipo: 'Artigo Completo',
          titulo: 'Desenvolvimento de uma Ferramenta Web para o Cálculo do Preço de Indiferença (PI) entre os Ambientes de Contratação de Energia Elétrica',
          autores: 'LIMA, M. N. S. M.; LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; SILVA, A. S.',
          local: 'Florianópolis',
          revista: 'Anais do IX Computer on the Beach p. 602-611',
          evento: 'IX Computer on the Beach',
          ano: '2018',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/12820',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cotb1_2018.pdf'
        },
        {
          id: '3',
          tipo: 'Expandido',
          titulo: 'Proposta de desenvolvimento de uma ferramenta on-line para o gerenciamento de contratos de compra de energia elétrica',
          autores: 'SILVA, A. S. ; TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; LIMA, M. N. S. M.',
          local: 'Florianópolis',
          revista: 'Anais do IX Computer on the Beach p. 975-975',
          evento: 'IX Computer on the Beach',
          ano: '2018',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/12879',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cotb2_2018.pdf'
        },
        {
          id: '2',
          tipo: 'Resumo',
          titulo: 'Aplicativo para alocação de contratos (APLAC)',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; LIMA, M. N. S. M. ; PAULA, W. R. ; SILVA, A. S.',
          local: 'Florianópolis',
          revista: 'Anais do 7 Seminário de Ensino, Pesquisa, Extensão e Inovação do IFSC p. 212-215',
          evento: 'SEPEI - Seminário de Ensino, Pesquisa, Extensão e Inovação do IFSC',
          ano: '2018',
          link: 'https://www.ifsc.edu.br/documents/832555/1685033/anais_2018_final_atualizado.pdf/a3b4d65d-6ef8-4c1d-ae97-f07e73624fcc',
          doi: '',
          issn: '2357-836X',
          isbn: '',
          arquivo: 'documents/Sepei_2018.pdf'
        },
        {
          id: '1',
          tipo: 'Artigo Completo',
          titulo: 'Desenvolvimento de uma página para divulgação do Grupo de Pesquisa',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          local: 'Boituva',
          revista: 'Revista Interdisciplinar de Tecnologias e Educação v.3 n.1',
          evento: 'Simpósio Interdisciplinar de Tecnologias na Educação (SInTE)',
          ano: '2017',
          link: 'http://rinte.ifsp.edu.br/index.php/RInTE/issue/view/%5BRInTE%5D%20-%20v.%203%20-%20nº%201/showToc',
          doi: '',
          issn: '2447-5955',
          isbn: '',
          arquivo: 'documents/Sinte_2017.pdf'
        },        
        {
          id: '0',
          tipo: 'Expandido',
          titulo: 'Guia de informações e ferramenta de apoio a decisão para o consumidor potencialmente livre',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; SOUSA, R. J. S. M. A. ; SILVA, A. S.',
          local: 'Itajaí',
          revista: 'Anais do 6 Seminário de Ensino, Pesquisa, Extensão e Inovação do IFSC p. 88-91',
          evento: 'SEPEI - Seminário de Ensino, Pesquisa, Extensão e Inovação do IFSC',
          ano: '2017',
          link: 'https://discovirtual.ifsc.edu.br/index.php/s/8GdIfAEKGlIGWZo',
          doi: '',
          issn: '2357-836X',
          isbn: '',
          arquivo: 'documents/Sepei_2017.pdf'
        }
      ],
      filterTipo: ''
    }
  }
  handleFilter = (e) => {
    this.setState({filterTipo: e})
  }
  render() {
    let publisFiltradas = this.state.publis.filter((publi) => {
      return publi.tipo.includes(this.state.filterTipo)
    })
    return (
       <>
        <Filter onClick={() => this.handleFilter('')}>Todas</Filter>
        <Filter onClick={() => this.handleFilter('Artigo Completo')}>Artigo Completo</Filter>
        <Filter onClick={() => this.handleFilter('Resumo')}>Resumo</Filter>
        <Filter onClick={() => this.handleFilter('Expandido')}>Resumo Expandido</Filter>
        <Filter onClick={() => this.handleFilter('Capítulo de Livro')}>Capítulo de Livro</Filter>
        <Publicacoes publisFiltradas={publisFiltradas}/>
       </>
    );
  }
};
export default ListaPublicacoes;

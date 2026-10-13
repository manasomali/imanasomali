import React from 'react';
import Publications from '../Publications';
import FilterItem from '../FilterItem';
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

class ListPublications extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      publis: [
        {
          id: '14',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.',
          ano: '2023',
          link: 'https://xxviisnptee.com.br/',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Snptee_2023.pdf'
        },
        {
          id: '13',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; Coelho, B. H.; TAKIGAWA, F. Y. K.',
          ano: '2022',
          link: 'https://xxvisnptee.com.br/',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Snptee_2022.pdf'
        },
        {
          id: '12',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          ano: '2021',
          link: 'https://ieeexplore.ieee.org/document/9659723',
          doi: '10.1109/ICEET53442.2021.9659723',
          issn: '',
          isbn: '',
          arquivo: 'documents/Iceet_2021.pdf'
        },
        {
          id: '11',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          ano: '2021',
          link: 'https://sigaa.ifsc.edu.br/sigaa/public/curso/monografias.jsf',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Tcc_2021.pdf'
        },
        {
          id: '10',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; COELHO, B. H. ; TAKIGAWA, F. Y. K.',
          ano: '2021',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/17441',
          doi: '10.14210/cotb.v12.p475-479',
          issn: '2358-0852',
          isbn: '',
          arquivo: 'documents/Cotb_2021.pdf'
        },
        {
          id: '9',
          tipo: '4',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K. ; FLORINDO, T. P. ; PAULA, W. R. ; SCHMITT, M. R.',
          ano: '2020',
          link: 'https://www.uniedusul.com.br/publication/gestao-do-conhecimento-na-industria-4-0/',
          doi: '10.29327/514128-8',
          issn: '',
          isbn: '978-65-86010-07-7',
          arquivo: 'documents/Uniedusul_2020.pdf'
        },
        {
          id: '8',
          tipo: '1',
          autores: 'LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; PAULA, W. R. ; FLORINDO, T. P.',
          ano: '2020',
          link: 'www.even3.com.br/Anais/icobicet2020/269309-APLICACAO-WEB-PARA-CORTE-DE-GERACAO-EOLICA-NA-REGIAO-DE-NOVA-SANTA-RITA---POVO-NOVO',
          doi: '',
          issn: '',
          isbn: '978-65-88243-19-0',
          arquivo: 'documents/Cobicet_2020.pdf'
        },
        {
          id: '7',
          tipo: '1',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; PAULA, W. R.',
          ano: '2019',
          link: 'http://www.xviiieriac.com.br/',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Eriac_2019.pdf'
        },
        {
          id: '6',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; PAULA, W. R. ; TAKIGAWA, F. Y. K.',
          ano: '2018',
          link: 'http://www.etic.ifc-camboriu.edu.br/2018/wsi.html',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Etic_2018.pdf'
        },
        {
          id: '5',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; SCUZZIATO, M. R. ; FERNANDES, R. C.',
          ano: '2018',
          link: 'https://www.cidel2018.com/recap.asp',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cidel_2018.pdf'
        },
        {
          id: '4',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; SILVA, A. S.',
          ano: '2018',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/12820',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cotb1_2018.pdf'
        },
        {
          id: '3',
          tipo: '3',
          autores: 'SILVA, A. S. ; TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; LIMA, M. N. S. M.',
          ano: '2018',
          link: 'https://siaiap32.univali.br/seer/index.php/acotb/article/view/12879',
          doi: '',
          issn: '',
          isbn: '',
          arquivo: 'documents/Cotb2_2018.pdf'
        },
        {
          id: '2',
          tipo: '2',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; LIMA, M. N. S. M. ; PAULA, W. R. ; SILVA, A. S.',
          ano: '2018',
          link: 'https://www.ifsc.edu.br/documents/832555/1685033/anais_2018_final_atualizado.pdf/a3b4d65d-6ef8-4c1d-ae97-f07e73624fcc',
          doi: '',
          issn: '2357-836X',
          isbn: '',
          arquivo: 'documents/Sepei_2018.pdf'
        },
        {
          id: '1',
          tipo: '1',
          autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
          ano: '2017',
          link: 'http://rinte.ifsp.edu.br/index.php/RInTE/issue/view/%5BRInTE%5D%20-%20v.%203%20-%20nº%201/showToc',
          doi: '',
          issn: '2447-5955',
          isbn: '',
          arquivo: 'documents/Sinte_2017.pdf'
        },        
        {
          id: '0',
          tipo: '3',
          autores: 'TAKIGAWA, F. Y. K. ; LIMA, M. N. S. M. ; SOUSA, R. J. S. M. A. ; SILVA, A. S.',
          ano: '2017',
          link: 'https://discovirtual.ifsc.edu.br/index.php/s/8GdIfAEKGlIGWZo',
          doi: '',
          issn: '2357-836X',
          isbn: '',
          arquivo: 'documents/Sepei_2017.pdf'
        }
      ],
      filterType: ''
    }
  }
  handleFilter = (e) => {
    this.setState({filterType: e})
  }
  render() {
    let publicationsFiltered = this.state.publis.filter((publi) => {
      return publi.tipo.includes(this.state.filterType)
    })
    return (
       <>
        <Filter onClick={() => this.handleFilter("")}><FilterItem i18nKey='components.list_publications.all'/></Filter>
        <Filter onClick={() => this.handleFilter("1")}><FilterItem i18nKey='components.list_publications.complete_article'/></Filter>
        <Filter onClick={() => this.handleFilter("2")}><FilterItem i18nKey='components.list_publications.summary'/></Filter>
        <Filter onClick={() => this.handleFilter("3")}><FilterItem i18nKey='components.list_publications.expanded_summary'/></Filter>
        <Filter onClick={() => this.handleFilter("4")}><FilterItem i18nKey='components.list_publications.book_chapter'/></Filter>
        <Publications publicationsFiltered={publicationsFiltered}/>
       </>
    );
  }
};
export default ListPublications;

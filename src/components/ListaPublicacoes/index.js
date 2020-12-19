import React from 'react';
import './ListaPublicacoes.css'; 
import styled from 'styled-components';
import { Accordion, AccordionItem } from 'react-light-accordion';

const AccordionContent = styled.div`
  padding:20px;
  text-align: center;
  font-size:15px;
  font-weight: normal;
`;

const publis = [
  {
    id: '0',
    titulo: 'Desenvolvimento de uma página para divulgação do Grupo de Pesquisa',
    autores: 'LIMA, M. N. S. M.; TAKIGAWA, F. Y. K.',
    local: 'Wieruch',
    revista: 'Uniedusul Editora',
    evento: '',
    ano: '2020',
  },
  {
    id: '1',
    titulo: 'Desenvolvimento de uma Ferramenta web para o controle de geração na região de Nova Santa Rita - Povo Novo',
    autores: 'LIMA, M. N. S. M.; LIMA, M. N. S. M. ; TAKIGAWA, F. Y. K. ; PAULA, W. R. ; FLORINDO, T. P.',
    local: 'Evento Online',
    revista: '',
    evento: 'I Congresso Brasileiro Interdisciplinar de Ciência e Tecnologia',
    ano: '2020',
  },
];

const ListaPublicacoes = () => (
  <Accordion >
    {publis.map((publi) => (
      <AccordionItem title={publi.titulo}>
        <AccordionContent>
            {publi.autores}
        </AccordionContent>
      </AccordionItem>
    ))}
  </Accordion>
);

export default ListaPublicacoes;
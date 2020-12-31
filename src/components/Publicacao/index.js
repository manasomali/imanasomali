import React from 'react';
import styled from 'styled-components';
import { Download } from '@styled-icons/boxicons-regular/Download';

const AccordionContent = styled.div`
  padding-top:20px;
  padding-bottom:20px;
  padding-left:50px;
  padding-right:80px;
  list-style: none;
`;
const Icone = styled.a`
  cursor: pointer;
  float:left;
  width:auto;
  margin-right: 10px;
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
`;
const Reference = styled.nav`
  overflow: hidden;
  text-align: justify;
  font-size: 15px;
  font-weight: normal;
  user-select: auto;
`;
function montaPublicacao(id, tipo, titulo, autores, local, revista, evento, ano, link, doi, issn, isbn, arquivo) {
    var publicacao = autores + '. ' + titulo + '. ' + local+ '. ' + revista + '. ' + evento + '. ' + ano;
    if(doi !== '') {
      publicacao = publicacao + '. DOI: ' + doi;
    } else if(issn !== '') {
      publicacao = publicacao + '. ISSN: ' + issn;
    } else if(isbn !== '') {
      publicacao = publicacao + '. ISBN: ' + isbn;
    }
    publicacao = publicacao + '. Acesso em: <' + link + '>.'
    return publicacao;
  }

  
function Publicacao(props) {
    return(
        <AccordionContent>
        <Icone href={props.arquivo} target="_blank" rel="noreferrer"><Download size="48" /></Icone>
        <Reference >{montaPublicacao(props.id, props.tipo, props.titulo, props.autores, props.local, props.revista, props.evento, props.ano, props.link, props.doi, props.issn, props.isbn, props.arquivo)}</Reference>
        </AccordionContent>
    )
}

export default Publicacao;
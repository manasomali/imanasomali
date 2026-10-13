import React from 'react';
import styled from 'styled-components';
import { Download } from '@styled-icons/boxicons-regular/Download';
import { useTranslation } from 'react-i18next';

const AccordionContent = styled.div`
  padding-top:20px;
  padding-bottom:20px;
  padding-left:50px;
  padding-right:80px;
  list-style: none;
`;
const Icon = styled.a`
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
function buildPublication(id, tipo, titulo, autores, local, revista, evento, ano, link, doi, issn, isbn, arquivo, accessedLabel) {
    var publication = [autores, titulo, local, revista, evento, ano]
      .filter((part) => part !== '')
      .map((part) => part.replace(/\.$/, ''))
      .join('. ');
    if(doi !== '') {
      publication = publication + '. DOI: ' + doi;
    } else if(issn !== '') {
      publication = publication + '. ISSN: ' + issn;
    } else if(isbn !== '') {
      publication = publication + '. ISBN: ' + isbn;
    }
    publication = publication + '. ' + accessedLabel + ': <' + link + '>.'
    return publication;
  }

  
function Publication(props) {
    const { t } = useTranslation();
    return(
        <AccordionContent>
        <Icon href={props.arquivo} target="_blank" rel="noopener noreferrer"><Download size="48" /></Icon>
        <Reference >{buildPublication(props.id, props.tipo, props.titulo, props.autores, props.local, props.revista, props.evento, props.ano, props.link, props.doi, props.issn, props.isbn, props.arquivo, t('components.publication.accessed'))}</Reference>
        </AccordionContent>
    )
}

export default Publication;
import React from 'react';
import Publicacao from '../Publicacao';
import { Accordion, AccordionItem } from 'react-light-accordion';
import './Publicacoes.css'; 


function Publicacoes(props) {
    let publis = props.publisFiltradas.map((publi) => {
        return <AccordionItem
        key={publi.id} 
        title={publi.ano + ' -> ' + publi.titulo}
        ><Publicacao
        id={publi.id}
        tipo={publi.tipo}
        titulo={publi.titulo}
        autores={publi.autores}
        local={publi.local}
        revista={publi.revista}
        evento={publi.evento}
        ano={publi.ano}
        link={publi.link}
        doi={publi.doi}
        issn={publi.issn}
        isbn={publi.isbn}
        arquivo={publi.arquivo}/></AccordionItem>
    })
    return(
      <Accordion >
        {publis}
      </Accordion>
    )
}

export default Publicacoes;
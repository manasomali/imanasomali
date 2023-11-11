import React from 'react';
import Publication from '../Publication';
import { Accordion, AccordionItem } from 'react-light-accordion';
import './Publications.css'; 


function Publications(props) {
    let publis = props.publicationsFiltered.map((publi) => {
        return <AccordionItem
        key={publi.id} 
        title={publi.ano + ' -> ' + publi.titulo}
        ><Publication
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

export default Publications;
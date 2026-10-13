import React from 'react';
import Publication from '../Publication';
import { Accordion, AccordionItem } from 'react-light-accordion';
import './Publications.css'; 
import { useTranslation } from 'react-i18next';


function Publications(props) {
    const { t } = useTranslation();
    let publis = props.publicationsFiltered.map((publi) => {
        const field = (name) => t(`components.list_publications.items.${publi.id}.${name}`);
        return <AccordionItem
        key={publi.id} 
        title={publi.ano + ' -> ' + field('title')}
        ><Publication
        id={publi.id}
        tipo={publi.tipo}
        titulo={field('title')}
        autores={publi.autores}
        local={field('location')}
        revista={field('journal')}
        evento={field('event')}
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
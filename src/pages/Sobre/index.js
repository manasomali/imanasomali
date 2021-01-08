import React from 'react';
import PageDefault from '../../components/PageDefault';
import Resumo from '../../components/Resumo';
import Titulo from '../../components/Titulo';
import Experiencia from '../../components/Experiencia';

function Sobre() {
    return (
        <>
            <PageDefault>
                <Titulo>
                    Sobre
                </Titulo>
                <Resumo />
                <Experiencia />
            </PageDefault>
        </>
    );
}

export default Sobre;
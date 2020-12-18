import React from 'react';
import PageDefault from '../../components/PageDefault';
import Resumo from '../../components/Resumo';
import Titulo from '../../components/Titulo';

function Sobre() {
    return (
        <>
            <PageDefault>
                <Titulo>
                    Resumo
                </Titulo>
                <Resumo />
            </PageDefault>
        </>
    );
}

export default Sobre;
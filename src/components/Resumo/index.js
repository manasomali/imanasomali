import React from 'react';
import styled from 'styled-components';
import Link from '../Link';

const Descricao = styled.div`
    text-align: justify;
    font-size: 20px;
    width: 100%;
`;

function Resumo() {
    return (
        <>
            <Descricao>
                Formação Técnica em Programação de Jogos Digitais (2014 – 2015), pelo <Link fontSize="20px" href="https://www.opet.com.br" target="_blank" rel="noopener noreferrer">Grupo Educacional Opet</Link>. Atualmente é estudante de Engenharia Elétrica (2016-2021), nono período, no <Link fontSize="20px" href="http://florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">Instituto de Federal de Santa Catarina (IFSC)</Link>. Pesquisador do <Link fontSize="20px" href="https://gese.florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">Grupo em Estudos de Sistemas de Energia (GESE)</Link> (2016-atual) e estagiou no setor de pós-operação no <Link fontSize="20px" href="http://www.ons.org.br" target="_blank" rel="noopener noreferrer">Operador Nacional do Sistema Elétrico (ONS)</Link> (2019-2020). Formado em Desenvolvimento Mobile Android (2020 - 2021) pela <Link fontSize="20px" href="https://www.digitalhouse.com/br" target="_blank" rel="noopener noreferrer">Digital House</Link>. Atualmente atua como Assistente de Projetos P&D na <Link fontSize="20px" href="https://www.engie.com.br" target="_blank" rel="noopener noreferrer">ENGIE Brasil</Link> (2021-atual).
                <br />
                <br />
                Possui conhecimentos sobre <Link fontSize="20px" href="https://docs.microsoft.com/pt-br/office/vba/api/overview/" target="_blank" rel="noopener noreferrer">VBA</Link>, <Link fontSize="20px" href="https://www.php.net" target="_blank" rel="noopener noreferrer">PHP</Link>, <Link fontSize="20px" href="https://developer.mozilla.org/pt-BR/docs/Web/JavaScript" target="_blank" rel="noopener noreferrer">JS</Link>, <Link fontSize="20px" href="https://angularjs.org" target="_blank" rel="noopener noreferrer">AngularJS</Link>, <Link fontSize="20px" href="https://www.mysql.com" target="_blank" rel="noopener noreferrer">mySQL</Link>, <Link fontSize="20px" href="https://www.python.org" target="_blank" rel="noopener noreferrer">Python</Link>, <Link fontSize="20px" href="https://www.r-project.org" target="_blank" rel="noopener noreferrer">R</Link>, <Link fontSize="20px" href="https://kotlinlang.org" target="_blank" rel="noopener noreferrer">Kotlin</Link>, <Link fontSize="20px" href="https://git-scm.com" target="_blank" rel="noopener noreferrer">Git</Link> e <Link fontSize="20px" href="https://flask.palletsprojects.com" target="_blank" rel="noopener noreferrer">Flask</Link>.<br />
                Adicionalmente, estuda as áreas de Ciência de Dados: Processamento de Linguagem Natural (NLP) e Aprendizado de Máquina (ML).
            </Descricao>
        </>
    )
}
export default Resumo
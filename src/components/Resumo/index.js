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
                Formação Técnica em Programação de Jogos Digitais (2014 – 2015), pelo <Link fontSize="20px" href="https://www.opet.com.br" target="_blank" rel="noopener noreferrer">Grupo Educacional Opet</Link>. Atualmente é estudante de Engenharia Elétrica (2016-2021), nono período, no <Link fontSize="20px" href="http://florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">Instituto de Federal de Santa Catarina (IFSC)</Link>. Pesquisador do <Link fontSize="20px" href="https://gese.florianopolis.ifsc.edu.br" target="_blank" rel="noopener noreferrer">Grupo em Estudos de Sistemas de Energia (GESE)</Link> (2016-atual) e estagiou no setor de pós-operação no <Link fontSize="20px" href="http://www.ons.org.br" target="_blank" rel="noopener noreferrer">Operador Nacional do Sistema Elétrico (ONS)</Link> (2019-2020).
                <br />
                <br />
                Adicionalmente, fez cursos de desenvolvimento web, adquirindo conhecimentos sobre <Link fontSize="20px" href="https://www.php.net" target="_blank" rel="noopener noreferrer">PHP</Link>, <Link fontSize="20px" href="https://developer.mozilla.org/pt-BR/docs/Web/JavaScript" target="_blank" rel="noopener noreferrer">JS</Link>, <Link fontSize="20px" href="https://angularjs.org" target="_blank" rel="noopener noreferrer">AngularJS</Link>, <Link fontSize="20px" href="https://www.mysql.com" target="_blank" rel="noopener noreferrer">mySQL</Link>, <Link fontSize="20px" href="https://www.python.org" target="_blank" rel="noopener noreferrer">Python</Link> e <Link fontSize="20px" href="https://www.r-project.org" target="_blank" rel="noopener noreferrer">R</Link>. Formado em Desenvolvimento Mobile Android (2020 - 2021) com <Link fontSize="20px" href="https://kotlinlang.org" target="_blank" rel="noopener noreferrer">Kotlin</Link> pela <Link fontSize="20px" href="https://www.digitalhouse.com/br" target="_blank" rel="noopener noreferrer">Digital House</Link>.
            </Descricao>
        </>
    )
}
export default Resumo
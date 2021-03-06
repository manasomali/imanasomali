import React from 'react';
import styled from 'styled-components';

const Descricao = styled.div`
    text-align: justify;
    font-size: 18px;
    width: 100%;
    margin-left: 20px;
    margin-bottom: 20px;
`;

const SubTitulo = styled.h2`
    text-align: left;
    display: block;
    font-size: 1.5em;
    margin-top: 0.83em;
    margin-bottom: 0.83em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    padding-top: 0;
    margin-bottom: 0;
    margin-left: 10px;
`;
const Ano = styled.h3`
    text-align: left;
    display: block;
    font-size: 1.17em;
    margin-top: 1em;
    margin-bottom: 1em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    margin-bottom: 0px;
    margin-left: 20px;
    margin-top:0;

`;
const Titulo = styled.h1`
    text-align: left;
    font-size: 2em;
    margin-top: 0.67em;
    margin-bottom: 0.67em;
    margin-left: 0;
    margin-right: 0;
    font-weight: bold;
    width: 100%;
    padding-top: 40px;
    margin-top: 0;
`;

function Experiencia() {
    return (
        <>
            <Titulo>Experiência Profissional</Titulo>
            <SubTitulo>Pesquisador, IFSC - GESE</SubTitulo>
            <Ano>2016 - 2018</Ano>
            <Descricao>Desenvolvimento de um aplicativo computacional para a gestão de
            contratos de compra de energia elétrica.</Descricao>
            <Ano>2018 - 2020</Ano>
            <Descricao>Desenvolvimento de uma ferramenta web para auxílio na redução de
            geração eólica devido ao limite de carregamento de linhas de
            transmissão.</Descricao>
            <Ano>2020-2021</Ano>
            <Descricao>Desenvolvimento de uma plataforma web para registro de transcrições de
            voz de operadores do setor elétrico.</Descricao>
            <SubTitulo>Estágiario, ONS</SubTitulo>
            <Ano>2019 – 2020</Ano>
            <Descricao>
                Atuou no setor de pós operação, auxiliando nas atividades de apuração nos sistemas:
                <i>
                <ul>
                    <li>SADHI – Apuração dos Dados Hidrológicos</li>
                    <li>SAMUG – Apuração das Mudanças de Estados Operativos de Unidades Geradoras</li>
                    <li>SIPER – Sistema Integrado de Perturbações</li>
                    <li>SAGIC – Apuração da Geração, Carga e Intercâmbio</li>
                    <li>SAIPC – Apuração das Interrupções dos Pontos de Controle</li>
                    <li>SAMUST – Sistema de Apuração dos Montantes de Uso do Sistema da Transmissão</li>
                    <li>SATRA – Sistema de Apuração da Transmissão</li>
                </ul>
                </i>
            </Descricao>
        </>
    )
}
export default Experiencia
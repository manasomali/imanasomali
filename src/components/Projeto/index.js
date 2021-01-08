import React from 'react';
import Card from 'react-bootstrap/Card';
import styled from 'styled-components';
import 'bootstrap/dist/css/bootstrap.css';

const Button =  styled.a`
	box-shadow:inset 0px 1px 0px 0px #ffffff;
    border-radius:6px;
    padding:6px 24px;
    border:2px solid black;
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    margin: 0px 24px 0px 24px;
    font-style: normal;
    font-weight: bold;
    outline: none;
    text-decoration: none;
    display: inline-block;
    transition: opacity .3s;
    &:hover {
        text-decoration:underline;
        color:black;
    }
`;
function Projeto(props) {
    return (
        <>
        <Card className="text-center">
                <Card.Img variant="top" src={props.imagedir}/>
                <Card.Body>
                    <Card.Title>{props.titulo}</Card.Title>
                    <Card.Text>
                    {props.descricao}
                    </Card.Text>
                    <Button href={props.link} target="_blanck">Acessar</Button>
                </Card.Body>
            </Card>
        </>
    )
}
export default Projeto
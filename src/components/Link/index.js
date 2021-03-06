import styled from 'styled-components';

const Link = styled.a`
    color: var(--black);
    cursor: pointer;
    font-style: normal;
    font-size: ${props => props.fontSize || '15px'};
    outline: none;
    text-decoration: underline;
    display: inline-block;
    transition: opacity .3s;

    &:hover,
    &:focus {
        opacity: .6;
        color: var(--black);
    }
`;

export default Link;
import styled from 'styled-components';

const Button = styled.button`
    color: var(--black);
    box-sizing: border-box;
    cursor: pointer;
    padding: 16px 24px;
    font-style: normal;
    font-weight: bold;
    font-size: 20px;
    outline: none;
    border-radius: 5px;
    text-decoration: none;
    display: inline-block;
    transition: opacity .3s;
    &::after {
        content: '';
        display: block;
        width: 0;
        height: 2px;
        background: #000;
        transition: width .3s;
    }
    &:hover::after {
        width: 100%;
    }
`;
export default Button;
import styled from 'styled-components';

export const FooterBase = styled.footer`
  background: var(--white);
  border-top: 2px solid var(--black);
  padding-left: 15px;
  padding-right: 15px;
  padding-top: 10px;
  padding-bottom: 10px;
  color: var(--black);
  font-weight: bold;
  text-align: left;
  @media (max-width: 800px) {
    margin-bottom: 50px;
  }
`;
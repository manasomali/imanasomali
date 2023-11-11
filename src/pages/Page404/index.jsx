import React from 'react';
import PageDefault from '../../components/PageDefault';
import Iframe from 'react-iframe';

function Page404() {
  return (
    <>
        <PageDefault>
            <Iframe url="https://media.tenor.com/2g8VHWu_d4UAAAAC/cake-i-do-not-want-cake.gif/"
            width = "100%"
            height = "384"
            />
        </PageDefault>
    </>
  );
}

export default Page404;
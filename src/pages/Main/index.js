import React from 'react';
import ImageRound from '../../components/ImageRound';
import PageDefault from '../../components/PageDefault';
import Social from '../../components/Social';
import Avatar from '../../images/avatar.jpg'

function Main() {
  return (
    <>
      <PageDefault>
          <ImageRound src={Avatar}/>
          <Social />
      </PageDefault>
    </>
  );
}

export default Main;
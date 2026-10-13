import React from 'react';
import Title from '../../components/Title';
import Projeto from '../../components/Project';
import PageDefault from '../../components/PageDefault';
import CardColumns from 'react-bootstrap/CardColumns';
import { useTranslation } from 'react-i18next';

function Projects() {
  const projects = [
    {
      key: 'pi',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/pi/',
      imagedir: '/pi.png'
    },
    {
      key: 'aplac',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/aplac/#!/',
      imagedir: '/aplac.png'
    },
    {
      key: 'wind_simulator',
      link: 'https://gese.florianopolis.ifsc.edu.br/consumidorlivre/simulador/',
      imagedir: '/simulador.png'
    },
    {
      key: 'voice_transcription',
      link: 'https://github.com/manasomali/poc-transcritor-pi3',
      imagedir: '/transcricao.png'
    },
    {
      key: 'redsquare',
      link: 'https://play.google.com/store/apps/details?id=com.redsquare.manasomali',
      imagedir: '/redsquare.png'
    },
    {
      key: 'timelinelist',
      link: 'https://play.google.com/store/apps/details?id=com.manasomali.timelinelist',
      imagedir: '/timelinelist.jpg'
    },
    {
      key: 'legendas_organizer',
      link: 'https://github.com/manasomali/legendas-tv-organizer',
      imagedir: '/legendas-tv-organizer.gif'
    },
    {
      key: 'automatic_renamer',
      link: 'https://github.com/manasomali/automatic-renamer',
      imagedir: '/automatic-renamer.gif'
    },
    {
      key: 'classifier',
      link: 'https://gese.florianopolis.ifsc.edu.br/classificador-operacao/',
      imagedir: '/classificador.png'
    },
    {
      key: 'legendas_viewer',
      link: 'https://github.com/manasomali/start-project-react-native',
      imagedir: '/legendas-tv-viewer.png'
    },
    {
      key: 'movie_grabber',
      link: 'https://github.com/manasomali/movie-grabber',
      imagedir: '/movie-graber.png'
    }
  ];
  const { t, i18n } = useTranslation();
  return (
    <>
        <PageDefault>
          <Title>
              {t('pages.projects.title')}
          </Title>
          <CardColumns>
            {projects.map(item => <Projeto key={item.key} title={t(`pages.projects.items.${item.key}.title`)} description={t(`pages.projects.items.${item.key}.description`)} link={item.link} imagedir={item.imagedir}/>)}
          </CardColumns>
        </PageDefault>
    </>
  );
}

export default Projects;

import {
  SiGithub, SiGmail, SiInstagram, SiLetterboxd, SiMyanimelist, SiTrakt,
} from 'react-icons/si';
import { FaGraduationCap } from 'react-icons/fa';
import styles from './styles.module.css';

// `shape` evens out the glyphs: "wide" for short, wide logos and "badge" for
// small or wordmark logos, which sit inside a filled circle.
const networks = [
  { label: 'GitHub', href: 'https://github.com/manasomali', Icon: SiGithub },
  {
    label: 'Gmail',
    href: 'https://mail.google.com/mail/?view=cm&fs=1&to=matheus.nascimento.marques@gmail.com',
    Icon: SiGmail,
    shape: 'wide',
  },
  {
    label: 'Lattes', href: 'http://lattes.cnpq.br/2299260238389056', Icon: FaGraduationCap, shape: 'wide',
  },
  { label: 'Instagram', href: 'https://www.instagram.com/mat.n96/', Icon: SiInstagram },
  {
    label: 'Letterboxd', href: 'https://letterboxd.com/manasomali/', Icon: SiLetterboxd, shape: 'badge',
  },
  { label: 'Trakt', href: 'https://app.trakt.tv/profile/manasomali?share=lkXUvi1B6rPK', Icon: SiTrakt },
  {
    label: 'MyAnimeList', href: 'https://myanimelist.net/profile/manasomali', Icon: SiMyanimelist, shape: 'badge',
  },
];

function Social() {
  return (
    <ul className={styles.social}>
      {networks.map(({
        label, href, Icon, shape,
      }) => (
        <li key={label}>
          <a
            className={`${styles.icon} ${shape ? styles[shape] : ''}`}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={label}
            title={label}
          >
            {shape === 'badge'
              ? <span className={styles.badgeCircle}><Icon aria-hidden /></span>
              : <Icon aria-hidden />}
          </a>
        </li>
      ))}
    </ul>
  );
}

export default Social;

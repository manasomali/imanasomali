import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiX } from 'react-icons/fi';
import { useActiveBanner } from '../../api/banners';
import { bannerText, dismissBanner, isBannerDismissed } from '../../lib/banner';
import styles from './styles.module.css';

// Aviso global do admin (um por vez), para todos, com ou sem login, no idioma da tela. O texto
// entra como texto puro: o React escapa, e "<b>" aparece como está. Fechar vale para aquele banner
// neste navegador. `onDismiss` recebe o foco de volta (o botão some ao fechar)
export default function Banner({ onDismiss }) {
  const { t, i18n } = useTranslation();
  const { data: banner } = useActiveBanner();
  const [closedId, setClosedId] = useState(null);

  if (!banner || banner.id === closedId || isBannerDismissed(banner.id)) return null;

  const close = () => {
    dismissBanner(banner.id);
    setClosedId(banner.id);
    onDismiss?.();
  };

  return (
    <section className={styles.banner} aria-label={t('banner.label')}>
      <div className={styles.inner}>
        <p className={styles.text}>{bannerText(banner, i18n.resolvedLanguage)}</p>
        <button type="button" className={styles.close} aria-label={t('banner.dismiss')} onClick={close}>
          <FiX aria-hidden size={20} />
        </button>
      </div>
    </section>
  );
}

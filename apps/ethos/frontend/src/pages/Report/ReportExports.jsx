import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FiDownload, FiImage, FiShare2 } from 'react-icons/fi';
import { csvFile, jsonFile } from '../../lib/export/files';
import { IMAGE_HEIGHT, IMAGE_WIDTH, renderReportImage } from '../../lib/export/image';
import { canShareFile, downloadBlob, shareOrDownload } from '../../lib/export/share';
import { watchSystemTheme } from '../../lib/theme';
import { today } from '../../lib/time';
import styles from './styles.module.css';

const ICON_SIZE = 18;

// Muda a cada troca de tema (data-theme no <html>, pelo menu, ou o tema do sistema): a imagem
// pronta usa as cores do tema em que foi gerada e deixa de valer
function useThemeVersion() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((value) => value + 1);
    const observer = new MutationObserver(bump);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const stopWatching = watchSystemTheme(bump);
    return () => {
      observer.disconnect();
      stopWatching();
    };
  }, []);
  return version;
}

// Exports do relatório. A imagem é gerada antes ("Gerar imagem", com prévia) e só depois
// compartilhada: o navigator.share exige um gesto recente, e gerar leva um tempo. Mudar o relatório,
// as informações, o idioma ou o tema descarta a imagem pronta. CSV e JSON baixam direto
export default function ReportExports({ report }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const themeVersion = useThemeVersion();
  const [image, setImage] = useState(null);
  const [status, setStatus] = useState(null);
  const [working, setWorking] = useState(false);
  // A imagem vale para este relatório (objeto refeito a cada mudança), idioma e tema
  const fresh = image && image.report === report && image.language === language
    && image.themeVersion === themeVersion;

  // Libera a URL da prévia quando a imagem muda ou a tela sai
  useEffect(() => {
    if (!image) return undefined;
    return () => URL.revokeObjectURL(image.url);
  }, [image]);

  const generate = async () => {
    setWorking(true);
    setStatus(null);
    try {
      const file = await renderReportImage(report, { t, language, today: today(report.timezone) });
      setImage({ report, language, themeVersion, file, url: URL.createObjectURL(file) });
      setStatus('image_ready');
    } catch {
      setImage(null);
      setStatus('image_error');
    } finally {
      setWorking(false);
    }
  };

  const deliver = async () => {
    const result = await shareOrDownload(image.file, { title: t('report.export.share_title') });
    setStatus(result === 'canceled' ? null : result);
  };

  const download = (file) => {
    downloadBlob(file, file.name);
    setStatus('downloaded');
  };

  const canShare = fresh && canShareFile(image.file);

  return (
    <section className={styles.exports} aria-labelledby="report-export">
      <h3 id="report-export" className={styles.cardTitle}>
        {t('report.export.title')}
      </h3>
      <p className={styles.hint}>{t('report.export.hint', { width: IMAGE_WIDTH, height: IMAGE_HEIGHT })}</p>
      <div className={styles.buttons}>
        <button type="button" className={styles.primary} onClick={generate} disabled={working}>
          <FiImage aria-hidden size={ICON_SIZE} />
          {fresh ? t('report.export.regenerate') : t('report.export.image')}
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={() => download(csvFile(report, { t }))}
        >
          <FiDownload aria-hidden size={ICON_SIZE} />
          {t('report.export.csv')}
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={() => download(jsonFile(report, { generatedAt: new Date() }))}
        >
          <FiDownload aria-hidden size={ICON_SIZE} />
          {t('report.export.json')}
        </button>
      </div>
      <p className={styles.status} role="status">
        {working ? t('report.export.working') : status && t(`report.export.${status}`)}
      </p>
      {fresh && (
        <figure className={styles.preview}>
          <img
            src={image.url}
            width={IMAGE_WIDTH}
            height={IMAGE_HEIGHT}
            alt={t('report.export.preview')}
          />
          <figcaption className={styles.buttons}>
            <button type="button" className={styles.primary} onClick={deliver}>
              {canShare ? <FiShare2 aria-hidden size={ICON_SIZE} /> : <FiDownload aria-hidden size={ICON_SIZE} />}
              {canShare ? t('report.export.share') : t('report.export.download_image')}
            </button>
            {canShare && (
              <button type="button" className={styles.button} onClick={() => download(image.file)}>
                <FiDownload aria-hidden size={ICON_SIZE} />
                {t('report.export.download_image')}
              </button>
            )}
          </figcaption>
        </figure>
      )}
    </section>
  );
}

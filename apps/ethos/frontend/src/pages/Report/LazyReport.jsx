import { Suspense, lazy } from 'react';
import { useTranslation } from 'react-i18next';

// O relatório e a geração da imagem ficam num chunk à parte, baixado só quando a tela abre: quem
// só marca hábitos não paga por eles no carregamento
const Report = lazy(() => import('./index'));

export default function LazyReport() {
  const { t } = useTranslation();
  return (
    <Suspense fallback={<p role="status">{t('common.loading')}</p>}>
      <Report />
    </Suspense>
  );
}

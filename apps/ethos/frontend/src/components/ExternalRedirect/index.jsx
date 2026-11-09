import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { page } from '../../lib/page';

/**
 * Sai do app para `to` (uma tela de outra aplicação na mesma origem, ex.: o login do imago), no
 * lugar da entrada atual do histórico: o voltar do navegador não cai de novo aqui.
 */
export default function ExternalRedirect({ to }) {
  const { t } = useTranslation();

  useEffect(() => {
    page.replace(to);
  }, [to]);

  return (
    <p role="status">
      <a href={to}>{t('common.redirecting')}</a>
    </p>
  );
}

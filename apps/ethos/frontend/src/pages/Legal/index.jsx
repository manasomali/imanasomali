import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import TextDocument from '../../components/TextDocument';
import { loadLegalDocument } from '../../lib/legal';

// Termos de uso (name="terms") e política de privacidade (name="privacy"), abertos sem login.
// O texto é puro e vai como texto (TextDocument), com uma âncora por seção (/termos#account)
export default function Legal({ name }) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const legal = useQuery({
    queryKey: ['legal', name, language],
    queryFn: () => loadLegalDocument(name, language),
    // O texto faz parte do build: não muda enquanto a aba está aberta
    staleTime: Infinity,
  });

  if (legal.data === undefined) {
    return (
      <>
        <PageTitle title={t(`pages.${name}.title`)} />
        {legal.isError ? (
          <ErrorMessage error={legal.error} onRetry={() => legal.refetch()} />
        ) : (
          <p role="status">{t('common.loading')}</p>
        )}
      </>
    );
  }

  const { title, version, sections } = legal.data;
  return (
    <TextDocument
      language={legal.data.language}
      title={title}
      note={t('legal.version', { version })}
      sections={sections}
      contentsLabel={t('legal.contents')}
    />
  );
}

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import TextDocument from '../../components/TextDocument';
import { loadHelp } from '../../lib/help';

// Ajuda (`/ajuda`), aberta sem login como os termos: explica as regras do app e não mostra nem
// busca dado de ninguém, então serve também a quem ainda está decidindo se cria a conta. O texto
// (src/help/<idioma>.json) vai como texto puro, com uma âncora por seção (/ajuda#alerts); as
// telas apontam para a seção certa com o HelpLink
export default function Help() {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const help = useQuery({
    queryKey: ['help', language],
    queryFn: () => loadHelp(language),
    // O texto faz parte do build: não muda enquanto a aba está aberta
    staleTime: Infinity,
  });

  if (help.data === undefined) {
    return (
      <>
        <PageTitle title={t('pages.help.title')} />
        {help.isError ? (
          <ErrorMessage error={help.error} onRetry={() => help.refetch()} />
        ) : (
          <p role="status">{t('common.loading')}</p>
        )}
      </>
    );
  }

  return (
    <TextDocument
      language={help.data.language}
      title={help.data.title}
      sections={help.data.sections}
      contentsLabel={t('help.contents')}
    />
  );
}

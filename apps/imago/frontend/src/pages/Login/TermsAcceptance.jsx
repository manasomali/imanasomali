import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { acceptTerms, logout, meQueryKey } from '../../api/account';
import ErrorMessage from '../../components/ErrorMessage';
import { TERMS_VERSION } from '../../lib/legal';
import { pageLocation } from '../../lib/location';
import { PATHS } from '../../paths';
import styles from './styles.module.css';

// Aceite de uma versão nova dos termos, na tela de entrar, para quem já tem sessão. Termos
// pendentes contam como sem login para as aplicações: só depois do aceite a tela de entrar volta
// para o `next`. O aceite manda o TERMS_VERSION desta aba; se o backend já estiver noutra versão
// (deploy com a aba aberta), 409: busca o /me de novo e pede para recarregar a página, que traz os
// textos novos. Dá para sair, e quem não concordar pode excluir a conta na tela de conta
export default function TermsAcceptance({ me }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // A sessão acabou no meio (401) ou a versão mudou (409): o /me novo decide o que a tela mostra
  const refreshMe = () => queryClient.invalidateQueries({ queryKey: meQueryKey });

  const accept = useMutation({
    mutationFn: acceptTerms,
    onSuccess: (data) => queryClient.setQueryData(meQueryKey, data),
    onError: (error) => {
      if (error.status === 401 || error.status === 409) void refreshMe();
    },
  });

  // Sair daqui volta para o email → código, na mesma tela
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== meQueryKey[0] });
      await refreshMe();
    },
    onError: (error) => {
      if (error.status === 401) void refreshMe();
    },
  });

  // Esta aba tem textos de outra versão: só recarregando a página
  const outdated = me.current_terms_version !== TERMS_VERSION;
  const busy = accept.isPending || signOut.isPending;

  return (
    <div className={styles.form}>
      <p className={styles.muted}>{t('pages.terms_acceptance.signed_in_as', { email: me.email })}</p>
      <p>{outdated ? t('pages.terms_acceptance.outdated') : t('pages.terms_acceptance.text')}</p>

      {!outdated && (
        <>
          <p className={styles.muted}>{t('legal.version', { version: TERMS_VERSION })}</p>
          <ul className={styles.links} aria-label={t('pages.terms_acceptance.links')}>
            <li>
              <Link to={PATHS.terms} target="_blank" rel="noreferrer">
                {t('pages.terms.title')}
              </Link>
            </li>
            <li>
              <Link to={PATHS.privacy} target="_blank" rel="noreferrer">
                {t('pages.privacy.title')}
              </Link>
            </li>
          </ul>
        </>
      )}

      {accept.isError && !outdated && <ErrorMessage error={accept.error} />}
      {signOut.isError && <ErrorMessage error={signOut.error} />}

      <div className={styles.actions}>
        {outdated ? (
          <button type="button" className={styles.primary} onClick={() => pageLocation.reload()}>
            {t('pages.terms_acceptance.reload')}
          </button>
        ) : (
          <button type="button" className={styles.primary} disabled={busy} onClick={() => accept.mutate()}>
            {accept.isPending ? t('pages.terms_acceptance.accepting') : t('pages.terms_acceptance.accept')}
          </button>
        )}
        <button type="button" className={styles.button} disabled={busy} onClick={() => signOut.mutate()}>
          {signOut.isPending ? t('pages.terms_acceptance.signing_out') : t('pages.terms_acceptance.sign_out')}
        </button>
      </div>

      <p className={styles.consent}>
        <Trans
          i18nKey="pages.terms_acceptance.disagree"
          components={{ account: <Link to={PATHS.account} /> }}
        />
      </p>
    </div>
  );
}

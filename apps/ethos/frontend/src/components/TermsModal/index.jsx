import { useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { acceptTerms, meQueryKey, useLogout } from '../../api/auth';
import { LANGUAGES } from '../../i18n';
import { TERMS_VERSION } from '../../lib/legal';
import { PATHS } from '../../paths';
import ErrorMessage from '../ErrorMessage';
import PageTitle from '../PageTitle';
import styles from './styles.module.css';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Deixa o resto da página inerte e prende o Tab dentro de `dialog` enquanto ele está montado.
 * O foco começa no próprio diálogo, para o leitor de tela ler o título e o texto. Layout effect:
 * o `inert` sai no mesmo commit que tira o diálogo da tela, sem um instante de página travada.
 */
function useModal(dialogRef) {
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    const host = dialog.parentElement;
    const others = [...document.body.children].filter(
      (element) => element !== host && !element.hasAttribute('inert'),
    );
    for (const element of others) element.setAttribute('inert', '');
    const previous = document.activeElement;
    dialog.focus();

    const onKeyDown = (event) => {
      if (event.key !== 'Tab') return;
      const items = [...dialog.querySelectorAll(FOCUSABLE)];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = dialog.contains(active);
      if (event.shiftKey && (!inside || active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    // Foco que escapa (ex.: clique fora, num navegador sem `inert`) volta para o diálogo
    const onFocusIn = (event) => {
      if (!dialog.contains(event.target)) dialog.focus();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('focusin', onFocusIn);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('focusin', onFocusIn);
      for (const element of others) element.removeAttribute('inert');
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [dialogRef]);
}

// Aceite dos termos quando a versão mudou (`terms_pending` no /me). Bloqueia o app: quem chama não
// desenha a tela por trás, o resto da página fica inerte e não há como fechar sem aceitar. Sair
// continua possível. O aceite manda o TERMS_VERSION desta aba; se o backend já estiver noutra
// versão (deploy com a aba aberta), 409: recarrega o /me e pede para recarregar a página, que
// traz os textos novos
export default function TermsModal({ me }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const ids = useId();
  const dialogRef = useRef(null);
  const signOut = useLogout();
  useModal(dialogRef);

  const accept = useMutation({
    mutationFn: acceptTerms,
    onSuccess: (data) => queryClient.setQueryData(meQueryKey, data),
    onError: (error) => {
      if (error.status === 409) queryClient.invalidateQueries({ queryKey: meQueryKey });
    },
  });

  // Esta aba tem textos de outra versão: só recarregando a página
  const outdated = me.current_terms_version !== TERMS_VERSION;
  const titleId = `${ids}-title`;
  const textId = `${ids}-text`;
  const busy = accept.isPending || signOut.isPending;

  return createPortal(
    <div className={styles.backdrop}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={textId}
        tabIndex={-1}
        className={styles.dialog}
      >
        <PageTitle title={t('terms_modal.title')} />
        <h1 id={titleId} className={styles.title}>
          {t('terms_modal.title')}
        </h1>
        <p id={textId}>{outdated ? t('terms_modal.outdated') : t('terms_modal.text')}</p>

        {!outdated && (
          <>
            <p className={styles.version}>{t('legal.version', { version: TERMS_VERSION })}</p>
            <ul className={styles.links} aria-label={t('terms_modal.links')}>
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
            <button type="button" className={styles.primary} onClick={() => window.location.reload()}>
              {t('terms_modal.reload')}
            </button>
          ) : (
            <button
              type="button"
              className={styles.primary}
              disabled={busy}
              onClick={() => accept.mutate()}
            >
              {accept.isPending ? t('terms_modal.accepting') : t('terms_modal.accept')}
            </button>
          )}
          <button
            type="button"
            className={styles.secondary}
            disabled={busy}
            onClick={() => signOut.mutate()}
          >
            {t('terms_modal.sign_out')}
          </button>
        </div>

        {/* O menu fica inerte: o idioma muda aqui */}
        <div className={styles.languages} role="group" aria-label={t('a11y.language')}>
          {LANGUAGES.map((lng) => (
            <button
              key={lng}
              type="button"
              lang={lng}
              className={styles.language}
              aria-pressed={i18n.resolvedLanguage === lng}
              onClick={() => i18n.changeLanguage(lng)}
            >
              {lng}
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

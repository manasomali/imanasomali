import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminKeys, createBanner, endBanner, updateBanner, useBanners } from '../../api/admin';
import { useMe } from '../../api/auth';
import { activeBannerQueryKey, useActiveBanner } from '../../api/banners';
import ErrorMessage from '../../components/ErrorMessage';
import PageTitle from '../../components/PageTitle';
import { bannerStatus } from '../../lib/banner';
import { formatDateTime } from '../../lib/datetime';
import AdminNav from './AdminNav';
import BannerForm from './BannerForm';
import styles from './admin.module.css';

// Depois de qualquer escrita: a lista do admin e o banner que todos veem
function useRefreshBanners() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: adminKeys.banners }),
      queryClient.invalidateQueries({ queryKey: activeBannerQueryKey }),
    ]);
}

function BannerCard({ banner, status, timeZone, onDone }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const refresh = useRefreshBanners();
  const [editing, setEditing] = useState(false);
  const editRef = useRef(null);

  const update = useMutation({
    mutationFn: (values) => updateBanner(banner.id, values),
    onSuccess: () => {
      refresh();
      setEditing(false);
      onDone(t('admin.banners.updated_done', { id: banner.id }));
    },
  });
  const end = useMutation({
    mutationFn: () => endBanner(banner.id),
    onSuccess: () => {
      refresh();
      onDone(t('admin.banners.ended_done', { id: banner.id }));
    },
  });

  const save = (values) => {
    // Nada mudou: só fecha
    if (Object.keys(values).length === 0) {
      setEditing(false);
      editRef.current?.focus();
      return;
    }
    update.mutate(values);
  };

  const cancel = () => {
    setEditing(false);
    update.reset();
    editRef.current?.focus();
  };

  const date = (value) => formatDateTime(value, timeZone, i18n.resolvedLanguage);
  const formId = `${id}-form`;

  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>
        <span>{t('admin.banners.item', { id: banner.id })}</span>{' '}
        <span className={styles.badge}>{t(`admin.banners.status.${status}`)}</span>
      </h3>
      <dl className={styles.details}>
        <div>
          <dt>{t('admin.banners.text_pt')}</dt>
          <dd lang="pt">{banner.text_pt}</dd>
        </div>
        <div>
          <dt>{t('admin.banners.text_en')}</dt>
          <dd lang="en">{banner.text_en}</dd>
        </div>
        <div>
          <dt>{t('admin.banners.starts_at')}</dt>
          <dd>{date(banner.starts_at)}</dd>
        </div>
        <div>
          <dt>{t('admin.banners.ends_at')}</dt>
          <dd>{date(banner.ends_at)}</dd>
        </div>
      </dl>

      <div className={styles.buttons} role="group" aria-label={t('admin.banners.actions', { id: banner.id })}>
        <button
          ref={editRef}
          type="button"
          className={styles.button}
          aria-expanded={editing}
          aria-controls={editing ? formId : undefined}
          onClick={() => (editing ? cancel() : setEditing(true))}
        >
          {t('admin.banners.edit')}
        </button>
        {status !== 'ended' && (
          <button type="button" className={styles.button} disabled={end.isPending} onClick={() => end.mutate()}>
            {t('admin.banners.end')}
          </button>
        )}
      </div>
      {end.error && <ErrorMessage error={end.error} />}

      {editing && (
        <div id={formId}>
          <BannerForm
            banner={banner}
            timeZone={timeZone}
            pending={update.isPending}
            error={update.error}
            submitLabel={t('admin.banners.save')}
            onSubmit={save}
            onCancel={cancel}
          />
        </div>
      )}
    </li>
  );
}

// Banners: criar, editar e encerrar. Só um aparece por vez (o que começou por último dentro da
// janela); a situação de cada um é calculada no instante em que a lista chegou
export default function AdminBanners() {
  const { t } = useTranslation();
  const me = useMe().data;
  const id = useId();
  const banners = useBanners();
  const active = useActiveBanner();
  const refresh = useRefreshBanners();
  const [formKey, setFormKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const statusRef = useRef(null);
  const title = t('admin.banners.title');

  const create = useMutation({
    mutationFn: createBanner,
    onSuccess: (banner) => {
      refresh();
      // Formulário novo, em branco
      setFormKey((key) => key + 1);
      setNotice({ text: t('admin.banners.created_done', { id: banner.id }) });
    },
  });

  useEffect(() => {
    if (notice) statusRef.current?.focus();
  }, [notice]);

  const list = banners.data?.pages.flatMap((page) => page.banners) ?? [];
  const activeId = active.data?.id ?? null;

  return (
    <>
      <PageTitle title={title} />
      <AdminNav />
      <h1 className={styles.title}>{title}</h1>
      <p ref={statusRef} role="status" tabIndex={-1} className={styles.status}>
        {notice?.text}
      </p>

      <section aria-labelledby={`${id}-new`}>
        <h2 id={`${id}-new`} className={styles.subtitle}>
          {t('admin.banners.new')}
        </h2>
        <BannerForm
          key={formKey}
          timeZone={me.timezone}
          pending={create.isPending}
          error={create.error}
          submitLabel={t('admin.banners.create')}
          onSubmit={(values) => create.mutate(values)}
        />
      </section>

      <section className={styles.section} aria-labelledby={`${id}-list`}>
        <h2 id={`${id}-list`} className={styles.subtitle}>
          {t('admin.banners.all')}
        </h2>
        {banners.isPending && <p role="status">{t('common.loading')}</p>}
        {banners.isError && <ErrorMessage error={banners.error} onRetry={() => banners.refetch()} />}
        {banners.isSuccess && list.length === 0 && <p className={styles.muted}>{t('admin.banners.empty')}</p>}
        {list.length > 0 && (
          <ul className={styles.list}>
            {list.map((banner) => (
              <BannerCard
                key={banner.id}
                banner={banner}
                status={bannerStatus(banner, banners.dataUpdatedAt, activeId)}
                timeZone={me.timezone}
                onDone={(text) => setNotice({ text })}
              />
            ))}
          </ul>
        )}
        {banners.hasNextPage && (
          <button
            type="button"
            className={`${styles.button} ${styles.more}`}
            disabled={banners.isFetchingNextPage}
            onClick={() => banners.fetchNextPage()}
          >
            {banners.isFetchingNextPage ? t('common.loading') : t('admin.load_more')}
          </button>
        )}
      </section>
    </>
  );
}

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Publication from '../Publication';
import publications, { publicationTypes } from '../../data/publications';
import styles from './styles.module.css';

const filters = [
  { id: '', i18nKey: 'components.list_publications.all' },
  ...publicationTypes,
];

function countOf(type) {
  return publications.filter((publi) => type === '' || publi.tipo === type).length;
}

function ListPublications() {
  const { t } = useTranslation();
  const [filterType, setFilterType] = useState('');

  const publicationsFiltered = publications.filter(
    (publi) => filterType === '' || publi.tipo === filterType,
  );

  return (
    <>
      <div className={styles.filters} role="group" aria-label={t('components.list_publications.filter')}>
        {filters.map((filter) => (
          <button
            key={filter.id}
            type="button"
            className={styles.filter}
            aria-pressed={filterType === filter.id}
            onClick={() => setFilterType(filter.id)}
          >
            {t(filter.i18nKey)}
            <span className={styles.count}>{countOf(filter.id)}</span>
          </button>
        ))}
      </div>
      <div className={styles.list}>
        {publicationsFiltered.map((publi) => {
          const field = (name) => t(`components.list_publications.items.${publi.id}.${name}`);
          return (
            <Publication
              key={publi.id}
              titulo={field('title')}
              autores={publi.autores}
              local={field('location')}
              revista={field('journal')}
              evento={field('event')}
              ano={publi.ano}
              link={publi.link}
              doi={publi.doi}
              issn={publi.issn}
              isbn={publi.isbn}
              arquivo={publi.arquivo}
            />
          );
        })}
      </div>
    </>
  );
}

export default ListPublications;

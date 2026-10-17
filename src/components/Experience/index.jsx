import { useTranslation } from 'react-i18next';
import Title from '../Title';
import styles from './styles.module.css';

const prefix = 'components.experience';

// Roles with a description followed by a list of activities.
const roles = [
  { role: 'role1', period: 'year1', description: 'description1', items: 4 },
  { role: 'role2', period: 'year2', description: 'description2', items: 4 },
  { role: 'role3', period: 'year3', description: 'description3', items: 7 },
];

// The research role is split into periods, one project each.
const researchPeriods = [1, 2, 3];

function range(count) {
  return Array.from({ length: count }, (_, i) => i + 1);
}

function Experience() {
  const { t } = useTranslation();

  return (
    <section>
      <Title as="h2">{t(`${prefix}.title`)}</Title>
      <ol className={styles.timeline}>
        {roles.map(({
          role, period, description, items,
        }) => (
          <li key={role} className={styles.entry}>
            <h3 className={styles.role}>{t(`${prefix}.${role}`)}</h3>
            <p className={styles.period}>{t(`${prefix}.${period}`)}</p>
            <p>{t(`${prefix}.${description}.description`)}</p>
            <ul className={styles.items}>
              {range(items).map((n) => (
                <li key={n}>{t(`${prefix}.${description}.item${n}`)}</li>
              ))}
            </ul>
          </li>
        ))}
        <li className={styles.entry}>
          <h3 className={styles.role}>{t(`${prefix}.role4`)}</h3>
          <dl className={styles.periods}>
            {researchPeriods.map((n) => (
              <div key={n}>
                <dt className={styles.period}>{t(`${prefix}.description4.year${n}`)}</dt>
                <dd>{t(`${prefix}.description4.item${n}`)}</dd>
              </div>
            ))}
          </dl>
        </li>
      </ol>
    </section>
  );
}

export default Experience;

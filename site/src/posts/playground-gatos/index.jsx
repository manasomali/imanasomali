import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { intlLocale } from '../../i18n';
import DataTable from '../../components/DataTable';
import Figure from '../../components/Figure';
import {
  Assembly, CutPlan, Legend, Profile, WallLayout,
} from './diagrams';
import {
  bevelZoneCuts, blockCuts, ripCuts, stripCuts,
} from './data';
import copy from './copy';
import styles from './styles.module.css';

// Number formats of the plan in the page's language: `num` drops a zero decimal (39,5 / 60),
// `cota` always shows one, like a tape-measure mark (30,0).
function formatters(locale) {
  const plain = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const fixed = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const num = (value) => plain.format(value);
  const cota = (value) => fixed.format(value);
  return {
    num,
    cota,
    dim: (...values) => `${values.map(num).join(' × ')} cm`,
    marks: (values) => values.map(cota).join(' · '),
  };
}

const SECTION_IDS = ['how', 'wall', 'parts', 'plan', 'steps', 'profiles', 'assembly', 'notes'];

function CatPlayground() {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage === 'pt' ? 'pt' : 'en';
  const c = copy[lang];
  const fmt = formatters(intlLocale(lang));
  const {
    num, cota, dim, marks,
  } = fmt;
  const n = c.parts.names;
  const sectionTitle = (id) => (
    <h2 id={id}>{c.sections[id]}</h2>
  );

  return (
    <>
      {c.intro.map((paragraph) => <p key={paragraph} className={styles.intro}>{paragraph}</p>)}
      <dl>
        {c.specs.map(([term, description]) => (
          <Fragment key={term}>
            <dt>{term}</dt>
            <dd>{description}</dd>
          </Fragment>
        ))}
      </dl>
      <nav className={styles.toc} aria-label={c.toc}>
        <p className={styles.tocTitle} aria-hidden>{c.toc}</p>
        <ol>
          {SECTION_IDS.map((id) => (
            <li key={id}><a href={`#${id}`}>{c.sections[id]}</a></li>
          ))}
        </ol>
      </nav>

      {sectionTitle('how')}
      <Figure label={c.diagrams.detail.title} caption={c.how.caption} minWidth={600}>
        <Assembly variant="detail" labels={c.diagrams.detail} />
      </Figure>
      <h3>{c.how.lockTitle}</h3>
      <ol>
        {c.how.lockSteps.map((step) => <li key={step}>{step}</li>)}
      </ol>
      <p>{c.how.selfLocking}</p>

      {sectionTitle('wall')}
      <Figure
        label={c.diagrams.wall.title}
        minWidth={540}
        caption={(
          <>
            {c.wall.caption}
            <Legend kinds={['rail', 'back', 'top', 'cleat', 'house', 'spacer']} labels={c.legend} />
          </>
        )}
      >
        <WallLayout labels={c.diagrams.wall} fmt={fmt} />
      </Figure>
      <h3>{c.wall.levelsTitle}</h3>
      {c.wall.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      <p className={styles.callout}>
        <strong>{c.wall.check.term}</strong>
        {' '}
        {c.wall.check.text}
      </p>

      {sectionTitle('parts')}
      <p>{c.parts.intro}</p>
      <h3>{c.parts.platforms}</h3>
      <DataTable
        label={c.parts.platforms}
        columns={c.parts.columns}
        numeric={[2]}
        rows={[
          [n.topL, dim(60, 28), 3],
          [n.topM, dim(30, 23), 5],
          [n.topS, dim(10, 23), 6],
          [n.backL, dim(60, 7), 3],
          [n.backM, dim(30, 7), 5],
          [n.backS, dim(10, 7), 6],
          [n.cleatL, dim(60, 3.5), 3],
          [n.cleatM, dim(30, 3.5), 5],
          [n.cleatS, dim(10, 3.5), 6],
        ]}
      />
      <h3>{c.parts.houses}</h3>
      <DataTable
        label={c.parts.houses}
        columns={c.parts.columns}
        numeric={[2]}
        rows={[
          [n.backFront, dim(39.5, 30), 4],
          [n.topBottom, dim(39.5, 27), 4],
          [n.side, dim(27, 27), 2],
          [n.houseCleat, dim(39.5, 3.5), 2],
          [n.spacer, dim(36, 3), 2],
        ]}
      />
      <h3>{c.parts.rails}</h3>
      <DataTable
        label={c.parts.rails}
        columns={c.parts.columns}
        numeric={[2]}
        rows={[
          [n.rail, `${dim(220, 5)}, ${c.parts.railCut}`, 5],
          [n.spareBacks, `${num(30)} × ${num(7)} / ${dim(10, 7)}`, `${num(1)} / ${num(3)}`],
          [n.spareSpacer, dim(36, 3), 1],
          [n.spareCleats, `${num(3.5)} cm ${c.parts.width}`, 5],
        ]}
      />
      <h3>{c.parts.hardware}</h3>
      <DataTable
        label={c.parts.hardware}
        columns={c.parts.hardwareColumns}
        numeric={[2]}
        rows={c.parts.hardwareRows}
      />
      <p className={styles.note}>{c.parts.reserve}</p>

      {sectionTitle('plan')}
      <p>{c.plan.intro}</p>
      <Figure
        wide
        label={c.diagrams.plan.title}
        minWidth={880}
        caption={(
          <Legend
            kinds={['house', 'top', 'back', 'cleat', 'rail', 'waste']}
            labels={c.legend}
            bevel
            spare
          />
        )}
      >
        <CutPlan labels={c.diagrams.plan} fmt={fmt} />
      </Figure>

      {sectionTitle('steps')}
      <p>{c.steps.intro}</p>
      <h3>{c.steps.rip.title}</h3>
      <DataTable
        label={c.steps.rip.title}
        columns={c.steps.rip.columns}
        numeric={[1]}
        rows={ripCuts.map((mark, index) => [index + 1, cota(mark), c.steps.rip.frees[index]])}
      />
      <h3>{c.steps.strips.title}</h3>
      <DataTable
        label={c.steps.strips.title}
        columns={c.steps.strips.columns}
        rows={stripCuts.map(({ strip, cuts }, index) => [
          strip, marks(cuts), c.steps.strips.results[index],
        ])}
      />
      <h3>{c.steps.blocks.title}</h3>
      <DataTable
        label={c.steps.blocks.title}
        columns={c.steps.blocks.columns}
        nowrap={[0]}
        rows={blockCuts.map(({ rips, crossCuts, eachStrip }, index) => [
          c.steps.blocks.names[index],
          marks(rips),
          `${crossCuts.map(marks).join(' / ')}${eachStrip ? ` ${c.steps.blocks.eachStrip}` : ''}`,
          c.steps.blocks.results[index],
        ])}
      />
      <h3>{c.steps.bevelZone.title}</h3>
      <DataTable
        label={c.steps.bevelZone.title}
        columns={c.steps.bevelZone.columns}
        nowrap={[0]}
        rows={[
          ...bevelZoneCuts.map((cuts, index) => [
            c.steps.bevelZone.names[index], marks(cuts), c.steps.bevelZone.results[index],
          ]),
          [c.steps.bevelZone.names[3], `${cota(170)} ${c.steps.bevelZone.railCuts}`, c.steps.bevelZone.results[3]],
        ]}
      />
      <h3>{c.steps.bevel.title}</h3>
      <p>{c.steps.bevel.text}</p>
      <ul>
        {c.steps.bevel.faces.map(([term, text]) => (
          <li key={term}>
            <strong>{term}</strong>
            {' '}
            {text}
          </li>
        ))}
      </ul>

      {sectionTitle('profiles')}
      <p>{c.profiles.intro}</p>
      <h3>{c.profiles.rail}</h3>
      <Figure label={c.diagrams.rail.title} minWidth={600}>
        <Profile variant="rail" labels={c.diagrams.rail} fmt={fmt} />
      </Figure>
      <h3>{c.profiles.cleat}</h3>
      <Figure label={c.diagrams.cleat.title} minWidth={600}>
        <Profile variant="cleat" labels={c.diagrams.cleat} fmt={fmt} />
      </Figure>
      <h3>{c.profiles.fit}</h3>
      <Figure label={c.diagrams.fit.title} minWidth={560}>
        <Assembly variant="fit" labels={c.diagrams.fit} />
      </Figure>
      <h3>{c.profiles.othersTitle}</h3>
      <p>{c.profiles.others}</p>

      {sectionTitle('assembly')}
      <ol>
        {c.assembly.map((step) => <li key={step}>{step}</li>)}
      </ol>

      {sectionTitle('notes')}
      {c.notes.map(([term, text]) => (
        <p key={term}>
          <strong>{term}</strong>
          {' '}
          {text}
        </p>
      ))}
    </>
  );
}

export default CatPlayground;

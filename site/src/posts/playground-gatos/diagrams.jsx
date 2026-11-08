import {
  BACK_HEIGHT, DOOR, HOUSE, PLATFORM_WIDTH, RAIL_WIDTH, SHEET, THICKNESS, WALL,
  chamferMarks, houses, planTicks, platforms, rails, sheetPieces,
} from './data';
import styles from './diagrams.module.css';

// The diagrams are drawn in cm and scaled to viewBox units by a factor per diagram, picked so
// that no text is smaller than 12 units. Browsers with a minimum font size setting enlarge
// smaller SVG text whatever the SVG's scale, which would push labels out of their pieces.
// `labels` holds the diagram's text in the page language and `fmt` formats its numbers.

const cx = (...names) => names.filter(Boolean).join(' ');

// The 45° bevel removes a triangle as wide as the board is thick
const BEVEL = THICKNESS;

function toPoints(list, k, dx = 0, dy = 0) {
  return list.map(([x, y]) => `${(x + dx) * k},${(y + dy) * k}`).join(' ');
}

// Wall seen in section: the wall face at x and short diagonal strokes behind it
function WallSection({ x, y1, y2 }) {
  const strokes = [];
  for (let y = y1; y + 8 <= y2; y += 10) {
    strokes.push(<line key={y} x1={x - 8} y1={y + 8} x2={x} y2={y} className={styles.hatch} />);
  }
  return (
    <g>
      {strokes}
      <line x1={x} y1={y1} x2={x} y2={y2} className={styles.wallLine} />
    </g>
  );
}

// Horizontal dimension line with end ticks; the label sits above (labelDy < 0) or below it
function Dimension({
  x1, x2, y, label, labelDy,
}) {
  return (
    <g>
      <line x1={x1} y1={y} x2={x2} y2={y} className={styles.tick} />
      <line x1={x1} y1={y - 4} x2={x1} y2={y + 4} className={styles.tick} />
      <line x1={x2} y1={y - 4} x2={x2} y2={y + 4} className={styles.tick} />
      <text x={(x1 + x2) / 2} y={y + labelDy} className={cx(styles.text, styles.middle)}>{label}</text>
    </g>
  );
}

// Dashed leader from a point on the drawing to a label on the right
function Callout({
  from, labelX, labelY, children,
}) {
  return (
    <g>
      <polyline points={`${from[0]},${from[1]} ${labelX - 6},${labelY}`} className={styles.leader} />
      <text x={labelX} y={labelY} className={cx(styles.text, styles.central)}>{children}</text>
    </g>
  );
}

export function Legend({
  kinds, labels, bevel = false, spare = false,
}) {
  return (
    <ul className={cx(styles.legend, styles.palette)}>
      {kinds.map((kind) => (
        <li key={kind}>
          <span className={cx(styles.swatch, styles[kind])} aria-hidden />
          {labels[kind]}
        </li>
      ))}
      {bevel && (
        <li>
          <span className={styles.markSwatch} aria-hidden />
          {labels.bevel}
        </li>
      )}
      {spare && <li>{labels.spare}</li>}
    </ul>
  );
}

const PLAN_SCALE = 5;
// the last rip and the sheet edge are 2.3 cm apart: move their labels away from each other
const PLAN_TICK_SHIFT = { 157.7: -6, 160: 7 };

export function CutPlan({ labels, fmt }) {
  const k = PLAN_SCALE;
  const width = SHEET.width * k;
  const height = SHEET.height * k;
  const tickLabel = (value) => (
    value === 0 || value === SHEET.height ? fmt.num(value) : fmt.cota(value)
  );

  return (
    <svg
      className={cx(styles.svg, styles.palette)}
      viewBox={`-56 -8 ${width + 64} ${height + 52}`}
      role="img"
      aria-label={labels.title}
    >
      {sheetPieces.map(([x, y, w, h, kind, label]) => (
        <g key={`${x}-${y}`}>
          <rect
            x={x * k}
            y={y * k}
            width={w * k}
            height={h * k}
            className={cx(styles.piece, styles[kind])}
          />
          {label && (
            <text
              x={(x + w / 2) * k}
              y={(y + h / 2) * k}
              fontSize={Math.min(13, h * k * 0.7)}
              className={cx(styles.pieceLabel, w <= 10 && styles.strong)}
            >
              {labels.pieces[label]}
            </text>
          )}
        </g>
      ))}
      {chamferMarks.map(([x1, x2, y]) => (
        <line key={`${x1}-${y}`} x1={x1 * k} y1={y * k} x2={x2 * k} y2={y * k} className={styles.mark} />
      ))}

      {/* four rails are cut at 170; the fifth stays whole */}
      <line x1={170 * k} y1={130.3 * k} x2={170 * k} y2={152.1 * k} className={styles.cut} />
      <text x={171.5 * k} y={144.2 * k} className={cx(styles.pieceLabel, styles.start)} fontSize={12}>
        {labels.cutAt}
      </text>
      <text x={171.5 * k} y={155.2 * k} className={cx(styles.pieceLabel, styles.start)} fontSize={12}>
        {labels.whole}
      </text>

      <rect
        x={0}
        y={157.7 * k}
        width={width}
        height={(SHEET.height - 157.7) * k}
        className={cx(styles.outline, styles.dashed)}
      />
      <rect x={0} y={0} width={width} height={height} className={styles.outline} />

      {planTicks.map((value) => (
        <g key={value}>
          <line x1={-8} y1={value * k} x2={0} y2={value * k} className={styles.tick} />
          <text
            x={-12}
            y={value * k + (PLAN_TICK_SHIFT[value] ?? 0)}
            className={cx(styles.text, styles.end, styles.central)}
          >
            {tickLabel(value)}
          </text>
        </g>
      ))}
      <text x={width} y={height + 15} className={cx(styles.muted, styles.end)}>{labels.waste}</text>
      <Dimension x1={0} x2={width} y={height + 30} label={fmt.num(SHEET.width)} labelDy={4} />
    </svg>
  );
}

const WALL_SCALE = 2.4;

export function WallLayout({ labels, fmt }) {
  const k = WALL_SCALE;
  const width = WALL.width * k;
  const height = WALL.height * k;
  // heights are measured from the floor; the SVG's y grows downward from the ceiling
  const y = (fromFloor) => (WALL.height - fromFloor) * k;
  const ticks = [...rails.map((rail) => rail.height), WALL.height];

  return (
    <svg
      className={cx(styles.svg, styles.palette)}
      viewBox={`-40 -22 ${width + 48} ${height + 46}`}
      role="img"
      aria-label={labels.title}
    >
      <rect x={0} y={0} width={width} height={height} className={styles.wallFace} />
      <rect
        x={DOOR.x * k}
        y={y(DOOR.height)}
        width={DOOR.width * k}
        height={DOOR.height * k}
        className={styles.door}
      />
      <text
        x={(DOOR.x + DOOR.width / 2) * k}
        y={y(DOOR.height / 2)}
        className={cx(styles.muted, styles.middle, styles.central)}
      >
        {labels.door}
      </text>
      <line x1={-6} y1={height} x2={width + 6} y2={height} className={styles.floor} />
      <text x={0} y={height + 18} className={styles.muted}>{labels.floor}</text>
      <text x={width} y={-8} className={cx(styles.muted, styles.end)}>{labels.ceiling}</text>

      {rails.map((rail) => (
        <rect
          key={rail.height}
          x={0}
          y={y(rail.height + RAIL_WIDTH)}
          width={rail.length * k}
          height={RAIL_WIDTH * k}
          className={cx(styles.piece, styles.rail)}
        />
      ))}
      {platforms.map(([rail, x, size]) => {
        const w = PLATFORM_WIDTH[size] * k;
        return (
          <g key={`${rail}-${x}`}>
            <rect x={x * k} y={y(rail)} width={w} height={THICKNESS * k} className={cx(styles.piece, styles.top)} />
            <rect
              x={x * k}
              y={y(rail + BACK_HEIGHT)}
              width={w}
              height={BACK_HEIGHT * k}
              className={cx(styles.piece, styles.back)}
            />
            <text
              x={x * k + w / 2}
              y={y(rail + BACK_HEIGHT / 2)}
              fontSize={12}
              className={cx(styles.pieceLabel, styles.strong)}
            >
              {labels.sizes[size]}
            </text>
          </g>
        );
      })}
      {houses.map((x) => (
        <g key={x}>
          <rect
            x={x * k}
            y={y(HOUSE.top)}
            width={HOUSE.width * k}
            height={HOUSE.height * k}
            className={cx(styles.piece, styles.house)}
          />
          <rect
            x={x * k}
            y={y(HOUSE.top)}
            width={HOUSE.width * k}
            height={HOUSE.cleat * k}
            className={cx(styles.piece, styles.cleat)}
          />
          <rect
            x={x * k}
            y={y(HOUSE.top - HOUSE.height + HOUSE.spacer)}
            width={HOUSE.width * k}
            height={HOUSE.spacer * k}
            className={cx(styles.piece, styles.spacer)}
          />
          <text
            x={(x + HOUSE.width / 2) * k}
            y={y(HOUSE.top - HOUSE.height / 2)}
            fontSize={12}
            className={styles.pieceLabel}
          >
            {labels.house}
          </text>
        </g>
      ))}

      {ticks.map((value) => (
        <g key={value}>
          <line x1={-6} y1={y(value)} x2={0} y2={y(value)} className={styles.tick} />
          <text x={-10} y={y(value)} className={cx(styles.text, styles.end, styles.central)}>
            {fmt.num(value)}
          </text>
        </g>
      ))}
      <text x={2 * k} y={y(201)} className={styles.text}>{labels.shortRails}</text>
      <text x={2 * k} y={y(239)} className={styles.text}>{labels.longRail}</text>
    </svg>
  );
}

const PROFILE_SCALE = 28;

// A beveled strip as it leaves the saw (left) and as it sits once mounted (right)
export function Profile({ variant, labels, fmt }) {
  const k = PROFILE_SCALE;
  const t = THICKNESS;
  const isRail = variant === 'rail';
  const full = isRail ? RAIL_WIDTH : 3.5;
  const narrow = full - BEVEL;

  const wallX = 11.5;
  const top = 0.4;
  const mountedMid = top + full / 2;
  const rawY = mountedMid - t / 2;
  const labelX = (wallX + 3) * k;

  const raw = [[0, 0], [narrow, 0], [full, t], [0, t]];
  const waste = [[narrow, 0], [full, 0], [full, t]];
  // rail: the bevel faces up and rises outward; cleat: it faces down, toward the rail
  const mounted = isRail
    ? [[0, BEVEL], [t, 0], [t, full], [0, full]]
    : [[0, 0], [t, 0], [t, narrow], [0, full]];
  const rows = isRail
    ? { outer: top + 1, outerFrom: [t + 0.1, 1.3], ramp: top + 2.3, inner: top + 3.6, innerFrom: [0.4, 3.9] }
    : { outer: top + 0.6, outerFrom: [t + 0.1, 0.9], ramp: top + 1.7, inner: top + 2.8, innerFrom: [0.4, 2.6] };
  const captionY = top + full + 0.95;
  const bottom = Math.max(captionY, rawY + t + 1.7) + 0.35;
  const arrowY = mountedMid * k;

  return (
    <svg
      className={cx(styles.svg, styles.palette)}
      viewBox={`-4 0 ${labelX + 330} ${bottom * k}`}
      role="img"
      aria-label={labels.title}
    >
      <polygon points={toPoints(raw, k, 0, rawY)} className={cx(styles.piece, styles[variant])} />
      <polygon points={toPoints(waste, k, 0, rawY)} className={cx(styles.piece, styles.waste)} />
      <line
        x1={narrow * k}
        y1={rawY * k}
        x2={full * k}
        y2={(rawY + t) * k}
        className={cx(styles.mark, styles.dashedMark)}
      />
      <Dimension x1={0} x2={narrow * k} y={(rawY - 0.4) * k} label={fmt.cota(narrow)} labelDy={-7} />
      <Dimension x1={0} x2={full * k} y={(rawY + t + 0.4) * k} label={fmt.cota(full)} labelDy={17} />
      <text x={(full + 0.3) * k} y={(rawY - 0.15) * k} className={styles.muted}>
        {`${labels.waste} ${fmt.num(BEVEL)} × ${fmt.num(BEVEL)}`}
      </text>
      <text x={0} y={(rawY + t + 1.7) * k} className={styles.text}>{labels.raw}</text>

      <path
        d={`M ${(wallX - 4.6) * k} ${arrowY} H ${(wallX - 1.4) * k} m -8 -5 l 8 5 l -8 5`}
        className={styles.arrow}
      />

      <WallSection x={wallX * k} y1={(top - 0.3) * k} y2={(top + full + 0.3) * k} />
      <polygon points={toPoints(mounted, k, wallX, top)} className={cx(styles.piece, styles[variant])} />
      <text x={(wallX + t / 2) * k} y={captionY * k} className={cx(styles.muted, styles.middle)}>
        {labels.mounted}
      </text>
      <Callout
        from={[(wallX + rows.outerFrom[0]) * k, (top + rows.outerFrom[1]) * k]}
        labelX={labelX}
        labelY={rows.outer * k}
      >
        {labels.outer}
      </Callout>
      <text x={labelX} y={rows.ramp * k} className={cx(styles.muted, styles.central)}>{labels.ramp}</text>
      <Callout
        from={[(wallX + rows.innerFrom[0]) * k, (top + rows.innerFrom[1]) * k]}
        labelX={labelX}
        labelY={rows.inner * k}
      >
        {labels.inner}
      </Callout>
    </svg>
  );
}

// Side section of a platform on its rail. "detail" shows the whole top and the hinge;
// "fit" zooms in on the two ramps.
export function Assembly({ variant, labels }) {
  const isDetail = variant === 'detail';
  const k = isDetail ? 16 : 28;
  const t = THICKNESS;
  const topLength = isDetail ? 28 : 11.5;
  const labelX = (topLength + (isDetail ? 2 : 1.5)) * k;

  const rail = [[0, 3.5], [t, 2], [t, BACK_HEIGHT], [0, BACK_HEIGHT]];
  const cleat = [[0, 0], [t, 0], [t, 2], [0, 3.5]];
  const callouts = isDetail
    ? [
      ['cleat', [0.75, 1], 0.2],
      ['back', [2.25, 1.8], 1.8],
      ['rail', [0.75, 5.6], 3.4],
      ['hinge', [5, 6.8], 5],
      ['top', [topLength - 2, 7.75], 7.75],
    ]
    : [
      ['back', [2.6, 1], 0.4],
      ['ramps', [0.75, 2.75], 2.75],
      ['top', [9, 7.4], 6.2],
    ];
  const wallTop = -1;
  const wallBottom = BACK_HEIGHT + t + 1;

  return (
    <svg
      className={cx(styles.svg, styles.palette)}
      viewBox={`-12 ${(wallTop - 0.3) * k} ${labelX + 300} ${(wallBottom - wallTop + 0.9) * k}`}
      role="img"
      aria-label={labels.title}
    >
      <WallSection x={0} y1={wallTop * k} y2={wallBottom * k} />
      <polygon points={toPoints(rail, k)} className={cx(styles.piece, styles.rail)} />
      <polygon points={toPoints(cleat, k)} className={cx(styles.piece, styles.cleat)} />
      <rect x={t * k} y={0} width={t * k} height={BACK_HEIGHT * k} className={cx(styles.piece, styles.back)} />
      <rect x={0} y={BACK_HEIGHT * k} width={topLength * k} height={t * k} className={cx(styles.piece, styles.top)} />
      {isDetail ? (
        <g className={styles.hinge}>
          <rect x={3 * k} y={3.8 * k} width={0.35 * k} height={2.5 * k} />
          <circle cx={3.18 * k} cy={6.6 * k} r={0.38 * k} />
          <rect x={3.4 * k} y={6.6 * k} width={2.8 * k} height={0.35 * k} />
        </g>
      ) : (
        <line x1={0} y1={3.5 * k} x2={t * k} y2={2 * k} className={styles.mark} />
      )}
      {callouts.map(([key, [x, y], row]) => (
        <Callout key={key} from={[x * k, y * k]} labelX={labelX} labelY={row * k}>
          {labels[key]}
        </Callout>
      ))}
    </svg>
  );
}

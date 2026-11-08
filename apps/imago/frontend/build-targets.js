// Converte a lista do browserslist ("chrome 141", "ios_saf 16.4-16.7"...) no formato de alvo do
// build do Vite ("chrome141", "ios16.4"), com a menor versão de cada navegador

const ENGINES = {
  chrome: 'chrome',
  edge: 'edge',
  firefox: 'firefox',
  safari: 'safari',
  ios_saf: 'ios',
};

function compareVersions(a, b) {
  const left = a.split('.').map(Number);
  const right = b.split('.').map(Number);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export function buildTargets(browsers) {
  const lowest = new Map();
  for (const entry of browsers) {
    const [name, range] = entry.split(' ');
    const engine = ENGINES[name];
    // Navegador fora da lista (ex.: um "and_chr" por engano no browserslist): sem alvo próprio
    if (!engine || !range) continue;
    // "16.4-16.7": vale o começo do intervalo; "16.0" vira "16"
    const version = range.split('-')[0].replace(/\.0$/, '');
    if (!/^\d+(\.\d+)*$/.test(version)) continue;
    const current = lowest.get(engine);
    if (current === undefined || compareVersions(version, current) < 0) {
      lowest.set(engine, version);
    }
  }
  if (lowest.size === 0) {
    throw new Error('browserslist sem nenhum navegador conhecido');
  }
  return [...lowest].map(([engine, version]) => `${engine}${version}`).sort();
}

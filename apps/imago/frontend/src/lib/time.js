// Fuso do navegador e nomes de fuso IANA. O backend confere o nome contra a base de fusos dele
// (422 invalid_timezone); aqui é só o que o navegador conhece

const formatters = new Map();

/** Fuso IANA do navegador; "UTC" se o navegador não informar. */
export function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Se o navegador conhece o fuso `timeZone`. Os já conferidos ficam guardados. */
export function isValidTimezone(timeZone) {
  if (typeof timeZone !== 'string' || timeZone === '') return false;
  if (formatters.has(timeZone)) return true;
  try {
    formatters.set(timeZone, new Intl.DateTimeFormat('en-US', { timeZone }));
    return true;
  } catch {
    return false;
  }
}

function canonicalTimezone(timeZone) {
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone }).resolvedOptions().timeZone;
  } catch {
    return timeZone;
  }
}

/** Mesmo fuso, aceitando grafias diferentes do mesmo nome (ex.: "utc" e "UTC"). */
export function sameTimezone(a, b) {
  return canonicalTimezone(a) === canonicalTimezone(b);
}

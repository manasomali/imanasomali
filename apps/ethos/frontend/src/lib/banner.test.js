import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BANNER_TEXT_MAX_LENGTH,
  DISMISSED_BANNERS_KEY,
  MAX_DISMISSED,
  bannerForm,
  bannerPayload,
  bannerStatus,
  bannerText,
  bannerTextLength,
  dismissBanner,
  dismissedBanners,
  isBannerDismissed,
  singleLine,
} from './banner';

const SAO_PAULO = 'America/Sao_Paulo';

afterEach(() => {
  vi.restoreAllMocks();
});

function banner(overrides = {}) {
  return {
    id: 7,
    text_pt: 'Manutenção hoje',
    text_en: 'Maintenance today',
    starts_at: '2026-11-01T12:00:00Z',
    ends_at: '2026-11-08T12:00:00Z',
    ...overrides,
  };
}

function blockStorage() {
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new DOMException('blocked', 'SecurityError');
  });
}

describe('dismissed banners', () => {
  it('remembers each closed banner by id', () => {
    expect(isBannerDismissed(7)).toBe(false);

    expect(dismissBanner(7)).toBe(true);
    dismissBanner(9);

    expect(isBannerDismissed(7)).toBe(true);
    expect(isBannerDismissed(9)).toBe(true);
    expect(isBannerDismissed(8)).toBe(false);
    expect(JSON.parse(window.localStorage.getItem(DISMISSED_BANNERS_KEY))).toEqual([7, 9]);
  });

  it('keeps only the most recent ids, without repeating', () => {
    for (let id = 1; id <= MAX_DISMISSED + 5; id += 1) dismissBanner(id);
    dismissBanner(10);

    const ids = dismissedBanners();

    expect(ids).toHaveLength(MAX_DISMISSED);
    expect(ids.at(-1)).toBe(10);
    expect(ids.filter((id) => id === 10)).toHaveLength(1);
    expect(isBannerDismissed(1)).toBe(false);
  });

  it('treats a broken saved value as nothing closed', () => {
    for (const value of ['{', '"7"', '{"id":7}', 'null']) {
      window.localStorage.setItem(DISMISSED_BANNERS_KEY, value);

      expect(dismissedBanners()).toEqual([]);
    }

    window.localStorage.setItem(DISMISSED_BANNERS_KEY, '[7, "8", -1, 1.5, null, 9]');

    expect(dismissedBanners()).toEqual([7, 9]);
  });

  it('refuses ids that are not positive integers', () => {
    for (const id of [0, -1, 1.5, '7', null, undefined, Number.MAX_SAFE_INTEGER + 1]) {
      expect(dismissBanner(id)).toBe(false);
    }
    expect(window.localStorage.getItem(DISMISSED_BANNERS_KEY)).toBeNull();
  });

  it('survives blocked storage', () => {
    blockStorage();

    expect(dismissBanner(7)).toBe(false);
    expect(isBannerDismissed(7)).toBe(false);
  });
});

describe('banner text', () => {
  it('picks the language of the screen', () => {
    expect(bannerText(banner(), 'pt')).toBe('Manutenção hoje');
    expect(bannerText(banner(), 'pt-BR')).toBe('Manutenção hoje');
    expect(bannerText(banner(), 'en')).toBe('Maintenance today');
    expect(bannerText(banner(), undefined)).toBe('Maintenance today');
  });

  it('counts characters like the API: trimmed, one per code point', () => {
    expect(bannerTextLength('  abc  ')).toBe(3);
    expect(bannerTextLength('👍🏽 ok')).toBe(5);
    expect(bannerTextLength('😀'.repeat(BANNER_TEXT_MAX_LENGTH))).toBe(BANNER_TEXT_MAX_LENGTH);
  });

  it('turns line breaks into spaces', () => {
    expect(singleLine('a\nb\r\nc\n\nd')).toBe('a b c d');
    expect(singleLine('no breaks')).toBe('no breaks');
  });
});

describe('banner status', () => {
  const now = Date.parse('2026-11-05T12:00:00Z');

  it('marks the one the public endpoint returns as live', () => {
    expect(bannerStatus(banner(), now, 7)).toBe('live');
  });

  it('tells scheduled, ended and hidden banners apart', () => {
    expect(bannerStatus(banner({ starts_at: '2026-11-06T00:00:00Z' }), now, null)).toBe('scheduled');
    expect(bannerStatus(banner({ ends_at: '2026-11-05T12:00:00Z' }), now, null)).toBe('ended');
    expect(bannerStatus(banner(), now, 8)).toBe('waiting');
    expect(bannerStatus(banner(), now, undefined)).toBe('waiting');
  });
});

describe('banner form', () => {
  it('starts a new banner now, in the admin time zone', () => {
    expect(bannerForm(null, SAO_PAULO, Date.parse('2026-11-01T12:34:56Z'))).toEqual({
      text_pt: '',
      text_en: '',
      starts_at: '2026-11-01T09:34',
      ends_at: '',
    });
  });

  it('fills an existing banner in the admin time zone', () => {
    expect(bannerForm(banner(), SAO_PAULO)).toEqual({
      text_pt: 'Manutenção hoje',
      text_en: 'Maintenance today',
      starts_at: '2026-11-01T09:00',
      ends_at: '2026-11-08T09:00',
    });
  });
});

describe('banner payload', () => {
  const valid = {
    text_pt: '  Olá <b>todos</b>  ',
    text_en: 'Hello',
    starts_at: '2026-11-01T09:00',
    ends_at: '2026-11-02T21:30',
  };

  it('builds the POST body with trimmed texts and UTC instants', () => {
    expect(bannerPayload(valid, SAO_PAULO)).toEqual({
      values: {
        text_pt: 'Olá <b>todos</b>',
        text_en: 'Hello',
        starts_at: '2026-11-01T12:00:00.000Z',
        ends_at: '2026-11-03T00:30:00.000Z',
      },
      errors: {},
    });
  });

  it('requires both texts and limits them to 280 characters', () => {
    const { errors } = bannerPayload(
      { ...valid, text_pt: '   ', text_en: 'x'.repeat(BANNER_TEXT_MAX_LENGTH + 1) },
      SAO_PAULO,
    );

    expect(errors).toEqual({ text_pt: 'required', text_en: 'too_long' });
    expect(bannerPayload({ ...valid, text_en: 'x'.repeat(BANNER_TEXT_MAX_LENGTH) }, SAO_PAULO).errors).toEqual(
      {},
    );
  });

  it('requires valid dates from 1900 on', () => {
    expect(bannerPayload({ ...valid, starts_at: '', ends_at: '2026-02-30T10:00' }, SAO_PAULO).errors).toEqual({
      starts_at: 'required',
      ends_at: 'invalid_date',
    });
    expect(bannerPayload({ ...valid, starts_at: '1899-12-31T10:00' }, SAO_PAULO).errors).toEqual({
      starts_at: 'invalid_date',
    });
  });

  it('requires the end after the start', () => {
    expect(bannerPayload({ ...valid, ends_at: valid.starts_at }, SAO_PAULO).errors).toEqual({
      ends_at: 'ends_before_starts',
    });
    expect(bannerPayload({ ...valid, ends_at: '2026-10-31T09:00' }, SAO_PAULO).errors).toEqual({
      ends_at: 'ends_before_starts',
    });
  });

  it('sends only the changed fields when editing', () => {
    const current = banner();
    const form = bannerForm(current, SAO_PAULO);

    expect(bannerPayload(form, SAO_PAULO, current)).toEqual({ values: {}, errors: {} });
    expect(bannerPayload({ ...form, text_en: ' Maintenance tonight ' }, SAO_PAULO, current).values).toEqual({
      text_en: 'Maintenance tonight',
    });
    expect(bannerPayload({ ...form, ends_at: '2026-11-09T09:00' }, SAO_PAULO, current).values).toEqual({
      ends_at: '2026-11-09T12:00:00.000Z',
    });
  });

  it('keeps the exact instants of untouched dates', () => {
    // Banner agendado encerrado antes de começar: o início fica 1 µs antes do fim
    const ended = banner({ starts_at: '2026-11-05T12:00:00.999999Z', ends_at: '2026-11-05T12:00:01Z' });
    const form = bannerForm(ended, SAO_PAULO);

    expect(form.starts_at).toBe(form.ends_at);
    expect(bannerPayload({ ...form, text_pt: 'Outro texto' }, SAO_PAULO, ended)).toEqual({
      values: { text_pt: 'Outro texto' },
      errors: {},
    });
  });

  it('checks the window against the untouched date', () => {
    const current = banner();
    const form = bannerForm(current, SAO_PAULO);

    expect(bannerPayload({ ...form, ends_at: '2026-10-31T09:00' }, SAO_PAULO, current).errors).toEqual({
      ends_at: 'ends_before_starts',
    });
  });
});

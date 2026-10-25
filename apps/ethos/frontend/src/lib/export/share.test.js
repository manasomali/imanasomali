import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { canShareFile, downloadBlob, shareOrDownload } from './share';

const file = () => new File(['png'], 'ethos-2026-03-01_2026-03-31.png', { type: 'image/png' });

let clicks;

beforeEach(() => {
  clicks = [];
  // O jsdom não implementa as URLs de blob nem o download
  URL.createObjectURL = vi.fn(() => 'blob:ethos/1');
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click() {
    clicks.push({ href: this.href, download: this.download, connected: this.isConnected });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
});

function sharingNavigator({ canShare = true, share = vi.fn(async () => {}) } = {}) {
  return { canShare: vi.fn(() => canShare), share };
}

describe('canShareFile', () => {
  it('asks navigator.canShare with the file', () => {
    const nav = sharingNavigator();
    const value = file();

    expect(canShareFile(value, nav)).toBe(true);
    expect(nav.canShare).toHaveBeenCalledWith({ files: [value] });
    expect(canShareFile(value, sharingNavigator({ canShare: false }))).toBe(false);
  });

  it('is false without the API or when it throws', () => {
    expect(canShareFile(file(), {})).toBe(false);
    expect(canShareFile(file(), { share: () => {} })).toBe(false);
    expect(canShareFile(file(), { canShare: () => true })).toBe(false);
    expect(canShareFile(file(), undefined)).toBe(false);
    expect(
      canShareFile(file(), {
        share: () => {},
        canShare: () => {
          throw new TypeError('no');
        },
      }),
    ).toBe(false);
  });
});

describe('shareOrDownload', () => {
  it('shares when the browser shares files', async () => {
    const nav = sharingNavigator();
    const value = file();

    expect(await shareOrDownload(value, { nav, title: 'My habits' })).toBe('shared');
    expect(nav.share).toHaveBeenCalledWith({ files: [value], title: 'My habits' });
    expect(clicks).toEqual([]);
  });

  it('downloads without share support (mocked navigator)', async () => {
    expect(await shareOrDownload(file(), { nav: {} })).toBe('downloaded');
    expect(await shareOrDownload(file(), { nav: sharingNavigator({ canShare: false }) })).toBe('downloaded');
    expect(clicks).toEqual([
      { href: 'blob:ethos/1', download: 'ethos-2026-03-01_2026-03-31.png', connected: true },
      { href: 'blob:ethos/1', download: 'ethos-2026-03-01_2026-03-31.png', connected: true },
    ]);
  });

  it('does nothing when the person closes the share sheet', async () => {
    const share = vi.fn(async () => {
      throw new DOMException('closed', 'AbortError');
    });

    expect(await shareOrDownload(file(), { nav: sharingNavigator({ share }) })).toBe('canceled');
    expect(clicks).toEqual([]);
  });

  it('downloads when sharing fails for another reason', async () => {
    const share = vi.fn(async () => {
      throw new DOMException('no gesture', 'NotAllowedError');
    });

    expect(await shareOrDownload(file(), { nav: sharingNavigator({ share }) })).toBe('downloaded');
    expect(clicks).toHaveLength(1);
  });

  it('uses the page navigator by default', async () => {
    expect(await shareOrDownload(file())).toBe('downloaded');
  });
});

describe('downloadBlob', () => {
  it('clicks a temporary link and frees the URL later', () => {
    vi.useFakeTimers();
    const blob = new Blob(['a,b'], { type: 'text/csv' });

    downloadBlob(blob, 'report.csv');

    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(clicks).toEqual([{ href: 'blob:ethos/1', download: 'report.csv', connected: true }]);
    expect(document.querySelector('a[download]')).toBeNull();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:ethos/1');
  });
});

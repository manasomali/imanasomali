import { describe, expect, it } from 'vitest';
import { guestSlots } from './sharing';

const owner = { user: { id: 1, email: 'ana@example.com' }, role: 'owner' };
const editor = { user: { id: 2, email: 'bia@example.com' }, role: 'editor' };
const viewer = { user: { id: 3, email: 'caio@example.com' }, role: 'viewer' };

describe('guest slots', () => {
  it('counts members without the owner plus pending invites', () => {
    expect(guestSlots([owner, editor, viewer], [{ id: 9 }], 5)).toEqual({ used: 3, limit: 5, left: 2 });
  });

  it('starts empty with only the owner', () => {
    expect(guestSlots([owner], [], 5)).toEqual({ used: 0, limit: 5, left: 5 });
  });

  it('never goes below zero when the limit was lowered', () => {
    expect(guestSlots([owner, editor, viewer], [{ id: 9 }], 2)).toEqual({ used: 3, limit: 2, left: 0 });
  });
});

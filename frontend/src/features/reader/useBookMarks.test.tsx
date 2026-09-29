import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { useBookMarks } from './useBookMarks';
const mark = (id: string) => ({ id, locator: { chapter: 0 }, label: id, created_at: '' });
afterEach(() => vi.restoreAllMocks());
it('ignores the old unit marks GET after navigation', async () => {
  let release!: (value: unknown) => void;
  vi.spyOn(api, 'get').mockImplementation((path) => path.includes('/old/') ? new Promise(resolve => { release = resolve; }) as never : Promise.resolve({ bookmarks: [mark('new')], highlights: [] }) as never);
  const { result, rerender } = renderHook(({ id }) => useBookMarks(id), { initialProps: { id: 'old' } });
  rerender({ id: 'new' });
  await waitFor(() => expect(result.current.bookmarks[0]?.id).toBe('new'));
  await act(async () => release({ bookmarks: [mark('old')], highlights: [] }));
  expect(result.current.bookmarks.map(m => m.id)).toEqual(['new']);
});
it('ignores an old unit bookmark POST after navigation', async () => {
  let release!: (value: unknown) => void;
  vi.spyOn(api, 'get').mockResolvedValue({ bookmarks: [], highlights: [] });
  vi.spyOn(api, 'post').mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const { result, rerender } = renderHook(({ id }) => useBookMarks(id), { initialProps: { id: 'old' } });
  await act(async () => {});
  let pending!: Promise<void>;
  act(() => { pending = result.current.addBookmark({ chapter: 0 }, 'old'); });
  rerender({ id: 'new' });
  await act(async () => { release(mark('old')); await pending; });
  expect(result.current.bookmarks).toEqual([]);
});

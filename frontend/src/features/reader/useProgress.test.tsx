import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '@/api/client';
import { useProgress } from './useProgress';

function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const state = (revision: number) => ({ read_state: 'partial', fraction: .2, locator: null, revision });
afterEach(() => vi.restoreAllMocks());

it('recovers saving after the initial revision request fails', async () => {
  vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(state(8));
  const post = vi.spyOn(api, 'post').mockResolvedValue(state(9));
  const { result } = renderHook(() => useProgress('unit'));
  await act(async () => {});
  act(() => { result.current.record(.4, { page: 4 }); result.current.flush(); });
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/reader/units/unit/progress',
    { fraction: .4, locator: { page: 4 }, revision: 8 }));
});

it('isolates late writes from the revision of the newly opened unit', async () => {
  const old = deferred<ReturnType<typeof state>>();
  vi.spyOn(api, 'get').mockImplementation(async (path) => state(path.includes('/old/') ? 5 : 20) as never);
  const post = vi.spyOn(api, 'post').mockImplementation((path) => path.includes('/old/') ? old.promise as never : Promise.resolve(state(21)) as never);
  const { result, rerender } = renderHook(({ id }) => useProgress(id), { initialProps: { id: 'old' } });
  await waitFor(() => expect(result.current.stored?.revision).toBe(5));
  act(() => { result.current.record(.3, { page: 3 }); result.current.flush(); });
  rerender({ id: 'new' });
  await waitFor(() => expect(result.current.stored?.revision).toBe(20));
  await act(async () => old.resolve(state(6)));
  act(() => { result.current.record(.4, { page: 4 }); result.current.flush(); });
  expect(post).toHaveBeenLastCalledWith('/api/reader/units/new/progress', expect.objectContaining({ revision: 20 }));
});

it('serializes in-flight saves and flushes the last position on exit using the resulting revision', async () => {
  const first = deferred<ReturnType<typeof state>>();
  vi.spyOn(api, 'get').mockResolvedValue(state(5));
  const post = vi.spyOn(api, 'post').mockReturnValueOnce(first.promise).mockResolvedValue(state(7));
  const { result, unmount } = renderHook(() => useProgress('unit'));
  await waitFor(() => expect(result.current.stored).not.toBeNull());
  act(() => { result.current.record(.3, {}); result.current.flush(); });
  act(() => { result.current.record(.7, {}); result.current.flush(); });
  expect(post).toHaveBeenCalledTimes(1);
  unmount();
  await act(async () => first.resolve(state(6)));
  expect(post).toHaveBeenLastCalledWith('/api/reader/units/unit/progress', { fraction: .7, locator: {}, revision: 6 });
});

it('waits for the initial revision before flushing an early interaction', async () => {
  const initial = deferred<ReturnType<typeof state>>();
  vi.spyOn(api, 'get').mockReturnValue(initial.promise);
  const post = vi.spyOn(api, 'post').mockResolvedValue(state(9));
  const { result, unmount } = renderHook(() => useProgress('unit'));
  act(() => { result.current.record(.4, {}); result.current.flush(); });
  expect(post).not.toHaveBeenCalled();
  unmount();
  await act(async () => initial.resolve(state(8)));
  expect(post).toHaveBeenCalledWith('/api/reader/units/unit/progress', expect.objectContaining({ revision: 8 }));
});

it('discards queued positions on STALE_PROGRESS instead of replaying them over another tab', async () => {
  const first = deferred<ReturnType<typeof state>>();
  vi.spyOn(api, 'get').mockResolvedValueOnce(state(5)).mockResolvedValue(state(20));
  const post = vi.spyOn(api, 'post').mockReturnValueOnce(first.promise).mockResolvedValue(state(21));
  const { result } = renderHook(() => useProgress('unit'));
  await waitFor(() => expect(result.current.stored).not.toBeNull());
  act(() => { result.current.record(.3, {}); result.current.flush(); result.current.record(.4, {}); result.current.flush(); });
  await act(async () => first.reject(new ApiError(409, 'STALE_PROGRESS', 'Another tab is newer')));
  expect(post).toHaveBeenCalledTimes(1);
  act(() => { result.current.record(.5, {}); result.current.flush(); });
  expect(post).toHaveBeenLastCalledWith('/api/reader/units/unit/progress', expect.objectContaining({ fraction: .5, revision: 20 }));
});

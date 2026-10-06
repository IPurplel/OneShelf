import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/render';
import { get, mockApi } from '@/test/http';
import { ReadRoute } from './ReadRoute';
vi.mock('./BookReader', () => ({ BookReader: ({ format, unitId }: { format: string; unitId: string }) => <p>{format} reader {unitId}</p> }));
vi.mock('./ReaderScreen', () => ({ ReaderScreen: () => <p>page reader</p> }));
afterEach(() => vi.unstubAllGlobals());
const context = { work_id: 'w', track_id: 'second', formats: ['pdf', 'epub'] };
const details = { work: { id: 'w' }, units: [{ id: 'u', formats: ['pdf', 'epub'] }] };
function open(route: string) { return renderWithProviders(<Routes><Route path="/read/:unitId" element={<ReadRoute />} /></Routes>, { route }); }
it('resolves legacy unit-only links and loads the unit own track before selecting its reader', async () => {
  const calls = mockApi([get('/api/reader/units/u/context', context), get('/api/works/w', details)]);
  open('/read/u');
  expect(await screen.findByText('epub reader u')).toBeInTheDocument();
  expect(calls.some(call => call.url === '/api/works/w?track_id=second')).toBe(true);
});
it('shows an unavailable work error and a recovery link after a terminal 404', async () => {
  mockApi([get('/api/reader/units/u/context', context), { match: url => url.startsWith('/api/works/missing'), status: 404, payload: { error: { code: 'NOT_FOUND', message: 'Work missing' } } }]);
  open('/read/u?work=missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Work missing');
  expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
  expect(screen.getByRole('link')).toHaveAttribute('href', '/works/missing?track=second');
});
it('shows a missing-unit error instead of falling back to the page reader', async () => {
  mockApi([get('/api/reader/units/u/context', context), get('/api/works/w', { ...details, units: [] })]);
  open('/read/u?work=w&track=second');
  expect(await screen.findByRole('alert')).toHaveTextContent(/reading unit/i);
  expect(screen.queryByText('page reader')).not.toBeInTheDocument();
});
it('opens a text unit in the Book Reader whether or not it is downloaded', async () => {
  mockApi([get('/api/reader/units/u/context', { ...context, formats: [], kind: 'text' }), get('/api/works/w', details)]);
  open('/read/u');
  expect(await screen.findByText('text reader u')).toBeInTheDocument();
  expect(screen.queryByText('page reader')).not.toBeInTheDocument();
});
it('opens a downloaded text unit as text', async () => {
  mockApi([get('/api/reader/units/u/context', { ...context, formats: ['text'], kind: 'text' }), get('/api/works/w', details)]);
  open('/read/u');
  expect(await screen.findByText('text reader u')).toBeInTheDocument();
});
it('keeps image units in the page reader', async () => {
  mockApi([get('/api/reader/units/u/context', { ...context, formats: [], kind: 'images' }), get('/api/works/w', details)]);
  open('/read/u');
  expect(await screen.findByText('page reader')).toBeInTheDocument();
});

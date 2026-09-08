/* OneShelf front-end.
   Plain ES modules, no framework and no build step - the whole UI is three
   static files served straight out of the container. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  series: null,
  chapters: [],
  selected: new Set(),
  /* Chapter indices the current filter leaves visible. The select buttons act
     on this, not on the whole list — see applyChapterFilter. */
  shown: new Set(),
  jobs: new Map(),
  /* The last /api/library answer, kept so filtering and sorting can rerun
     without another request (and another walk over the output directory). */
  library: [],
};

/* Statuses where a job still has work in flight. The same list the server
   calls ACTIVE_STATUSES, and the thing that decides the badge, the enabled
   toolbar buttons and whether the tab title shows progress. */
const ACTIVE = new Set(['running', 'queued', 'paused']);
const isActive = (job) => ACTIVE.has(job.status);

const BASE_TITLE = document.title;

/* ----------------------------------------------------------------- utils */

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

/* Bare hostname, which is what a person calls a site. Never throws: a URL that
   did not parse still has to render something. */
function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

const escapeHtml = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const power = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** power).toFixed(power ? 1 : 0)} ${units[power]}`;
}

/* Results used to be reported with alert(), which blocks the page — including
   the websocket repaint behind it — until it is dismissed. These say the same
   things without stopping anything. confirm() is deliberately left alone: a
   delete really should block until answered. */

function toast(message, kind = 'ok') {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.textContent = message;
  $('#toasts').append(node);
  const drop = () => node.remove();
  node.addEventListener('click', drop);
  setTimeout(() => {
    node.classList.add('leaving');
    node.addEventListener('transitionend', drop, { once: true });
    setTimeout(drop, 400);   // in case transitions are off
  }, kind === 'error' ? 7000 : 4000);
}

/* Every await in an event handler needs this. Without it a rejected promise is
   swallowed by the runtime: the click appears to do nothing at all, and the
   only trace is a console warning nobody is looking at. */
const reporting = (fn) => (...args) =>
  Promise.resolve()
    .then(() => fn(...args))
    .catch((error) => toast(error.message || String(error), 'error'));

/* ------------------------------------------------------------------ tabs */

function showView(name, { remember = true } = {}) {
  const tab = $(`.tab[data-view="${name}"]`);
  if (!tab) return;

  $$('.tab').forEach((t) => {
    t.classList.toggle('is-active', t === tab);
    t.setAttribute('aria-selected', String(t === tab));
  });
  $$('.view').forEach((v) => v.classList.toggle('is-active', v.id === `view-${name}`));
  if (remember) localStorage.setItem('view', name);

  if (name === 'library') reporting(loadLibrary)();
  if (name === 'settings') {
    reporting(loadSettings)();
    reporting(loadSessionStatus)();
  }
  // The queue view skips its repaint while it is hidden, so anything that
  // arrived in the meantime has to be drawn now — after is-active is set.
  if (name === 'queue' && jobsDirty) renderJobs();
}

$$('.tab').forEach((tab) => {
  tab.addEventListener('click', () => showView(tab.dataset.view));
});

/* ----------------------------------------------------------------- theme */

/* The stylesheet has always carried a full [data-theme] palette; nothing ever
   set the attribute, so the only way to get the dark one was to change the
   whole operating system. Three states, because "follow the OS" has to remain
   reachable after an explicit choice. */

const THEMES = ['system', 'light', 'dark'];
const THEME_ICON = { system: '🖥️', light: '☀️', dark: '🌙' };

function applyTheme(theme) {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  const button = $('#theme-toggle');
  button.textContent = THEME_ICON[theme];
  button.title = `Theme: ${theme} (click to change)`;
  button.setAttribute('aria-label', `Theme: ${theme}`);
}

let theme = localStorage.getItem('theme');
if (!THEMES.includes(theme)) theme = 'system';
applyTheme(theme);

$('#theme-toggle').addEventListener('click', () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  localStorage.setItem('theme', theme);
  applyTheme(theme);
});

/* ---------------------------------------------------------------- search */

/* Searching hits several sites at once, each behind a browser that may have to
   clear a bot check, so a request per keystroke would be both slow and rude.
   The input is debounced, only the newest response renders, and the request in
   flight is aborted when a newer one starts — dropping the stale *response* was
   never enough, because the server runs an abandoned search to its full 20s
   timeout and every site shares one rate limiter. */

let searchTimer = null;
let searchToken = 0;
let searchAbort = null;

function abandonSearch() {
  if (searchAbort) searchAbort.abort();
  searchAbort = null;
}

/* Which kind is being searched. Defaults to everything: the old flow left the
   field disabled until one of three chips was clicked, so the first thing you
   met was a control that did nothing. Results are grouped by kind, which is
   what made searching everything unusable before — they were interleaved. */
let searchKind = 'all';

/* The source catalogue from /api/sources, and the hosts switched off in the
   picker. Kept as "off" rather than "on" so a site added to the config later
   is searched by default instead of silently excluded. */
let sourceKinds = [];
let disabledHosts = new Set();
let searchSort = 'relevance';
let lastSearch = null;          // the last rendered payload, for re-sorting
let cursor = -1;                // keyboard position within the results

const RECENTS_KEY = 'md.recentSearches';
const OFF_KEY = 'md.disabledSources';
const MAX_RECENTS = 6;

/* localStorage is unavailable in some privacy modes and throws on access
   rather than returning null, so every touch is guarded. A missing preference
   is not an error — it just means "search everything". */
function readStore(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch { return fallback; }
}
function writeStore(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
}

const KIND_LABEL = { book: 'Books', manga: 'Manga', comics: 'Comics', all: 'All' };

/* ---- the source catalogue ---- */

async function loadSources() {
  try {
    const data = await api('/api/sources');
    sourceKinds = data.kinds || [];
  } catch {
    // A catalogue we could not load must not disable searching: fall back to
    // the three kinds with no counts, which still works.
    sourceKinds = ['manga', 'comics', 'book'].map((type) => (
      { type, label: KIND_LABEL[type], sites: [], count: 0 }
    ));
  }
  disabledHosts = new Set(readStore(OFF_KEY, []));
  renderKinds();
  renderSourcePicker();
}

/* Every site the current category could ask, whether or not it is switched on. */
function sitesForKind(kind) {
  return sourceKinds
    .filter((k) => kind === 'all' || k.type === kind)
    .flatMap((k) => k.sites.map((site) => ({ ...site, type: k.type })));
}

function activeSites(kind) {
  return sitesForKind(kind).filter((s) => !disabledHosts.has(s.host));
}

function renderKinds() {
  const total = sourceKinds.reduce((sum, k) => sum + k.count, 0);
  const rows = [{ type: 'all', label: 'All', count: total }, ...sourceKinds];
  $('#search-kinds').innerHTML = rows.map((row) => `
    <button type="button" class="kind${row.type === searchKind ? ' is-active' : ''}"
            role="tab" data-kind="${row.type}"
            aria-selected="${row.type === searchKind}"
            ${row.count ? '' : 'disabled title="No searchable sites for this yet"'}>
      ${escapeHtml(row.label)}<span class="kind-count">${row.count}</span>
    </button>`).join('');
  updateSourceCount();
}

function updateSourceCount() {
  const all = sitesForKind(searchKind).length;
  const on = activeSites(searchKind).length;
  $('#sources-count').textContent = on === all ? `${all}` : `${on}/${all}`;
  $('#sources-btn').disabled = all === 0;
}

function renderSourcePicker() {
  const sites = sitesForKind(searchKind);
  const list = $('#sources-list');
  if (!sites.length) {
    list.innerHTML = '<p class="popover-empty">No searchable sites for this category yet. '
      + 'Paste a URL instead.</p>';
    return;
  }
  list.innerHTML = sites.map((site) => `
    <label class="source-row">
      <input type="checkbox" data-host="${escapeHtml(site.host)}"
             ${disabledHosts.has(site.host) ? '' : 'checked'}>
      <span class="source-row-host">${escapeHtml(site.host)}</span>
      <span class="source-row-kind">${escapeHtml(KIND_LABEL[site.type] || site.type)}</span>
    </label>`).join('');
}

$('#sources-list').addEventListener('change', (event) => {
  const box = event.target.closest('input[data-host]');
  if (!box) return;
  if (box.checked) disabledHosts.delete(box.dataset.host);
  else disabledHosts.add(box.dataset.host);
  writeStore(OFF_KEY, [...disabledHosts]);
  updateSourceCount();
  rerunSearch();
});

$('#sources-all').addEventListener('click', () => {
  for (const site of sitesForKind(searchKind)) disabledHosts.delete(site.host);
  writeStore(OFF_KEY, [...disabledHosts]);
  renderSourcePicker();
  updateSourceCount();
  rerunSearch();
});

/* ---- the sources popover ---- */

function toggleSources(open) {
  const popover = $('#sources-popover');
  const wanted = open ?? popover.hidden;
  popover.hidden = !wanted;
  $('#sources-btn').setAttribute('aria-expanded', String(wanted));
}

$('#sources-btn').addEventListener('click', (event) => {
  event.stopPropagation();
  toggleSources();
});

/* Click-away and Escape both close it. Without these the panel stays open over
   the results it is meant to filter. */
document.addEventListener('click', (event) => {
  if (!event.target.closest('.popover-host')) toggleSources(false);
});

/* ---- category rail ---- */

$('#search-kinds').addEventListener('click', (event) => {
  const chip = event.target.closest('.kind');
  if (!chip || chip.disabled || chip.dataset.kind === searchKind) return;

  searchKind = chip.dataset.kind;
  renderKinds();
  renderSourcePicker();

  // Results from the previous category describe other things entirely, so they
  // go rather than sitting under a heading that no longer applies.
  clearTimeout(searchTimer);
  searchToken++;
  abandonSearch();
  const query = $('#search-input').value.trim();
  if (query.length >= 2) runSearch(query);
  else clearResults();
});

$('#search-sort').addEventListener('change', (event) => {
  searchSort = event.target.value;
  if (lastSearch) renderSearch(lastSearch);
});

/* ---- the field ---- */

const input = $('#search-input');

input.addEventListener('input', (event) => {
  const query = event.target.value.trim();
  clearTimeout(searchTimer);
  $('#search-clear').hidden = !event.target.value;

  if (query.length < 2) {
    // Clearing the box is as much an abandonment as retyping it.
    searchToken++;
    abandonSearch();
    clearResults();
    return;
  }
  showSkeletons();
  searchTimer = setTimeout(() => runSearch(query), 400);
});

$('#search-clear').addEventListener('click', () => {
  input.value = '';
  $('#search-clear').hidden = true;
  searchToken++;
  abandonSearch();
  clearResults();
  input.focus();
});

/* "/" is handled once, near the bottom of this file. There used to be a
   second handler here doing the same job by a different rule; being registered
   first it also ran first, so the later one silently overrode it and "/" did
   whatever that one decided. One shortcut, one handler. */

/* Arrow keys walk the results without leaving the field, Enter opens the one
   under the cursor, Escape backs out one step at a time. */
input.addEventListener('keydown', (event) => {
  const hits = $$('.search-hit', $('#search-results'));
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (!hits.length) return;
    event.preventDefault();
    cursor += event.key === 'ArrowDown' ? 1 : -1;
    if (cursor < 0) cursor = hits.length - 1;
    if (cursor >= hits.length) cursor = 0;
    moveCursor(hits);
  } else if (event.key === 'Enter' && cursor >= 0 && hits[cursor]) {
    event.preventDefault();
    hits[cursor].click();
  } else if (event.key === 'Enter') {
    // The box keeps its text after a result is opened, and search only fires
    // on `input` — so retyping the same query changes nothing and fires
    // nothing. Enter is the way back to the list you already had.
    event.preventDefault();
    if (heldSearch && $('#search-results').hidden
        && input.value.trim() === (heldSearch.query || '').trim()) {
      closePreview({ restore: true });
    } else {
      rerunSearch();
    }
  } else if (event.key === 'Escape') {
    if (!$('#sources-popover').hidden) { toggleSources(false); return; }
    if (cursor >= 0) { cursor = -1; moveCursor(hits); return; }
    input.value = '';
    $('#search-clear').hidden = true;
    clearResults();
  }
});

function moveCursor(hits) {
  hits.forEach((hit, index) => hit.classList.toggle('is-cursor', index === cursor));
  if (cursor >= 0) hits[cursor].scrollIntoView({ block: 'nearest' });
  input.setAttribute('aria-activedescendant', cursor >= 0 ? `hit-${cursor}` : '');
}

/* ---- recent searches ---- */

function renderRecents() {
  const recents = readStore(RECENTS_KEY, []);
  const box = $('#recents');
  // Only offered when there is nothing else in the space: a shortcut competing
  // with real results is noise.
  const idle = $('#search-results').hidden && input.value.trim().length < 2;
  if (!recents.length || !idle) { box.hidden = true; return; }
  $('#recents-list').innerHTML = recents.map((term) => `
    <button type="button" class="recent">${escapeHtml(term)}</button>`).join('');
  box.hidden = false;
}

function rememberSearch(query) {
  const recents = readStore(RECENTS_KEY, [])
    .filter((term) => term.toLowerCase() !== query.toLowerCase());
  recents.unshift(query);
  writeStore(RECENTS_KEY, recents.slice(0, MAX_RECENTS));
}

$('#recents-list').addEventListener('click', (event) => {
  const chip = event.target.closest('.recent');
  if (!chip) return;
  input.value = chip.textContent;
  $('#search-clear').hidden = false;
  input.focus();
  showSkeletons();
  runSearch(chip.textContent.trim());
});

$('#recents-clear').addEventListener('click', () => {
  writeStore(RECENTS_KEY, []);
  renderRecents();
});

/* ---- running a search ---- */

/* The rendered payload of the result list a preview was opened from.
   `clearResults()` nulls `lastSearch`, so without holding a copy here there is
   nothing left to go back to. */
let heldSearch = null;

function closePreview({ restore = false } = {}) {
  $('#preview').hidden = true;
  $('#back-to-results').hidden = true;
  if (restore && heldSearch) {
    // Straight from the payload we already have: going back to a list you
    // were just looking at must not depend on the network, or on the sites
    // answering the same way twice.
    renderSearch(heldSearch);
  }
  // #preview sits below .finder, so a long chapter list leaves the search box
  // scrolled off the top; landing back on a search you cannot see reads as
  // nothing having happened.
  $('.finder')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

$('#back-to-results').addEventListener('click', () => {
  closePreview({ restore: true });
  input.focus();
});

function rerunSearch() {
  const query = input.value.trim();
  if (query.length >= 2) runSearch(query);
}

function clearResults() {
  lastSearch = null;
  cursor = -1;
  $('#search-results').hidden = true;
  $('#search-results').innerHTML = '';
  $('#search-status').hidden = true;
  $('#source-readout').hidden = true;
  input.setAttribute('aria-expanded', 'false');
  renderRecents();
}

/* Placeholder cards rather than a spinner: they say results are coming *and*
   what shape they will be, and the count matches the sites actually being
   asked, so a one-site search does not promise a full grid. */
function showSkeletons() {
  const count = Math.min(Math.max(activeSites(searchKind).length, 2), 6);
  $('#search-results').innerHTML = Array.from({ length: count }, () => `
    <div class="search-hit skeleton" aria-hidden="true">
      <div class="sk-block sk-cover"></div>
      <div class="hit-text">
        <div class="sk-block sk-line"></div>
        <div class="sk-block sk-line short"></div>
      </div>
    </div>`).join('');
  $('#search-results').hidden = false;
  $('#recents').hidden = true;
  $('#search-status').textContent = 'Searching…';
  $('#search-status').hidden = false;
  input.setAttribute('aria-expanded', 'true');
}

async function runSearch(query) {
  abandonSearch();
  const token = ++searchToken;
  const kind = searchKind;
  const controller = new AbortController();
  searchAbort = controller;

  // Only send the site list when it is a real narrowing. Sending every host
  // would make the server re-derive a filter it already applies itself.
  const all = sitesForKind(kind);
  const on = activeSites(kind);
  const narrowed = on.length && on.length < all.length
    ? `&sites=${encodeURIComponent(on.map((s) => s.host).join(','))}`
    : '';

  if (on.length === 0 && all.length > 0) {
    // Every site switched off. Nothing to ask, and saying so is better than an
    // empty grid that looks like a failed search.
    lastSearch = null;
    $('#search-results').innerHTML =
      '<div class="search-empty"><p>Every source is switched off.</p>'
      + '<p>Turn one back on under Sources.</p></div>';
    $('#search-results').hidden = false;
    $('#search-status').hidden = true;
    $('#source-readout').hidden = true;
    return;
  }

  showSkeletons();
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`
                           + `&type=${encodeURIComponent(kind)}${narrowed}`,
                           { signal: controller.signal });
    if (token !== searchToken) return;   // a newer query is already in flight
    rememberSearch(query);
    renderSearch(data);
  } catch (error) {
    // We called it off on purpose; the newer query owns the status line now.
    if (error.name === 'AbortError') return;
    if (token !== searchToken) return;
    $('#search-results').hidden = true;
    $('#search-status').innerHTML =
      `Search failed: ${escapeHtml(error.message)}`;
    $('#search-status').hidden = false;
  }
}

/* ---- rendering ---- */

const PILL = {
  ok: { glyph: '', title: (s) => `${s.host} returned ${s.count}` },
  empty: { glyph: '—', title: (s) => `${s.host} had no match` },
  timeout: { glyph: '⏱', title: (s) => `${s.host} timed out` },
  error: { glyph: '!', title: (s) => `${s.host} could not be reached` },
  skipped: { glyph: '–', title: (s) => `${s.host} serves something else` },
};

/* Whether the "no match" sites are spelled out. Off by default: they are the
   bulk of any search and say the least. The ones that answered or failed are
   always shown — that is the whole point of the readout. */
let readoutExpanded = false;

function pill(site) {
  const shape = PILL[site.status] || PILL.empty;
  return `<span class="source-pill is-${escapeHtml(site.status)}"
                title="${escapeHtml(shape.title(site))}">
    <span class="pill-dot"></span>
    <span class="pill-host">${escapeHtml(site.host)}</span>
    ${site.status === 'ok' ? site.count : escapeHtml(shape.glyph)}
  </span>`;
}

function renderReadout(sites) {
  const box = $('#source-readout');
  if (!sites.length) { box.hidden = true; return; }

  const loud = sites.filter((s) => s.status !== 'empty' && s.status !== 'skipped');
  const quiet = sites.filter((s) => s.status === 'empty' || s.status === 'skipped');

  let html = loud.map(pill).join('');
  if (quiet.length && readoutExpanded) {
    html += quiet.map(pill).join('');
  }
  if (quiet.length) {
    html += `<span class="source-pill is-quiet">
      <button type="button" class="pill-more" id="readout-toggle">
        ${readoutExpanded ? 'hide' : `${quiet.length} no match`}
      </button></span>`;
  }
  box.innerHTML = html;
  box.hidden = false;
}

$('#source-readout').addEventListener('click', (event) => {
  if (!event.target.closest('#readout-toggle')) return;
  readoutExpanded = !readoutExpanded;
  if (lastSearch) renderReadout(lastSearch.sites || []);
});

function sortResults(results) {
  const rows = [...results];
  if (searchSort === 'title') {
    rows.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  } else if (searchSort === 'site') {
    rows.sort((a, b) => (a.site || '').localeCompare(b.site || '')
                        || (b.score || 0) - (a.score || 0));
  }
  // 'relevance' is the server's own order, which interleaves sites within each
  // band — re-sorting it here would undo that.
  return rows;
}

function hitCard(item, index, grouped = false) {
  return `
    <button class="search-hit" role="option" id="hit-${index}"
            data-url="${escapeHtml(item.url)}">
      ${item.cover_url
        ? `<img loading="lazy" alt=""
             src="/api/cover?url=${encodeURIComponent(item.cover_url)}">`
        : '<span class="no-cover"></span>'}
      <span class="hit-text">
        <span class="hit-title" dir="auto">${escapeHtml(item.title)}</span>
        ${item.alt_title
          // Why this hit matched: the site indexes names in several scripts,
          // so an Arabic query can land on a romanised title and look wrong.
          ? `<span class="hit-alt" dir="auto">${escapeHtml(item.alt_title)}</span>`
          : ''}
        ${item.author
          // The other reason a hit can look wrong: you searched a person, and
          // this is what they wrote. Berserk answering "Kentaro Miura" is only
          // obvious once the name is on the card.
          ? `<span class="hit-author">${escapeHtml(item.author)}</span>`
          : ''}
        <span class="hit-foot">
          ${item.content_type && searchKind === 'all' && !grouped
            // Only when the list is mixed *and* ungrouped. Under a "Manga"
            // heading, a MANGA badge on all sixteen cards says nothing — the
            // heading already said it.
            ? `<span class="hit-kind">${escapeHtml(
                 KIND_LABEL[item.content_type] || item.content_type)}</span>`
            : ''}
          <span class="hit-site">${escapeHtml(item.site)}</span>
          ${(item.sources || []).length > 1
            // The same work carried by several sites is one card, not three.
            // Naming the extras matters: they are alternatives to pick from
            // when one site is slow or has fewer chapters, so the count is a
            // real affordance rather than a footnote.
            ? `<span class="hit-also" title="${escapeHtml(
                 item.sources.map((s) => s.site).join(', '))}">+${
                 item.sources.length - 1} more</span>`
            : ''}
          ${item.match ? `<span class="hit-why">${escapeHtml(item.match)}</span>` : ''}
        </span>
      </span>
    </button>`;
}

function renderSearch(data) {
  lastSearch = data;
  cursor = -1;
  const box = $('#search-results');
  renderReadout(data.sites || []);

  if (!data.results.length) {
    box.innerHTML = `<div class="search-empty">${emptyMessage(data)}</div>`;
    box.hidden = false;
    $('#search-status').hidden = true;
    input.setAttribute('aria-expanded', 'true');
    return;
  }

  const answered = data.answered ?? (data.sites || []).filter((s) => s.count).length;
  $('#search-status').innerHTML =
    `<strong>${data.results.length}</strong> result${data.results.length === 1 ? '' : 's'}`
    + ` from <strong>${answered}</strong> of ${data.searched ?? answered} site`
    + `${(data.searched ?? answered) === 1 ? '' : 's'}`
    + (data.merged ? `, ${data.merged} duplicate${data.merged === 1 ? '' : 's'} merged` : '');
  $('#search-status').hidden = false;

  const rows = sortResults(data.results);
  let index = 0;
  let html = '';
  if (searchKind === 'all' && (data.kinds || []).length > 1 && searchSort === 'relevance') {
    // Grouped, not interleaved. Mixing novels into a manga list is exactly what
    // made an untyped search useless before; the groups are what make "All"
    // safe to offer at all.
    for (const group of data.kinds) {
      const inGroup = rows.filter((r) => r.content_type === group.type);
      if (!inGroup.length) continue;
      html += `<h3 class="result-group">${escapeHtml(group.label)}
                 <span>${inGroup.length}</span></h3>`;
      html += inGroup.map((item) => hitCard(item, index++, true)).join('');
    }
  } else {
    html = rows.map((item) => hitCard(item, index++)).join('');
  }
  box.innerHTML = html;
  box.hidden = false;
  $('#recents').hidden = true;
  input.setAttribute('aria-expanded', 'true');
}

/* An empty screen is a place to say what to do next, and the reason matters:
   "nothing found" is wrong when every site actually failed. */
function emptyMessage(data) {
  const sites = data.sites || [];
  const broke = sites.filter((s) => s.status === 'timeout' || s.status === 'error');
  if (!sites.length) {
    return `<p>No ${escapeHtml(KIND_LABEL[data.type] || data.type)} sites are set up`
      + ' for search yet.</p><p>Paste a series URL above instead.</p>';
  }
  if (broke.length === sites.length) {
    return `<p>No site could answer — ${broke.length === 1 ? 'it'
      : 'all of them'} timed out or failed.</p>`
      + '<p>Check the connection, or paste a series URL above.</p>';
  }
  return `<p>Nothing found for “${escapeHtml(data.query)}”.</p>`
    + '<p>Try a shorter query, another spelling, or the original title.</p>';
}

/* A cover that 404s or is refused by its host leaves an empty box, which reads
   as a broken card rather than as art we simply do not have. Swap it for the
   same placeholder a hit with no cover URL gets. Capture phase, because `error`
   from an <img> does not bubble. */
$('#search-results').addEventListener('error', (event) => {
  const img = event.target;
  if (img.tagName !== 'IMG' || !img.closest('.search-hit')) return;
  const placeholder = document.createElement('span');
  placeholder.className = 'no-cover';
  img.replaceWith(placeholder);
}, true);

$('#search-results').addEventListener('click', (event) => {
  const hit = event.target.closest('.search-hit');
  if (!hit || hit.classList.contains('skeleton')) return;
  // The same reset the kind chips and the clear button run. Without it a
  // debounce still pending, or a fetch still in flight, survives the click and
  // its late render reopens the result list on top of the preview that was
  // just loaded.
  clearTimeout(searchTimer);
  searchToken++;
  abandonSearch();
  // Held before clearResults() nulls it, so "Back to results" has something to
  // restore.
  heldSearch = lastSearch;
  // Fill the URL box and run the normal preview, so picking a result and
  // pasting a link end up on exactly the same path.
  $('#series-url').value = hit.dataset.url;
  clearResults();
  $('#back-to-results').hidden = !heldSearch;
  $('#preview-form').requestSubmit();
});

loadSources();
renderRecents();

/* --------------------------------------------------------------- preview */

$('#preview-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const url = $('#series-url').value.trim();
  if (!url) return;

  $('#preview-error').hidden = true;
  $('#preview').hidden = true;
  $('#preview-loading').hidden = false;
  $('#preview-btn').disabled = true;

  try {
    const data = await api('/api/preview', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
    renderPreview(data);
  } catch (error) {
    const box = $('#preview-error');
    box.textContent = `Could not read that series.\n\n${error.message}`;
    box.hidden = false;
  } finally {
    $('#preview-loading').hidden = true;
    $('#preview-btn').disabled = false;
  }
});

function renderPreview(data) {
  state.series = data.series;
  state.chapters = data.chapters;
  state.selected = new Set();

  $('#series-title').textContent = data.series.title;

  // Which site this is about to download from, said plainly and first. Picking
  // a search result fills the URL box and jumps straight here, so without it
  // the only record of the choice is a URL you scrolled past.
  const site = $('#series-site');
  site.textContent = hostOf(data.series.url);
  site.href = data.series.url;
  site.hidden = !site.textContent;

  $('#series-sub').textContent =
    `${data.chapters.length} chapters · ${data.adapter} adapter` +
    (data.series.author ? ` · ${data.series.author}` : '');
  $('#series-desc').textContent = data.series.description || '';

  const cover = $('#series-cover');
  if (data.series.cover_url) {
    // Through the app, not straight from the site: cover art often sits on a
    // filtered host or behind the clearance this app holds, and an <img> here
    // would go out from the browser without any of that.
    cover.src = `/api/cover?url=${encodeURIComponent(data.series.cover_url)}`;
    cover.hidden = false;
    cover.onerror = () => { cover.hidden = true; };
  } else {
    cover.hidden = true;
  }

  $('#range-from').max = $('#range-to').max = data.chapters.length;
  $('#range-from').value = 1;
  $('#range-to').value = data.chapters.length;

  $('#chapter-list').innerHTML = data.chapters.map((chapter, i) => `
    <li data-index="${i}">
      <label>
        <input type="checkbox" data-index="${i}">
        <span class="num">${escapeHtml(chapter.number ?? chapter.index)}</span>
        <span class="name">${escapeHtml(chapter.title)}</span>
      </label>
      ${chapter.status && chapter.status !== 'pending'
        ? `<span class="pill ${escapeHtml(chapter.status)}">${escapeHtml(chapter.status)}</span>`
        : ''}
    </li>
  `).join('');

  // A filter left over from the previous series would hide most of this one
  // and make the list look empty.
  $('#chapter-filter').value = '';
  applyChapterFilter();

  $('#preview').hidden = false;
}

/* --------------------------------------------------------- chapter filter */

/* Several hundred chapters is normal for a long-running series, and the list
   had no way in but scrolling. Matching is on the number and the title
   together, so "12" and "Vol. 3" both work.

   Filtering only changes what is *shown*. A chapter selected before the filter
   was typed stays selected even while hidden — silently dropping it would be
   worse — so the count below says how many of those there are. */

function chapterMatches(chapter, needle) {
  if (!needle) return true;
  return `${chapter.number ?? ''} ${chapter.title}`.toLowerCase().includes(needle);
}

function applyChapterFilter() {
  const needle = $('#chapter-filter').value.trim().toLowerCase();
  state.shown = new Set();

  $$('#chapter-list li').forEach((row) => {
    const index = Number(row.dataset.index);
    const match = chapterMatches(state.chapters[index], needle);
    row.hidden = !match;
    if (match) state.shown.add(index);
  });

  $('#chapter-list').classList.toggle('is-empty', state.chapters.length > 0
                                                  && state.shown.size === 0);
  updateDownloadButton();
}

$('#chapter-filter').addEventListener('input', applyChapterFilter);

/* Bound once, here, rather than inside renderPreview: the <ul> survives every
   render (only its innerHTML is replaced), so re-binding per preview stacked a
   fresh copy of this handler on the same element every time a series was
   fetched. */
$('#chapter-list').addEventListener('change', onChapterToggle);

function onChapterToggle(event) {
  const box = event.target;
  if (!box.matches('input[type=checkbox]')) return;
  const index = Number(box.dataset.index);
  if (box.checked) state.selected.add(index);
  else state.selected.delete(index);
  updateDownloadButton();
}

/* All of these replace the selection rather than adding to it, and all of them
   are scoped to what the filter leaves showing — so "filter to Vol. 3, Select
   all" means what it looks like. "None" is the exception: it clears
   everything, filtered out or not, because it is the escape hatch and leaving
   invisible chapters selected is exactly what it is reached for. */

$$('[data-select]').forEach((button) => {
  button.addEventListener('click', () => {
    const mode = button.dataset.select;
    const shown = (index) => state.shown.has(index);
    state.selected = new Set();

    if (mode === 'all') {
      state.chapters.forEach((_, i) => { if (shown(i)) state.selected.add(i); });
    } else if (mode === 'missing') {
      state.chapters.forEach((c, i) => {
        if (shown(i) && c.status !== 'done') state.selected.add(i);
      });
    } else if (mode === 'range') {
      const from = Math.max(1, Number($('#range-from').value) || 1);
      const to = Math.min(state.chapters.length, Number($('#range-to').value) || state.chapters.length);
      for (let i = from - 1; i <= to - 1; i += 1) if (shown(i)) state.selected.add(i);
    }

    $$('#chapter-list input[type=checkbox]').forEach((box) => {
      box.checked = state.selected.has(Number(box.dataset.index));
    });
    updateDownloadButton();
  });
});

function updateDownloadButton() {
  const count = state.selected.size;
  const button = $('#download-btn');
  button.disabled = count === 0;
  button.textContent = `Download ${count} chapter${count === 1 ? '' : 's'}`;

  // Selected but filtered out. The Download button acts on these too, so the
  // number has to be visible rather than merely correct.
  const hidden = [...state.selected].filter((i) => !state.shown.has(i)).length;
  const parts = [];
  if (state.chapters.length) parts.push(`${count} of ${state.chapters.length} selected`);
  if (hidden) parts.push(`${hidden} hidden by the filter`);
  if (state.shown.size !== state.chapters.length) parts.push(`${state.shown.size} shown`);
  $('#selection-count').textContent = parts.join(' · ');
}

$('#download-btn').addEventListener('click', async () => {
  const chapters = [...state.selected].sort((a, b) => a - b).map((i) => state.chapters[i]);
  $('#download-btn').disabled = true;
  try {
    const result = await api('/api/download', {
      method: 'POST',
      body: JSON.stringify({ series: state.series, chapters }),
    });
    $('.tab[data-view=queue]').click();
    await refreshJobs();
    toast(`Queued ${result.queued} chapter(s) of “${state.series.title}”.`);
  } catch (error) {
    const box = $('#preview-error');
    box.textContent = error.message;
    box.hidden = false;
  } finally {
    updateDownloadButton();
  }
});

/* ----------------------------------------------------------------- queue */

/* Rebuilt from the server's list every time, never merged into the old one.
   Merging is what let a removed or cleared job stay on screen: the server had
   forgotten it, /api/jobs no longer mentioned it, and nothing here ever took it
   out of the map — so "Clear finished" reported success while the list it was
   supposed to empty sat there unchanged until a manual reload.

   Details are fetched together rather than one after another, and a job that
   404s mid-refresh (removed between the two calls) degrades to its summary
   instead of rejecting the whole refresh and freezing the view. */

let jobsToken = 0;

async function refreshJobs() {
  const token = ++jobsToken;
  let summaries;
  try {
    ({ jobs: summaries } = await api('/api/jobs'));
  } catch (error) {
    if (token === jobsToken) toast(`Could not read the queue: ${error.message}`, 'error');
    return;
  }

  const details = await Promise.all(summaries.map(
    (job) => api(`/api/jobs/${job.id}`).catch(() => null),
  ));
  if (token !== jobsToken) return;   // a newer refresh already landed

  state.jobs = new Map(summaries.map((job, i) => [
    job.id, details[i] || { ...job, chapters: [] },
  ]));
  renderJobs();
}

/* How far along a job is, counting pages and not only whole chapters.
   `done/total` alone left a one-chapter job reading 0% from the first byte to
   the last, while the rows underneath it counted "12/40 pages" — the bar was
   flat for the entire download and looked stuck.

   Returns a fraction of the job, so partial chapters contribute their share. */
function jobProgress(job) {
  const total = job.total || 0;
  if (!total) return { done: 0, failed: 0, fraction: 0, percent: 0 };

  const chapters = job.chapters || [];
  let done = 0;
  let failed = 0;
  let filled = 0;

  for (const chapter of chapters) {
    if (chapter.status === 'done') { done += 1; filled += 1; continue; }
    if (chapter.status === 'failed') { failed += 1; continue; }
    if (chapter.status === 'running' && chapter.pages_total > 0) {
      filled += Math.min(chapter.pages_done / chapter.pages_total, 1);
    }
  }

  // Clamped because a progress event can arrive for a chapter the summary does
  // not know about yet, which would otherwise put the bar past its own end.
  const fraction = Math.min(filled / total, 1);
  // 100% is reserved for actually finished. Rounding up to it while a chapter
  // is still being written is the one number a progress bar must never show.
  const percent = done >= total ? 100 : Math.min(99, Math.floor(fraction * 100));
  return { done, failed, fraction, percent };
}

/* The tab spends most of a long download in the background, so the one place
   progress is guaranteed to be visible is the title. Restored exactly when
   nothing is active, rather than left showing a stale number. */
function updateDocumentTitle(jobs) {
  const running = jobs.filter(isActive);
  if (!running.length) {
    document.title = BASE_TITLE;
    return;
  }
  const totals = running.reduce((sum, job) => {
    const { fraction } = jobProgress(job);
    return { filled: sum.filled + fraction * job.total, total: sum.total + job.total };
  }, { filled: 0, total: 0 });

  const percent = totals.total
    ? Math.min(99, Math.floor((totals.filled / totals.total) * 100)) : 0;
  document.title = running.length > 1
    ? `${percent}% · ${running.length} jobs · ${BASE_TITLE}`
    : `${percent}% · ${BASE_TITLE}`;
}

/* Set while the Queue view is hidden and something changed, so switching to it
   draws the current state instead of whatever was last painted. */
let jobsDirty = false;

function renderJobs() {
  const container = $('#jobs');
  const jobs = [...state.jobs.values()].sort((a, b) => b.id - a.id);
  const active = jobs.filter(isActive).length;

  // Outside the Queue view, so these stay right whichever tab is open.
  const badge = $('#queue-badge');
  badge.textContent = active;
  badge.hidden = active === 0;
  updateDocumentTitle(jobs);

  // Rebuilding the list costs a full reflow of every chapter row, and progress
  // arrives per page. Skipped entirely while the view is hidden — which is
  // most of a download, since the tab is usually elsewhere.
  if (!$('#view-queue').classList.contains('is-active')) {
    jobsDirty = true;
    return;
  }
  jobsDirty = false;

  $('#queue-empty').hidden = jobs.length > 0;
  $('#stop-all').disabled = active === 0;
  $('#clear-finished').disabled = jobs.length === active;
  $('#clear-all').disabled = jobs.length === 0;

  // .chapter-rows is a 320px scroller and this replaces it wholesale on every
  // repaint, which sent it back to the top several times a second — scrolling
  // down to watch a chapter was impossible during the download it was showing.
  const scrolled = new Map($$('.chapter-rows', container)
    .map((node) => [node.dataset.job, node.scrollTop]));

  container.innerHTML = jobs.map(renderJob).join('');

  $$('.chapter-rows', container).forEach((node) => {
    const previous = scrolled.get(node.dataset.job);
    if (previous) node.scrollTop = previous;
  });

  $$('.job-actions button', container).forEach((button) => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await api(`/api/jobs/${button.dataset.job}/${button.dataset.action}`, { method: 'POST' });
      } catch (error) {
        // Said out loud, not console.warn'd: a refused action (cancelling a job
        // that just finished, say) looked exactly like the button doing nothing.
        toast(error.message, 'error');
      } finally {
        refreshJobs();
      }
    });
  });
}

/* Queue controls. Clearing the queue never touches files on disk — a job is
   bookkeeping, not the archives it produced. The confirm dialogs say so,
   because "delete" already means removing files over in the Library. */

function activeJobCount() {
  return [...state.jobs.values()].filter(isActive).length;
}

$('#stop-all').addEventListener('click', reporting(async () => {
  const active = activeJobCount();
  if (!active) return;
  if (!confirm(`Stop ${active} download(s) in progress?\n\n`
             + 'Chapters already finished are kept. Anything mid-download is '
             + 'discarded and can be queued again later.')) return;
  const result = await api('/api/jobs/stop', { method: 'POST' });
  await refreshJobs();
  toast(`Stopped ${result.stopped} job(s).`);
}));

$('#clear-finished').addEventListener('click', reporting(async () => {
  const result = await api('/api/jobs/clear', { method: 'POST' });
  await refreshJobs();
  toast(`Cleared ${result.removed} finished job(s). Your downloads are untouched.`);
}));

$('#clear-all').addEventListener('click', reporting(async () => {
  const active = activeJobCount();
  const warning = active
    ? `This stops ${active} download(s) in progress and clears the whole list.`
    : 'This clears the whole list.';
  if (!confirm(`${warning}\n\nDownloaded files are kept — this only empties `
             + 'the queue view.')) return;
  const result = await api('/api/jobs/clear?all=true', { method: 'POST' });
  await refreshJobs();
  toast(`Stopped ${result.stopped}, cleared ${result.removed} job(s).`);
}));

function renderJob(job) {
  const chapters = job.chapters || [];
  const { done, failed, percent } = jobProgress(job);
  // Keyed on the job, not on whether any chapter failed. One 403 among forty
  // turned the whole bar red while thirty-nine chapters were still downloading
  // fine — the summary line below already says "1 failed", in red, and the bar
  // is meant to show how much of the work is done.
  const barClass = ['failed', 'cancelled'].includes(job.status) ? 'failed'
    : (job.status === 'done' ? 'done' : '');

  const controls = [];
  if (job.status === 'running') controls.push(['pause', 'Pause']);
  if (job.status === 'paused') controls.push(['resume', 'Resume']);
  if (isActive(job)) controls.push(['cancel', 'Cancel']);
  if (failed && !['running', 'queued'].includes(job.status)) controls.push(['retry', `Retry ${failed}`]);
  // Only once the job is finished: removing an active one would abandon a
  // download mid-chapter, so Stop comes first and is a deliberate choice.
  if (!isActive(job)) controls.push(['remove', 'Remove']);

  return `
    <div class="job">
      <div class="job-head">
        <h3>${escapeHtml(job.series.title)}</h3>
        <div class="job-actions">
          ${controls.map(([action, label]) =>
            `<button data-job="${job.id}" data-action="${action}">${label}</button>`).join('')}
        </div>
      </div>
      <p class="job-summary">
        <span class="pill ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
        ${done}/${job.total} done${failed ? ` · <span class="bad">${failed} failed</span>` : ''}
        ${job.error ? ` · ${escapeHtml(job.error)}` : ''}
      </p>
      <div class="bar-row">
        <div class="bar ${barClass}"
             role="progressbar" aria-valuenow="${percent}"
             aria-valuemin="0" aria-valuemax="100"><span style="width:${percent}%"></span></div>
        <span class="percent">${percent}%</span>
      </div>
      <div class="chapter-rows" data-job="${job.id}">
        ${chapters.map(renderChapterRow).join('')}
      </div>
    </div>`;
}

function renderChapterRow(chapter) {
  const pages = chapter.pages_total
    ? `${chapter.pages_done}/${chapter.pages_total} pages`
    : (chapter.status === 'running' ? 'reading…' : '');
  return `
    <div class="chapter-row">
      <span class="title">${escapeHtml(chapter.title)}</span>
      <span class="count">${escapeHtml(pages)}</span>
      <span class="pill ${escapeHtml(chapter.status)}">${escapeHtml(chapter.status)}</span>
      ${chapter.error ? `<span class="err">${escapeHtml(chapter.error)}</span>` : ''}
    </div>`;
}

/* ------------------------------------------------------------- websocket */

let socket = null;
let reconnectDelay = 1000;
let renderScheduled = false;

function scheduleRender() {
  // Progress events arrive per page; batch them to one repaint per frame.
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    renderJobs();
  });
}

function setConnection(status, label) {
  const node = $('#conn-status');
  node.className = `status ${status}`;
  $('.label', node).textContent = label;
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${location.host}/ws`);

  socket.onopen = () => {
    reconnectDelay = 1000;
    setConnection('is-live', 'live');
    refreshJobs();
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    if (message.type === 'chapter_progress') {
      const job = state.jobs.get(message.job_id);
      if (!job) { refreshJobs(); return; }
      const index = (job.chapters || []).findIndex(
        (c) => c.chapter_url === message.chapter.chapter_url,
      );
      if (index >= 0) job.chapters[index] = message.chapter;
      else job.chapters.push(message.chapter);
      scheduleRender();
    } else if (message.type === 'job_created' || message.type === 'job_updated'
               || message.type === 'jobs_changed') {
      refreshJobs();
    }
  };

  socket.onclose = (event) => {
    // Only the live socket may schedule a reconnect. A late close from a socket
    // this one already replaced would otherwise start a second connect loop,
    // and the two would then double every reconnect from there on.
    if (event.target !== socket) return;
    setConnection('is-down', 'reconnecting…');
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 15000);
  };

  // event.target, not the module-level `socket`: by the time an error arrives
  // from an older connection, `socket` may already point at its replacement —
  // and closing that is how a working connection got torn down.
  socket.onerror = (event) => event.target.close();
}

/* --------------------------------------------------------------- library */

async function loadLibrary() {
  const { series } = await api('/api/library');
  state.library = series;
  renderLibrary();
}

/* Sorting and filtering run on the answer already in hand. Going back to the
   server for either would re-walk the output directory to re-measure every
   series on disk, which is the expensive half of /api/library. */

const LIBRARY_SORTS = {
  recent: (a, b) => (b.updated_at || 0) - (a.updated_at || 0),
  title: (a, b) => String(a.title).localeCompare(String(b.title)),
  size: (a, b) => (b.size_bytes || 0) - (a.size_bytes || 0),
  downloaded: (a, b) => (b.downloaded_count || 0) - (a.downloaded_count || 0),
};

function renderLibrary() {
  const needle = $('#library-filter').value.trim().toLowerCase();
  const sort = LIBRARY_SORTS[$('#library-sort').value] || LIBRARY_SORTS.recent;

  const series = state.library
    // The hostname is matched too: with the same series downloaded from two
    // sites, the title alone cannot tell the two cards apart.
    .filter((item) => !needle
      || `${item.title} ${hostOf(item.url)}`.toLowerCase().includes(needle))
    .sort(sort);

  // Three distinct states, and they are not the same message: an empty library
  // needs "download something", an over-narrow filter needs "widen it".
  $('#library-empty').hidden = state.library.length > 0;
  $('#library-no-match').hidden = !(state.library.length && !series.length);
  $('#library-count').textContent = state.library.length
    ? (series.length === state.library.length
        ? `${series.length} series`
        : `${series.length} of ${state.library.length} series`)
    : '';

  $('#library').innerHTML = series.length ? `
    <div class="library-grid">
      ${series.map((item) => `
        <div class="library-card" data-url="${escapeHtml(item.url)}"
             data-title="${escapeHtml(item.title)}">
          <h3>${escapeHtml(item.title)}</h3>
          <!-- Same reason as the badge on the preview: with the same series
               downloaded from two sites, the title alone names neither. -->
          <a class="series-site card-site" href="${escapeHtml(item.url)}"
             target="_blank" rel="noopener noreferrer"
             >${escapeHtml(hostOf(item.url))}</a>
          <p class="stats">
            ${item.downloaded_count}/${item.chapter_count} chapters<br>
            ${formatBytes(item.size_bytes)} on disk
          </p>
          ${item.size_bytes ? `
            <p class="card-actions">
              <a class="download-zip"
                 href="/api/library/archive?title=${encodeURIComponent(item.title)}"
                 download>Download .zip (${formatBytes(item.size_bytes)})</a>
            </p>
            <p class="card-actions">
              <button class="link-btn pick-chapters">Choose chapters…</button>
              <button class="link-btn danger delete-all"
                      data-size="${item.size_bytes}"
                      data-count="${item.downloaded_count}">
                Delete all files (${formatBytes(item.size_bytes)})
              </button>
            </p>
            <div class="chapter-picker" hidden></div>` : ''}
          <p class="card-actions">
            <button class="link-btn forget">Remove from library</button>
          </p>
        </div>`).join('')}
    </div>` : '';
}

/* Deleting is irreversible and there is no trash, so every path asks first
   with the real count and size, and the card is re-read from the server
   afterwards rather than having its numbers adjusted locally. */

async function deleteFiles(card, chapters, description) {
  if (!confirm(`Delete ${description} from "${card.dataset.title}"?\n\n`
             + 'The files are removed from disk permanently. The series stays '
             + 'in your library and can be downloaded again.')) return;

  const result = await api('/api/library/delete', {
    method: 'POST',
    body: JSON.stringify({ series_url: card.dataset.url, chapters }),
  });

  let note = `Deleted ${result.removed} file(s), freed ${formatBytes(result.freed_bytes)}.`;
  if (result.skipped.length) {
    note += ` Skipped ${result.skipped.length} still downloading.`;
  }
  await loadLibrary();
  toast(note, result.skipped.length ? 'warn' : 'ok');
}

async function showChapterPicker(card) {
  const panel = card.querySelector('.chapter-picker');
  if (!panel.hidden) { panel.hidden = true; return; }

  const { chapters } = await api(
    `/api/library/chapters?series_url=${encodeURIComponent(card.dataset.url)}`);
  const onDisk = chapters.filter((c) => c.on_disk);

  panel.innerHTML = onDisk.length ? `
    <label class="pick-all"><input type="checkbox" class="select-all"> Select all</label>
    <div class="pick-rows">
      ${onDisk.map((c) => `
        <label class="pick-row">
          <input type="checkbox" value="${escapeHtml(c.url)}" data-size="${c.size_bytes}">
          <span>${escapeHtml(c.title || c.number || c.url)}</span>
          <span class="count">${formatBytes(c.size_bytes)}</span>
        </label>`).join('')}
    </div>
    <button class="link-btn danger delete-selected" disabled>Delete selected</button>`
    : '<p class="stats">Nothing downloaded for this series.</p>';
  panel.hidden = false;

  // Everything below is looked up through the panel at the moment it is used,
  // never captured. Reopening the picker replaces the panel's contents, so a
  // handler holding on to the old button would be adjusting a detached node.
  const boxes = () => Array.from(panel.querySelectorAll('.pick-row input'));
  const picks = () => boxes().filter((b) => b.checked);
  const pickedBytes = (picked) =>
    picked.reduce((sum, b) => sum + Number(b.dataset.size), 0);

  const sync = () => {
    const button = panel.querySelector('.delete-selected');
    if (!button) return;
    const picked = picks();
    button.disabled = picked.length === 0;
    button.textContent = picked.length
      ? `Delete selected (${picked.length} · ${formatBytes(pickedBytes(picked))})`
      : 'Delete selected';
  };

  // Wired once per panel, and delegated. Both listeners used to be re-added on
  // every open — the change handler stacking another copy each time, the click
  // handler landing on a button that the next open would throw away.
  if (!panel.dataset.wired) {
    panel.dataset.wired = '1';
    panel.addEventListener('change', (event) => {
      if (event.target.classList.contains('select-all')) {
        boxes().forEach((b) => { b.checked = event.target.checked; });
      }
      sync();
    });
    panel.addEventListener('click', reporting((event) => {
      if (!event.target.classList.contains('delete-selected')) return undefined;
      const picked = picks();
      return deleteFiles(
        card, picked.map((b) => b.value),
        `${picked.length} chapter(s), ${formatBytes(pickedBytes(picked))}`,
      );
    }));
  }
  sync();
}

$('#library').addEventListener('click', reporting((event) => {
  const card = event.target.closest('.library-card');
  if (!card) return undefined;
  if (event.target.classList.contains('pick-chapters')) {
    return showChapterPicker(card);
  }
  if (event.target.classList.contains('delete-all')) {
    return deleteFiles(card, null,
      `all ${event.target.dataset.count} downloaded chapter(s), `
      + formatBytes(Number(event.target.dataset.size)));
  }
  if (event.target.classList.contains('forget')) {
    return forgetSeries(card);
  }
  return undefined;
}));

/* Separate from deleting files on purpose: this drops the series and its
   chapter list from the index and leaves every archive where it is. Without
   it there is no way to clear an entry that has no files - such as the bogus
   ones a chapter URL used to create. */
async function forgetSeries(card) {
  if (!confirm(`Remove "${card.dataset.title}" from your library?\n\n`
             + 'Any downloaded files are kept on disk — this only forgets the '
             + 'series and its chapter list. Use "Delete all files" first if '
             + 'you want the space back.')) return;

  await api(`/api/library?url=${encodeURIComponent(card.dataset.url)}`,
            { method: 'DELETE' });
  await loadLibrary();
  toast(`Removed “${card.dataset.title}” from the library. Files are untouched.`);
}

$('#refresh-library').addEventListener('click', reporting(loadLibrary));
$('#library-filter').addEventListener('input', renderLibrary);
$('#library-sort').addEventListener('change', () => {
  localStorage.setItem('librarySort', $('#library-sort').value);
  renderLibrary();
});

/* -------------------------------------------------------------- settings */

const FIELD_LABELS = {
  output_dir: 'Output directory',
  chapter_concurrency: 'Chapters in parallel',
  image_concurrency: 'Images in parallel',
  requests_per_second: 'Requests per second',
  max_retries: 'Max retries per image',
  prefer_original_quality: 'Prefer original quality',
  language: 'Language code',
  proxy: 'Proxy (blank = direct)',
  desync_enabled: 'Bypass hostname filtering',
  browser_cdp: 'Attach to my browser (blank = own browser)',
};

async function loadSettings() {
  const { values } = await api('/api/settings');
  $('#settings-fields').innerHTML = Object.entries(values).map(([key, value]) => {
    const label = FIELD_LABELS[key] || key;
    if (typeof value === 'boolean') {
      return `<label>${escapeHtml(label)}
        <select data-key="${key}">
          <option value="true"${value ? ' selected' : ''}>Yes</option>
          <option value="false"${!value ? ' selected' : ''}>No</option>
        </select></label>`;
    }
    const type = typeof value === 'number' ? 'number' : 'text';
    const step = Number.isInteger(value) ? '1' : '0.5';
    return `<label>${escapeHtml(label)}
      <input type="${type}" step="${step}" data-key="${key}" value="${escapeHtml(value)}">
    </label>`;
  }).join('');
}

$('#save-settings').addEventListener('click', reporting(async () => {
  const values = {};
  $$('#settings-fields [data-key]').forEach((input) => {
    let value = input.value;
    if (value === 'true' || value === 'false') value = value === 'true';
    else if (input.type === 'number') value = Number(value);
    values[input.dataset.key] = value;
  });

  const note = $('#settings-note');
  try {
    await api('/api/settings', { method: 'PUT', body: JSON.stringify({ values }) });
    note.textContent = 'Saved';
    note.style.color = '';
  } catch (error) {
    note.textContent = error.message;
    note.style.color = 'var(--err)';
  }
  note.hidden = false;
  setTimeout(() => { note.hidden = true; }, 3000);
}));

async function loadSessionStatus() {
  try {
    const health = await api('/api/health');
    const session = health.session;
    const mode = session.headless_mode === 'auto'
      ? `${session.headless ? 'headless' : 'headful'} (auto${session.escalated ? ', escalated' : ''})`
      : (session.headless ? 'headless' : 'headful');
    const rows = [
      ...(session.awaiting_user
        ? [['ACTION NEEDED',
            `Complete the Cloudflare check for ${session.awaiting_user} in the browser window that opened.`]]
        : []),
      ['Browser', session.browser_running ? 'running' : 'not started'],
      ['Engine', session.attached
        ? `attached to your browser at ${session.cdp_endpoint}`
        : (session.driver
            ? `${session.driver}${session.stealth ? ' (patched)' : ''} · ${session.channel || 'chromium'} · ${mode}`
            : 'not started')],
      ...(session.display ? [['Display', session.display]] : []),
      ['User-Agent', session.user_agent || '(not read yet)'],
      ['Output writable', health.output_writable ? 'yes' : 'NO - check the mount'],
      ...session.hosts.map((h) => [
        h.host,
        `${h.cookie_count} cookies · clearance: ${h.has_clearance ? 'yes' : 'no'}` +
        `${h.manual ? ' · manual' : ''}`,
      ]),
    ];
    $('#session-status').innerHTML =
      `<table>${rows.map(([k, v]) =>
        `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`).join('')}</table>`;
  } catch (error) {
    $('#session-status').textContent = error.message;
  }
}

$('#save-session').addEventListener('click', reporting(async () => {
  const note = $('#session-note');
  try {
    const result = await api('/api/session/manual', {
      method: 'POST',
      body: JSON.stringify({
        url: $('#manual-url').value.trim(),
        cookies: $('#manual-cookies').value.trim(),
        user_agent: $('#manual-ua').value.trim(),
      }),
    });
    note.textContent = `Installed ${result.cookie_count} cookies for ${result.host}`;
    note.style.color = '';
    await loadSessionStatus();
  } catch (error) {
    note.textContent = error.message;
    note.style.color = 'var(--err)';
  }
  note.hidden = false;
  setTimeout(() => { note.hidden = true; }, 5000);
}));

/* -------------------------------------------------------------- keyboard */

/* Two shortcuts, both for things this UI makes you reach for constantly: the
   box you are about to type in, and getting out of a filter you just typed. */

document.addEventListener('keydown', (event) => {
  const inField = event.target.closest('input, textarea, select');

  // Escape clears the filter or search box it is pressed in. Browsers do this
  // for type=search already — but only via the little ⨯, and not in a way that
  // fires `input`, so our own handlers never heard about it.
  // Escape leaves an open preview and puts the results back. Checked before
  // the search-input rule below so it works whether or not focus is in a box.
  if (event.key === 'Escape' && !$('#preview').hidden
      && $('#sources-popover').hidden
      && !event.target.matches('#chapter-filter')) {
    closePreview({ restore: true });
    event.preventDefault();
    return;
  }

  if (event.key === 'Escape' && event.target.matches('input[type=search]')) {
    if (!event.target.value) return;
    event.target.value = '';
    event.target.dispatchEvent(new Event('input', { bubbles: true }));
    event.preventDefault();
    return;
  }

  if (event.key !== '/' || inField || event.ctrlKey || event.metaKey || event.altKey) return;

  // One rule: "/" goes to the search box for the view you are on. It used to
  // retarget the *chapter filter* whenever a preview was open, which is
  // exactly when someone wants to search again — so the keyboard route back to
  // search was dead from the first result click until a page reload. The
  // chapter filter is on screen and clickable; it does not need the shortcut.
  const view = $('.view.is-active').id;
  let target = null;
  if (view === 'view-library') target = $('#library-filter');
  else if (view === 'view-add') {
    target = searchKind ? $('#search-input') : $('#series-url');
  } else {
    // Queue and Settings have nothing to type in, so '/' means "go search".
    showView('add');
    target = searchKind ? $('#search-input') : $('#series-url');
  }

  event.preventDefault();
  target.focus();
  target.select();
});

/* ------------------------------------------------------------------ boot */

const savedSort = localStorage.getItem('librarySort');
if (savedSort && savedSort in LIBRARY_SORTS) $('#library-sort').value = savedSort;

// Reloading during a download used to drop you back on Add, away from the
// queue you were watching.
showView(localStorage.getItem('view') || 'add', { remember: false });

connect();

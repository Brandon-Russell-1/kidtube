/* KidTube kid site. Plain JS, no build step.
 *
 * Safety properties this file maintains:
 *  - Only video IDs present in data/approved.json can ever be loaded.
 *  - There is no search box and no text input anywhere.
 *  - Taps never reach YouTube's own links: the player is covered by transparent
 *    shields, and the iframe is sandboxed without popup or navigation rights.
 *  - The player closes just before a video ends, so the end screen never shows.
 */
(function () {
  'use strict';

  const DEFAULT_PIN_SHA256 = '03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4'; // "1234"
  const LONG_PRESS_MS = 2000;
  const PLAY_WAIT_MS = 3500;
  const END_GUARD_SECONDS = 0.8;
  const SKIP_SECONDS = 10;
  // A jump never lands closer than this to the end, so it can't skip straight
  // into YouTube's end screen; the player closes itself just before the end.
  const SEEK_END_MARGIN = 3;
  const WATCH_AGAIN_MAX = 12;
  const BUTTON_RESULTS_MAX = 200;
  const BUTTONS_MAX = 24;
  const AUDIT_MAX = 40;
  const VIDEO_ID = /^[\w-]{11}$/;

  // The home feed.
  const FEED_PAGE = 24;                    // videos added each time he nears the bottom
  const SHELF_EVERY = 12;                  // a sideways shelf after every this many videos
  const SHELF_SIZE = 12;                   // videos per shelf
  const SHELF_MIN = 4;                     // a shelf with fewer is left out
  const NEW_FOR_MS = 2 * 86400000;         // "NEW" on videos approved in the last two days
  const FRESH_VISIT_MS = 5 * 60000;        // away this long and the feed reshuffles
  const FAVORITE_AFTER_SECONDS = 60;       // watching this long counts toward his favorites
  const FAVORITE_HALF_LIFE_DAYS = 14;      // old favorites fade by half every two weeks
  // Channel icons may come only from YouTube's own image hosts.
  const ICON_URL = /^https:\/\/yt3\.(?:ggpht|googleusercontent)\.com\/[\w\-./=~%]+$/;

  const $ = (id) => document.getElementById(id);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ── Storage (all per-device; nothing leaves the iPad) ─────────────────────

  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    },
  };

  function todayKey() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  const watchedSeconds = () => store.get(`kt.watch.${todayKey()}`, 0);
  const bonusMinutes = () => store.get(`kt.bonus.${todayKey()}`, 0);

  function pruneOldDays() {
    try {
      const keep = todayKey();
      Object.keys(localStorage)
        .filter((k) => /^kt\.(watch|bonus)\./.test(k) && !k.endsWith(keep))
        .forEach((k) => localStorage.removeItem(k));
    } catch (e) { /* ignore */ }
  }

  // ── Data ──────────────────────────────────────────────────────────────────

  let approved = new Map();   // id -> approved.json entry; the allowlist
  let lineup = { date: '', videos: [], settings: {} };
  let lineupIds = [];
  let channels = new Map();   // channel_id -> { title, icon } from data/channels.json
  const broken = new Set();   // videos that failed to play this session

  async function getJSON(path) {
    const response = await fetch(`${path}?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  }

  async function loadData() {
    try {
      const data = await getJSON('data/approved.json');
      approved = new Map(
        (data.videos || []).filter((v) => VIDEO_ID.test(v.id)).map((v) => [v.id, v])
      );
    } catch (e) {
      if (!approved.size) approved = new Map();
    }
    try {
      const data = await getJSON('data/lineup.json');
      lineup = { date: data.date || '', generated_at: data.generated_at || '',
                 videos: data.videos || [], settings: data.settings || {} };
    } catch (e) { /* keep whatever we had */ }
    lineupIds = lineup.videos.map((v) => v.id).filter((id) => approved.has(id));
    try {
      const data = await getJSON('data/channels.json');
      channels = new Map(Object.entries(data.channels || {}).map(([id, c]) => [id, {
        title: String((c && c.title) || ''),
        icon: c && typeof c.icon === 'string' && ICON_URL.test(c.icon) ? c.icon : '',
      }]));
    } catch (e) { /* icons are optional; tiles fall back to a letter */ }
    searchCache.clear();
  }

  function limitSeconds() {
    const minutes = Number(lineup.settings.daily_watch_limit_minutes) || 0;
    return minutes > 0 ? (minutes + bonusMinutes()) * 60 : 0;
  }

  function limitReached() {
    const limit = limitSeconds();
    return limit > 0 && watchedSeconds() >= limit;
  }

  // ── Home screen ───────────────────────────────────────────────────────────

  function formatLength(seconds) {
    const minutes = Math.max(1, Math.round(seconds / 60));
    return `${minutes} min`;
  }

  const watchedMap = () => store.get('kt.watched', {});
  let watchedNow = {};   // read once per render rather than once per tile

  function isNew(video) {
    const approvedAt = Date.parse(video.screened_at || '');
    return approvedAt > 0 && Date.now() - approvedAt < NEW_FOR_MS;
  }

  const AVATAR_COLORS = ['#ff6b5e', '#7cc6fe', '#3ddc97', '#ffc93c', '#b28dff', '#ff9f43'];

  // The channel's round icon, or a colored circle with its first letter.
  function avatar(video) {
    const box = el('div', 'avatar');
    const info = channels.get(video.channel_id) || {};
    const showLetter = () => {
      const name = info.title || video.channel_title || '';
      let hash = 0;
      for (const ch of String(video.channel_id || name)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
      box.style.background = AVATAR_COLORS[hash % AVATAR_COLORS.length];
      box.replaceChildren(el('span', '', (name.match(/[A-Za-z0-9]/) || ['?'])[0].toUpperCase()));
    };
    if (!info.icon) { showLetter(); return box; }
    const img = el('img');
    img.alt = '';
    img.loading = 'lazy';
    img.draggable = false;
    img.referrerPolicy = 'no-referrer';
    img.onerror = showLetter;
    img.src = info.icon;
    box.append(img);
    return box;
  }

  function tile(video) {
    const button = el('button', 'tile');
    const thumb = el('div', 'thumb');
    const img = el('img');
    img.alt = '';
    img.loading = 'lazy';
    img.draggable = false;
    img.src = video.thumbnail || `https://i.ytimg.com/vi/${video.id}/hqdefault.jpg`;
    img.onerror = () => {
      img.onerror = null;
      img.src = `https://i.ytimg.com/vi/${video.id}/hqdefault.jpg`;
    };
    thumb.append(img, el('div', 'play', '▶'));
    if (video.duration_seconds) thumb.append(el('div', 'badge', formatLength(video.duration_seconds)));
    if (watchedNow[video.id]) thumb.append(el('div', 'watched', '✓'));
    else if (isNew(video)) thumb.append(el('div', 'new-badge', 'NEW'));
    const text = el('div', 'meta-text');
    text.append(el('div', 'title', video.title), el('div', 'channel', video.channel_title));
    const meta = el('div', 'meta');
    meta.append(avatar(video), text);
    button.append(thumb, meta);
    button.addEventListener('click', () => openPlayer(video.id));
    return button;
  }

  function watchAgainIds() {
    const today = new Set(lineupIds);
    const watched = store.get('kt.watched', {});
    const mine = Object.keys(watched).sort((a, b) => watched[b] - watched[a]);
    const shown = [...approved.values()]
      .filter((v) => v.last_shown)
      .sort((a, b) => (a.last_shown < b.last_shown ? 1 : -1))
      .map((v) => v.id);
    const seen = new Set();
    return [...mine, ...shown].filter((id) => {
      if (seen.has(id) || today.has(id) || !approved.has(id) || broken.has(id)) return false;
      // Fun videos only come in the daily allowance, never as extras here.
      if (approved.get(id).kind === 'fun') return false;
      seen.add(id);
      return true;
    }).slice(0, WATCH_AGAIN_MAX);
  }

  // ── Search buttons ────────────────────────────────────────────────────────
  // Same matching rules as screener/matching.py: a word matches the start of a
  // word in the title, channel, or topics, ignoring case, hyphens, apostrophes,
  // and a trailing "s". Only videos already in approved.json are ever searched.

  let activeWord = null;   // the tapped button's word, or null for today's lineup

  function norm(text) {
    return ` ${String(text || '').toLowerCase().replace(/['’-]/g, '')
      .replace(/[^a-z0-9]+/g, ' ').trim()} `;
  }

  function stem(word) {
    const w = norm(word).trim();
    return w.length > 3 && w.endsWith('s') ? w.slice(0, -1) : w;
  }

  const searchCache = new Map();   // id -> normalized text; cleared when data reloads

  function searchText(video) {
    let text = searchCache.get(video.id);
    if (text === undefined) {
      text = norm([video.title, video.channel_title, ...(video.topics || []),
        video.kind === 'fun' ? 'fun' : ''].join(' '));
      searchCache.set(video.id, text);
    }
    return text;
  }

  function buttonStems(button) {
    return (Array.isArray(button.match) ? button.match : [button.word]).map(stem).filter(Boolean);
  }

  function matchesStems(video, stems) {
    const text = searchText(video);
    return stems.some((s) => text.includes(` ${s}`));
  }

  function searchButtons() {
    const raw = Array.isArray(lineup.settings.search_buttons) ? lineup.settings.search_buttons : [];
    return raw.filter((b) => b && typeof b.word === 'string' && b.word.trim()).slice(0, BUTTONS_MAX);
  }

  function buttonResults(button, limit = BUTTON_RESULTS_MAX) {
    const stems = buttonStems(button);
    const watched = watchedMap();
    return [...approved.values()]
      .filter((v) => !broken.has(v.id))
      .filter((v) => matchesStems(v, stems))
      .sort((a, b) => {
        const seen = (watched[a.id] ? 1 : 0) - (watched[b.id] ? 1 : 0);   // unwatched first
        if (seen) return seen;
        return (b.screened_at || '').localeCompare(a.screened_at || '');  // then newest
      })
      .slice(0, limit);
  }

  function chip(label, emoji, active, onTap) {
    const button = el('button', active ? 'chip active' : 'chip');
    if (emoji) button.append(el('span', 'chip-emoji', emoji));
    button.append(el('span', '', label));
    button.addEventListener('click', () => {
      onTap();
      renderHome();
      window.scrollTo(0, 0);
    });
    return button;
  }

  function drawChips(buttons, results) {
    // A button with nothing approved yet stays hidden, so he never taps into an empty page.
    const usable = buttons.filter((b, i) => results[i].length);
    const nav = $('chips');
    nav.hidden = usable.length === 0;
    if (!usable.length) { nav.replaceChildren(); return; }
    nav.replaceChildren(
      chip('Today', '☀️', activeWord === null, () => { activeWord = null; }),
      ...usable.map((b) => chip(b.word, b.emoji, activeWord === b.word, () => { activeWord = b.word; }))
    );
  }

  // ── Favorites (per device; nothing leaves the iPad) ──────────────────────
  // What he actually watches, so the feed can lean toward it. A video counts
  // once he has watched a minute of it, toward its channel, its topics, and
  // the buttons it matches. Interest fades with a two-week half-life.

  function faded(entry, now) {
    if (!entry || !(entry.p > 0)) return 0;
    return entry.p * Math.pow(0.5, (now - entry.t) / 86400000 / FAVORITE_HALF_LIFE_DAYS);
  }

  function loadFavorites() {
    const saved = store.get('kt.fav', null) || {};
    return { c: saved.c || {}, t: saved.t || {}, b: saved.b || {} };
  }

  function creditFavorite(video) {
    if (!video) return;
    const fav = loadFavorites();
    const now = Date.now();
    const bump = (map, key, amount) => { if (key) map[key] = { p: faded(map[key], now) + amount, t: now }; };
    bump(fav.c, video.channel_id, 1);
    const topics = video.topics || [];
    topics.forEach((topic) => bump(fav.t, topic, 1 / topics.length));
    searchButtons().forEach((button) => {
      if (matchesStems(video, buttonStems(button))) bump(fav.b, button.word, 1);
    });
    [fav.c, fav.t, fav.b].forEach((map) => Object.keys(map).forEach((key) => {
      if (faded(map[key], now) < 0.05) delete map[key];
    }));
    store.set('kt.fav', fav);
  }

  // 0 for a video from nothing he has watched, up to 3 for his clear favorites.
  function liking(video, fav, now) {
    const channel = faded(fav.c[video.channel_id], now);
    const topic = Math.max(0, ...(video.topics || []).map((t) => faded(fav.t[t], now)));
    return Math.min(3, 0.7 * Math.log2(1 + channel) + 0.3 * Math.log2(1 + topic));
  }

  // ── Feed ──────────────────────────────────────────────────────────────────
  // Today's lineup, reshuffled for each visit. The job's mix of learning and fun
  // videos stays as the parent set it; within each, his favorites and new
  // videos tend to come first, and videos he has watched wait at the end.
  // Shelves of one button's videos from the rest of the pool break it up.
  // The order holds still for the whole visit, so coming back from a video
  // lands him where he was.

  let visitSeed = 0;
  let feed = null;                        // { key, entries } for this visit
  let entries = [];                       // the current view: { video } or { shelf }
  let shown = { view: '', count: 0 };     // how many entries are on screen
  let moreObserver = null;
  let homeScroll = 0;

  function startVisit() {
    visitSeed = (Math.random() * 4294967296) >>> 0;
    feed = null;
    activeWord = null;
    shown = { view: '', count: 0 };
  }

  function seededRandom(seed) {   // mulberry32: the same seed gives the same order
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Random order that favors heavier items without fixing them in place:
  // each item's key is random^(1/weight), and higher keys go first.
  function weightedShuffle(items, weightOf, rng) {
    return items.map((item) => ({ item, key: Math.pow(rng(), 1 / weightOf(item)) }))
      .sort((a, b) => b.key - a.key)
      .map((x) => x.item);
  }

  // Same as _spread in screener/lineup.py: extras at even intervals through main.
  function spread(main, extras) {
    const result = main.slice();
    const step = (main.length + extras.length) / (extras.length + 1);
    extras.forEach((video, i) => {
      result.splice(Math.min(result.length, Math.round(step * (i + 1))), 0, video);
    });
    return result;
  }

  function buildShelves(feedIds, fav, now, rng, watched) {
    const weight = (v) => (1 + liking(v, fav, now)) * (isNew(v) ? 1.5 : 1);
    const pool = [...approved.values()].filter((v) => !feedIds.has(v.id));
    const learning = [];
    const fun = [];
    searchButtons().forEach((button) => {
      const stems = buttonStems(button);
      const all = [...approved.values()].filter((v) => matchesStems(v, stems));
      if (!all.length) return;
      const shelf = { title: button.word, emoji: button.emoji || '', word: button.word,
                      videos: pool.filter((v) => matchesStems(v, stems)) };
      (all.filter((v) => v.kind === 'fun').length * 2 > all.length ? fun : learning).push(shelf);
    });
    // Learning and cartoon shelves take turns, his favorite buttons tending first.
    const buttonLiking = (shelf) => 1 + Math.min(3, 0.8 * Math.log2(1 + faded(fav.b[shelf.word], now)));
    const learningOrder = weightedShuffle(learning, buttonLiking, rng);
    const funOrder = weightedShuffle(fun, buttonLiking, rng);
    const byButton = [];
    while (learningOrder.length || funOrder.length) {
      if (learningOrder.length) byButton.push(learningOrder.shift());
      if (funOrder.length) byButton.push(funOrder.shift());
    }
    const ordered = [
      { title: 'New', emoji: '🆕', videos: pool.filter(isNew) },
      ...byButton.slice(0, 2),
      { title: 'Watch again', emoji: '⭐', keepOrder: true,
        videos: watchAgainIds().map((id) => approved.get(id)) },
      ...byButton.slice(2),
    ];

    const used = new Set();   // each video appears on one shelf at most
    const shelves = [];
    ordered.forEach((shelf) => {
      let videos = shelf.videos.filter((v) => !used.has(v.id) && !broken.has(v.id));
      if (!shelf.keepOrder) {
        videos = [...weightedShuffle(videos.filter((v) => !watched[v.id]), weight, rng),
                  ...weightedShuffle(videos.filter((v) => watched[v.id]), weight, rng)];
      }
      videos = videos.slice(0, SHELF_SIZE);
      if (videos.length < SHELF_MIN) return;
      videos.forEach((v) => used.add(v.id));
      shelves.push({ ...shelf, videos });
    });
    return shelves;
  }

  function buildFeed() {
    const rng = seededRandom(visitSeed);
    const fav = loadFavorites();
    const now = Date.now();
    const watched = watchedMap();
    const weight = (v) => (1 + liking(v, fav, now)) * (isNew(v) ? 1.5 : 1);
    const today = lineupIds.map((id) => approved.get(id));
    const order = (seen) => {
      const group = today.filter((v) => Boolean(watched[v.id]) === seen);
      return spread(weightedShuffle(group.filter((v) => v.kind !== 'fun'), weight, rng),
                    weightedShuffle(group.filter((v) => v.kind === 'fun'), weight, rng));
    };
    const videos = [...order(false), ...order(true)];
    const shelves = buildShelves(new Set(lineupIds), fav, now, rng, watched);
    const list = [];
    videos.forEach((video, i) => {
      list.push({ video });
      if ((i + 1) % SHELF_EVERY === 0 && shelves.length) list.push({ shelf: shelves.shift() });
    });
    return list;
  }

  function openButton(word) {
    activeWord = word;
    renderHome();
    window.scrollTo(0, 0);
  }

  function shelfNode(shelf) {
    const section = el('section', 'shelf');
    const head = el(shelf.word ? 'button' : 'div', 'shelf-head');
    if (shelf.emoji) head.append(el('span', 'shelf-emoji', shelf.emoji));
    head.append(el('span', 'shelf-title', shelf.title));
    if (shelf.word) {
      head.append(el('span', 'shelf-more', '›'));
      head.addEventListener('click', () => openButton(shelf.word));
    }
    const row = el('div', 'row');
    row.append(...shelf.videos.filter((v) => !broken.has(v.id)).map(tile));
    section.append(head, row);
    return section;
  }

  function nodesFor(from, to) {
    return entries.slice(from, to)
      .map((entry) => (entry.shelf ? shelfNode(entry.shelf)
        : broken.has(entry.video.id) ? null : tile(entry.video)))
      .filter(Boolean);
  }

  // Index just past the next FEED_PAGE videos, and any shelf right after them.
  function pageEnd(from) {
    let i = from;
    let videos = 0;
    while (i < entries.length && videos < FEED_PAGE) { if (entries[i].video) videos++; i++; }
    while (i < entries.length && entries[i].shelf) i++;
    return i;
  }

  // While more is left, an invisible marker that loads the next page as he
  // nears it; after the last video, a friendly end.
  function feedFooter() {
    if (shown.count < entries.length) return el('div', 'feed-more');
    const end = el('div', 'feed-end');
    end.append(el('div', 'feed-end-emoji', '🎉'),
      el('div', '', activeWord === null ? 'You reached the end of today\'s videos!' : 'That\'s all of them for now!'),
      el('small', '', 'Tap a button at the top for more.'));
    return end;
  }

  function showMore() {
    const marker = $('today').querySelector('.feed-more');
    if (!marker || shown.count >= entries.length) return;
    const to = pageEnd(shown.count);
    const nodes = nodesFor(shown.count, to);
    shown.count = to;
    marker.replaceWith(...nodes, feedFooter());
    watchFooter();
  }

  function watchFooter() {
    if (moreObserver) moreObserver.disconnect();
    const marker = $('today').querySelector('.feed-more');
    if (!marker) return;
    // Reports right away if the marker is already near the screen, so a tall
    // screen keeps filling until it reaches past the bottom.
    moreObserver = new IntersectionObserver((seen) => {
      if (seen.some((s) => s.isIntersecting)) showMore();
    }, { rootMargin: '1200px 0px' });
    moreObserver.observe(marker);
  }

  function renderHome() {
    if (limitReached()) { show('done-screen'); return; }
    show('home');
    watchedNow = watchedMap();

    const buttons = searchButtons();
    const results = buttons.map((button) => buttonResults(button));
    let index = buttons.findIndex((b) => b.word === activeWord);
    if (index < 0 || !results[index].length) { activeWord = null; index = -1; }
    drawChips(buttons, results);

    const searching = index >= 0;
    const heading = $('heading');
    heading.classList.toggle('searching', searching);
    heading.textContent = searching
      ? `${buttons[index].emoji || '🔎'} ${buttons[index].word}`
      : "Today's videos";

    const view = searching ? `button:${activeWord}` : 'today';
    if (searching) {
      entries = results[index].map((video) => ({ video }));
    } else {
      const key = `${lineup.generated_at}|${visitSeed}`;
      if (!feed || feed.key !== key) {
        feed = { key, entries: buildFeed() };
        if (shown.view === view) shown.count = 0;
      }
      entries = feed.entries;
    }
    if (shown.view !== view) shown = { view, count: 0 };
    shown.count = 'IntersectionObserver' in window
      ? Math.min(entries.length, Math.max(shown.count, pageEnd(0)))
      : entries.length;

    $('today').replaceChildren(...(entries.length ? [...nodesFor(0, shown.count), feedFooter()] : []));
    $('empty').hidden = entries.length > 0;
    if ('IntersectionObserver' in window) watchFooter();

    const limit = limitSeconds();
    const pill = $('time-left');
    pill.hidden = limit === 0;
    if (limit) {
      const left = Math.max(1, Math.ceil((limit - watchedSeconds()) / 60));
      pill.textContent = `⏰ ${left} min left`;
    }
  }

  function show(screenId) {
    ['home', 'player-screen', 'done-screen'].forEach((id) => { $(id).hidden = id !== screenId; });
  }

  // ── Player ────────────────────────────────────────────────────────────────

  const YT_PLAYING = 1, YT_PAUSED = 2, YT_BUFFERING = 3, YT_ENDED = 0;
  let player = null;
  let currentId = null;
  let ticker = null;
  let playWait = null;
  let lastTick = 0;
  let unsavedSeconds = 0;
  let playedSeconds = 0;   // of the current video, for his favorites

  const youTubeApi = new Promise((resolve) => {
    window.onYouTubeIframeAPIReady = () => resolve(window.YT);
    const script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    script.async = true;
    document.head.append(script);
  });

  function playerState() {
    try { return player && player.getPlayerState ? player.getPlayerState() : -1; }
    catch (e) { return -1; }
  }

  function openPlayer(id) {
    // The allowlist check: nothing outside approved.json ever reaches an iframe.
    if (!approved.has(id) || !VIDEO_ID.test(id)) return;
    if (limitReached()) { show('done-screen'); return; }

    if (!$('home').hidden) homeScroll = window.scrollY;
    closePlayer(false);
    currentId = id;
    playedSeconds = 0;
    show('player-screen');
    setNeedsTap(false);
    $('pause-cover').hidden = true;
    drawProgress(0, 0);
    $('btn-toggle').textContent = '⏸';

    const params = new URLSearchParams({
      enablejsapi: '1', origin: location.origin, autoplay: '1', playsinline: '1',
      rel: '0', modestbranding: '1', controls: '0', fs: '0', disablekb: '1',
      iv_load_policy: '3',
    });
    const iframe = document.createElement('iframe');
    iframe.allow = 'autoplay; encrypted-media';
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    // No allow-popups and no allow-top-navigation: even a tap that somehow
    // reached a YouTube link could not open YouTube.
    iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
    iframe.title = 'Video';
    iframe.src = `https://www.youtube-nocookie.com/embed/${id}?${params}`;
    $('frame-holder').replaceChildren(iframe);

    youTubeApi.then((YT) => {
      if (currentId !== id) return;
      player = new YT.Player(iframe, {
        events: {
          onReady: () => { try { player.playVideo(); } catch (e) { /* ignore */ } },
          onStateChange: (event) => onStateChange(id, event.data),
          onError: () => { broken.add(id); closePlayer(true); },
        },
      });
    });

    expectPlayback();
    lastTick = Date.now();
    ticker = setInterval(tick, 500);
  }

  /* iPads sometimes refuse to start a video unless the tap lands on the video
     itself. If playback has not started shortly after we asked, open the middle
     of the shield so he can tap YouTube's play button directly. */
  function expectPlayback() {
    clearTimeout(playWait);
    playWait = setTimeout(() => {
      const state = playerState();
      if (state === YT_PLAYING) return;
      if (state === YT_BUFFERING) { expectPlayback(); return; }
      setNeedsTap(true);
    }, PLAY_WAIT_MS);
  }

  function setNeedsTap(on) {
    $('frame-box').classList.toggle('needs-tap', on);
    $('tap-hint').hidden = !on;
    if (on) $('pause-cover').hidden = true;
  }

  function onStateChange(id, state) {
    if (currentId !== id) return;
    if (state === YT_PLAYING) {
      clearTimeout(playWait);
      setNeedsTap(false);
      $('pause-cover').hidden = true;
      $('btn-toggle').textContent = '⏸';
      const watched = store.get('kt.watched', {});
      watched[id] = Date.now();
      store.set('kt.watched', watched);
    } else if (state === YT_PAUSED) {
      $('btn-toggle').textContent = '▶';
      // Hides YouTube's "more videos" shelf, which appears while paused.
      if (!$('frame-box').classList.contains('needs-tap')) $('pause-cover').hidden = false;
    } else if (state === YT_ENDED) {
      closePlayer(true);
    }
  }

  function togglePlayback() {
    if (!player || !player.playVideo) return;
    if (playerState() === YT_PLAYING) {
      player.pauseVideo();
    } else {
      player.playVideo();
      expectPlayback();
    }
  }

  // ── Seeking ───────────────────────────────────────────────────────────────

  let scrubbing = false;

  function timing() {
    try { return { current: player.getCurrentTime() || 0, duration: player.getDuration() || 0 }; }
    catch (e) { return { current: 0, duration: 0 }; }
  }

  function clock(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${r}` : `${m}:${r}`;
  }

  function drawProgress(current, duration) {
    const percent = duration > 0 ? Math.min(100, Math.max(0, (current / duration) * 100)) : 0;
    $('progress-fill').style.width = `${percent}%`;
    $('progress-knob').style.left = `${percent}%`;
    $('progress').setAttribute('aria-valuenow', String(Math.round(percent)));
    $('time-label').textContent = duration > 0 ? `${clock(current)} / ${clock(duration)}` : '';
  }

  function seekTo(seconds) {
    if (!player || !player.seekTo) return;
    const { duration } = timing();
    if (!(duration > 0)) return;
    const target = Math.max(0, Math.min(seconds, duration - SEEK_END_MARGIN));
    try { player.seekTo(target, true); } catch (e) { return; }
    drawProgress(target, duration);
  }

  function skip(delta) {
    if (!player) return;
    seekTo(timing().current + delta);
  }

  function wireScrubber() {
    const bar = $('progress');
    let pointerId = null;
    const fraction = (event) => {
      const box = bar.getBoundingClientRect();
      return box.width ? Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) : 0;
    };
    const preview = (event) => {
      const { duration } = timing();
      drawProgress(fraction(event) * duration, duration);
    };
    const finish = (event, commit) => {
      if (event.pointerId !== pointerId) return;
      pointerId = null;
      scrubbing = false;
      bar.classList.remove('scrubbing');
      if (commit) seekTo(fraction(event) * timing().duration);
    };

    bar.addEventListener('pointerdown', (event) => {
      if (!player || !(timing().duration > 0)) return;
      event.preventDefault();
      pointerId = event.pointerId;
      scrubbing = true;
      bar.classList.add('scrubbing');
      try { bar.setPointerCapture(pointerId); } catch (e) { /* ignore */ }
      preview(event);
    });
    bar.addEventListener('pointermove', (event) => {
      if (event.pointerId === pointerId) preview(event);
    });
    bar.addEventListener('pointerup', (event) => finish(event, true));
    bar.addEventListener('pointercancel', (event) => finish(event, false));
  }

  function saveWatchTime(force) {
    if (unsavedSeconds >= 5 || (force && unsavedSeconds > 0)) {
      store.set(`kt.watch.${todayKey()}`, watchedSeconds() + unsavedSeconds);
      unsavedSeconds = 0;
    }
  }

  function tick() {
    const now = Date.now();
    const elapsed = Math.min((now - lastTick) / 1000, 1);
    lastTick = now;
    if (playerState() !== YT_PLAYING) return;

    unsavedSeconds += elapsed;
    saveWatchTime(false);
    playedSeconds += elapsed;
    if (playedSeconds >= FAVORITE_AFTER_SECONDS && playedSeconds - elapsed < FAVORITE_AFTER_SECONDS) {
      creditFavorite(approved.get(currentId));
    }

    const { current, duration } = timing();
    if (duration > 0) {
      if (!scrubbing) drawProgress(current, duration);
      // Leave just before the end so YouTube's end screen never appears.
      if (duration - current < END_GUARD_SECONDS) { closePlayer(true); return; }
    }

    const limit = limitSeconds();
    if (limit > 0 && watchedSeconds() + unsavedSeconds >= limit) closePlayer(true);
  }

  function closePlayer(goHome) {
    clearInterval(ticker);
    clearTimeout(playWait);
    ticker = null;
    saveWatchTime(true);
    if (player) { try { player.destroy(); } catch (e) { /* ignore */ } }
    player = null;
    currentId = null;
    $('frame-holder').replaceChildren();
    if (goHome) {
      renderHome();
      window.scrollTo(0, homeScroll);   // back to where he was in the feed
    }
  }

  // ── Parent page ───────────────────────────────────────────────────────────

  let pinEntry = '';
  let pinIdle = null;

  function pinLength() { return Number(lineup.settings.pin_length) || 4; }

  function drawPinDots() {
    const dots = [];
    for (let i = 0; i < pinLength(); i++) dots.push(el('i', i < pinEntry.length ? 'on' : ''));
    $('pin-dots').replaceChildren(...dots);
  }

  function openPin() {
    if (!$('player-screen').hidden) closePlayer(true);
    pinEntry = '';
    drawPinDots();
    $('pin-screen').hidden = false;
    restartPinIdle();
  }

  function closePin() {
    clearTimeout(pinIdle);
    $('pin-screen').hidden = true;
  }

  function restartPinIdle() {
    clearTimeout(pinIdle);
    pinIdle = setTimeout(closePin, 15000);
  }

  async function sha256(text) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function pressPin(digit) {
    restartPinIdle();
    if (pinEntry.length >= pinLength()) return;
    pinEntry += digit;
    drawPinDots();
    if (pinEntry.length < pinLength()) return;

    let ok = false;
    try {
      ok = (await sha256(pinEntry)) === (lineup.settings.pin_sha256 || DEFAULT_PIN_SHA256);
    } catch (e) { ok = false; }
    if (ok) {
      closePin();
      openParent();
    } else {
      $('pin-dots').classList.add('wrong');
      setTimeout(() => {
        $('pin-dots').classList.remove('wrong');
        pinEntry = '';
        drawPinDots();
      }, 400);
    }
  }

  function buildPinPad() {
    const pad = $('pin-pad');
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'].forEach((digit) => {
      const button = el('button', digit === '0' ? 'wide' : '', digit);
      button.addEventListener('click', () => pressPin(digit));
      pad.append(button);
    });
  }

  function repoSlug() {
    if (lineup.settings.repo) return lineup.settings.repo;
    const host = location.hostname.match(/^([\w-]+)\.github\.io$/);
    const repo = location.pathname.split('/').filter(Boolean)[0];
    return host && repo ? `${host[1]}/${repo}` : '';
  }

  function auditItem(video, ok) {
    const item = el('div', `audit-item ${ok ? 'ok' : 'no'}`);
    item.append(el('b', '', video.title || video.id));
    const facts = [video.channel_title];
    if (video.kind === 'fun') facts.push('fun');
    if (video.educational_score) facts.push(`score ${video.educational_score}/10`);
    if (video.topics && video.topics.length) facts.push(video.topics.join(', '));
    if (video.stage === 'hard_filter') facts.push('hard filter');
    if (video.screened_at) facts.push(new Date(video.screened_at).toLocaleDateString());
    item.append(el('small', '', facts.filter(Boolean).join(' · ')));
    if (video.reason) item.append(el('p', '', video.reason));
    return item;
  }

  function fillAudit(containerId, videos, ok, emptyText) {
    const newest = [...videos]
      .sort((a, b) => ((a.screened_at || '') < (b.screened_at || '') ? 1 : -1))
      .slice(0, AUDIT_MAX);
    $(containerId).replaceChildren(
      ...(newest.length ? newest.map((v) => auditItem(v, ok)) : [el('div', 'audit-empty', emptyText)])
    );
  }

  function drawParentStatus() {
    const limit = Number(lineup.settings.daily_watch_limit_minutes) || 0;
    const watched = Math.round(watchedSeconds() / 60);
    const lines = [
      lineup.date
        ? `Lineup for ${lineup.date}, built ${new Date(lineup.generated_at).toLocaleString()}.`
        : 'No lineup has been built yet. Run the screening job.',
      `${approved.size} videos in the approved pool.`,
      limit
        ? `Watched today on this device: ${watched} of ${limit + bonusMinutes()} minutes.`
        : `Watched today on this device: ${watched} minutes (no daily limit).`,
    ];
    const buttons = searchButtons();
    if (buttons.length) {
      lines.push('Search buttons (videos each one finds; buttons with 0 are hidden): ' +
        buttons.map((b) => `${b.word} ${buttonResults(b, Infinity).length}`).join(', '));
    }
    const fav = loadFavorites();
    const now = Date.now();
    const top = Object.keys(fav.c)
      .map((id) => ({ id, score: faded(fav.c[id], now) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 6)
      .map(({ id }) => (channels.get(id) || {}).title
        || ([...approved.values()].find((v) => v.channel_id === id) || {}).channel_title)
      .filter(Boolean);
    lines.push(top.length
      ? `His favorite channels on this device, which the feed leans toward: ${top.join(', ')}.`
      : 'The feed has not learned his favorites on this device yet.');
    $('parent-status').replaceChildren(...lines.map((line) => el('div', '', line)));
  }

  async function openParent() {
    $('parent-screen').hidden = false;
    $('parent-screen').scrollTop = 0;
    drawParentStatus();

    const slug = repoSlug();
    $('link-rules').hidden = $('link-actions').hidden = !slug;
    if (slug) {
      $('link-rules').href = `https://github.com/${slug}/edit/main/rules.yaml`;
      $('link-actions').href = `https://github.com/${slug}/actions/workflows/screen.yml`;
    }

    const todays = lineupIds.map((id) => approved.get(id));
    $('parent-lineup').replaceChildren(
      ...(todays.length ? todays.map((v) => auditItem(v, true))
        : [el('div', 'audit-empty', 'Nothing in today\'s lineup.')])
    );
    fillAudit('parent-approved', [...approved.values()], true, 'No approvals yet.');
    $('parent-rejected').replaceChildren(el('div', 'audit-empty', 'Loading…'));
    try {
      const data = await getJSON('data/rejected.json');
      fillAudit('parent-rejected', data.videos || [], false, 'No rejections yet.');
    } catch (e) {
      $('parent-rejected').replaceChildren(el('div', 'audit-empty', 'Could not load rejections.'));
    }
  }

  function wireParent() {
    let press = null;
    const hotspot = $('parent-hotspot');
    const cancel = () => clearTimeout(press);
    hotspot.addEventListener('pointerdown', () => {
      cancel();
      press = setTimeout(openPin, LONG_PRESS_MS);
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((type) =>
      hotspot.addEventListener(type, cancel));

    $('pin-cancel').addEventListener('click', closePin);
    $('parent-close').addEventListener('click', () => {
      $('parent-screen').hidden = true;
      renderHome();
    });
    $('btn-more-time').addEventListener('click', () => {
      store.set(`kt.bonus.${todayKey()}`, bonusMinutes() + 15);
      drawParentStatus();
    });
    $('btn-reset-time').addEventListener('click', () => {
      store.set(`kt.watch.${todayKey()}`, 0);
      store.set(`kt.bonus.${todayKey()}`, 0);
      drawParentStatus();
    });
  }

  // ── Start ─────────────────────────────────────────────────────────────────

  // A fresh visit (opening the app, or coming back after a while) reshuffles
  // the feed and starts at the top; otherwise he stays where he was.
  async function refresh(fresh) {
    await loadData();
    if (!$('player-screen').hidden || !$('parent-screen').hidden) return;
    if (fresh) {
      startVisit();
      renderHome();
      window.scrollTo(0, 0);
    } else {
      const y = window.scrollY;
      renderHome();
      window.scrollTo(0, y);
    }
  }

  function start() {
    startVisit();
    pruneOldDays();
    buildPinPad();
    wireParent();

    $('btn-back').addEventListener('click', () => closePlayer(true));
    $('btn-toggle').addEventListener('click', togglePlayback);
    $('btn-rewind').addEventListener('click', () => skip(-SKIP_SECONDS));
    $('btn-forward').addEventListener('click', () => skip(SKIP_SECONDS));
    wireScrubber();
    document.querySelectorAll('.shield').forEach((shield) =>
      shield.addEventListener('click', togglePlayback));

    document.addEventListener('contextmenu', (event) => event.preventDefault());
    document.addEventListener('gesturestart', (event) => event.preventDefault());

    // A home-screen web app can stay open for days: reload the data whenever it
    // comes back to the foreground, and stop the video when it goes away.
    let lastDay = todayKey();
    let hiddenAt = 0;
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        hiddenAt = Date.now();
        if (playerState() === YT_PLAYING) player.pauseVideo();
        saveWatchTime(true);
      } else {
        refresh(hiddenAt > 0 && Date.now() - hiddenAt >= FRESH_VISIT_MS);
      }
    });
    setInterval(() => {
      if (todayKey() !== lastDay) {
        lastDay = todayKey();
        pruneOldDays();
        refresh(false);
      }
    }, 60000);

    refresh(true);
  }

  start();
})();

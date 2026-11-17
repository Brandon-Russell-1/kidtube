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
  const AUDIT_MAX = 40;
  const VIDEO_ID = /^[\w-]{11}$/;

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
    if (store.get('kt.watched', {})[video.id]) thumb.append(el('div', 'watched', '✓'));
    const meta = el('div', 'meta');
    meta.append(el('div', 'title', video.title), el('div', 'channel', video.channel_title));
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

  function renderHome() {
    if (limitReached()) { show('done-screen'); return; }
    show('home');

    const todayVideos = lineupIds.filter((id) => !broken.has(id)).map((id) => approved.get(id));
    $('today').replaceChildren(...todayVideos.map(tile));
    $('empty').hidden = todayVideos.length > 0;

    const again = watchAgainIds().map((id) => approved.get(id));
    $('again').replaceChildren(...again.map(tile));
    $('again-section').hidden = again.length === 0;

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

    closePlayer(false);
    currentId = id;
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
    if (goHome) renderHome();
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

  async function refresh() {
    await loadData();
    if ($('player-screen').hidden && $('parent-screen').hidden) renderHome();
  }

  function start() {
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
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (playerState() === YT_PLAYING) player.pauseVideo();
        saveWatchTime(true);
      } else {
        refresh();
      }
    });
    setInterval(() => {
      if (todayKey() !== lastDay) {
        lastDay = todayKey();
        pruneOldDays();
        refresh();
      }
    }, 60000);

    refresh();
  }

  start();
})();

/* Project Dashboard — frontend logic (vanilla JS). */

// status dot colors per design tokens (Deep-Blue)
const STATUS = {
  idle:      { label: 'Idle',      dot: '#3F8EE0' },
  analyzing: { label: 'Analyzing', dot: '#E0922F' },
  running:   { label: 'Running',   dot: '#7FC04B' },
  stopped:   { label: 'Stopped',  dot: '#E0567D' },
  complete:  { label: 'Complete', dot: '#3A6FE0' },
};

// language → color (exact from design handoff; extras kept for other langs)
const LANG_COLOR = {
  py: '#4B8BBE', json: '#C9B458', md: '#7C8694', tsx: '#3F8EE0', ts: '#2F7BD6',
  jsx: '#56C8E8', sql: '#E0922F', html: '#E0612F', h: '#A074C4', cpp: '#E0567D',
  sh: '#7FC04B', js: '#C9B458', go: '#00ADD8', rs: '#dea584', java: '#b07219',
  rb: '#701516', php: '#7C8694', css: '#56C8E8', scss: '#56C8E8', vue: '#7FC04B',
  svelte: '#E0612F', c: '#7C8694', hpp: '#A074C4', swift: '#E0612F', kt: '#A074C4',
  bash: '#7FC04B', zsh: '#7FC04B', yml: '#E0922F', yaml: '#E0922F', toml: '#7C8694',
};

let PROJECTS = [];
let FILTER = '';     // sidebar status filter
let QUERY = '';      // search text
let SORT = 'recent'; // recent | name | size

const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const fmt = n => (n || 0).toLocaleString('ru-RU');
const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// epoch-seconds → short relative ru time
function relTime(ts) {
  if (!ts) return '—';
  const s = Date.now() / 1000 - ts;
  if (s < 60) return 'только что';
  const m = s / 60; if (m < 60) return Math.floor(m) + ' мин';
  const h = m / 60; if (h < 24) return Math.floor(h) + ' ч';
  const d = h / 24; if (d < 30) return Math.floor(d) + ' дн';
  const mo = d / 30; if (mo < 12) return Math.floor(mo) + ' мес';
  return Math.floor(mo / 12) + ' г';
}
// last two path segments — readable, no ugly rtl truncation
const shortPath = p => p.replace(/\/$/, '').split('/').slice(-2).join('/');

// project health by last activity: 🟢 <7d · 🟡 7–30d · ⚪ stale/unknown
function health(ts) {
  if (!ts) return { color: 'var(--faint-fg)', label: 'не сканировано' };
  const d = (Date.now() / 1000 - ts) / 86400;
  if (d < 7)  return { color: 'var(--ok)',    label: 'активный · <7 дней' };
  if (d < 30) return { color: 'var(--warn)',  label: '7–30 дней' };
  return { color: 'var(--faint-fg)', label: 'давно не трогали · >30 дней' };
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let d = {}; try { d = await r.json(); } catch (e) {}
    const err = new Error(d.error || ('HTTP ' + r.status));
    err.status = r.status;
    throw err;
  }
  return r.json();
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2200);
}

/* ---------- lightweight themed modals (replace native confirm/prompt) ---------- */
function overlay(cardHTML) {
  const root = el('div', 'pd-modal pd-mini');
  root.innerHTML = `<div class="pd-mini-card">${cardHTML}</div>`;
  document.body.appendChild(root);
  const close = () => { root.remove(); document.removeEventListener('keydown', onKey); };
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);
  root.addEventListener('click', e => { if (e.target === root) close(); });
  return { root, close };
}
function pdConfirm(msg, okLabel = 'Удалить') {
  return new Promise(res => {
    const { root, close } = overlay(`
      <div class="pd-mini-body">${esc(msg)}</div>
      <div class="pd-mini-foot">
        <button class="pd-btn" data-x="no">Отмена</button>
        <button class="pd-btn primary" data-x="yes">${esc(okLabel)}</button>
      </div>`);
    root.querySelector('[data-x="no"]').onclick = () => { close(); res(false); };
    root.querySelector('[data-x="yes"]').onclick = () => { close(); res(true); };
  });
}
function pdPrompt(title, value = '', placeholder = 'например: npm run dev') {
  return new Promise(res => {
    const { root, close } = overlay(`
      <div class="pd-mini-title">${esc(title)}</div>
      <input class="pd-mini-input" value="${esc(value)}" placeholder="${esc(placeholder)}" />
      <div class="pd-mini-foot">
        <button class="pd-btn" data-x="no">Отмена</button>
        <button class="pd-btn primary" data-x="ok">OK</button>
      </div>`);
    const inp = root.querySelector('.pd-mini-input');
    inp.focus(); inp.select();
    const ok = () => { close(); res(inp.value.trim()); };
    root.querySelector('[data-x="ok"]').onclick = ok;
    root.querySelector('[data-x="no"]').onclick = () => { close(); res(null); };
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') ok(); });
  });
}

/* ---------- load + render ---------- */
async function load() {
  const data = await api('/api/projects');
  PROJECTS = data.projects || [];
  render();
}

function sortProjects(arr) {
  const a = [...arr];
  if (SORT === 'name') a.sort((x, y) => x.name.localeCompare(y.name, 'ru'));
  else if (SORT === 'size') a.sort((x, y) => (y.lines || 0) - (x.lines || 0));
  else a.sort((x, y) => (y.last_modified || 0) - (x.last_modified || 0)); // recent
  return a;
}

function visibleProjects() {
  const filtered = PROJECTS.filter(p => {
    if (FILTER && p.status !== FILTER) return false;
    if (QUERY) {
      const q = QUERY.toLowerCase();
      if (!p.name.toLowerCase().includes(q) && !p.path.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  return sortProjects(filtered);
}

function render() {
  renderBanner();
  renderStats();
  renderCards();
  $('#nav-count').textContent = PROJECTS.length;
  const pc = $('#proj-count');
  if (pc) pc.textContent = `${visibleProjects().length} из ${PROJECTS.length}`;
}

/* persistent banner: onboarding (no projects) or TCC access nudge */
function renderBanner() {
  const b = $('#pd-banner');
  if (!b) return;
  if (!PROJECTS.length) {
    b.hidden = false; b.className = 'pd-banner info';
    b.innerHTML = `<span>👋 Пока нет проектов. Добавь папку или найди все репозитории в папке сразу.</span>
      <button class="pd-btn" data-b="discover">🔍 Найти в папке</button>
      <button class="pd-btn primary" data-b="add">＋ Добавить проект</button>`;
    b.querySelector('[data-b="add"]').onclick = () => $('#add-btn').click();
    b.querySelector('[data-b="discover"]').onclick = () => $('#grant-btn').click();
  } else if (PROJECTS.some(p => p.scan_error === 'no_access')) {
    b.hidden = false; b.className = 'pd-banner warn';
    b.innerHTML = `<span>🔒 Часть папок без доступа (macOS). Выдай доступ к папке с проектами — и сканирование заработает.</span>
      <button class="pd-btn primary" data-b="grant">Дать доступ</button>`;
    b.querySelector('[data-b="grant"]').onclick = () => $('#grant-btn').click();
  } else {
    b.hidden = true;
  }
}

function renderStats() {
  const total = PROJECTS.length;
  const files = PROJECTS.reduce((s, p) => s + (p.files || 0), 0);
  const lines = PROJECTS.reduce((s, p) => s + (p.lines || 0), 0);
  const active = PROJECTS.filter(p => p.status === 'running').length;
  const dirty = PROJECTS.filter(p => p.git && p.git.dirty).length;
  const now = Date.now() / 1000;
  const recent = PROJECTS.filter(p => p.last_modified && now - p.last_modified < 7 * 86400).length;

  const wrap = $('#stats');
  wrap.innerHTML = '';

  // feature tile (1.55fr) — headline KPI
  const feature = el('div', 'mi-tile mi-feature');
  feature.innerHTML = `
    <div class="mi-feature-top">${ICON.grid}Проектов на этом Mac</div>
    <div class="mi-feature-num tnum">${fmt(total)}</div>
    <div class="mi-feature-tags">
      <span class="mi-ftag">${ICON.play}${active} активных</span>
      <span class="mi-ftag">${ICON.branch}${dirty} с изменениями</span>
      <span class="mi-ftag ghost">${fmt(recent)} тронуто за неделю</span>
    </div>`;
  wrap.appendChild(feature);

  // three stat tiles
  const tiles = [
    { label: 'Файлов кода', val: fmt(files), sub: 'без lock/min', icon: ICON.file },
    { label: 'Строк кода', val: fmt(lines), sub: 'весь код проектов', icon: ICON.code },
  ];
  tiles.forEach(t => {
    const c = el('div', 'mi-tile mi-stat');
    c.innerHTML = `
      <span class="mi-stat-ico">${t.icon}</span>
      <div class="mi-stat-lbl">${t.label}</div>
      <div class="mi-stat-num tnum">${t.val}</div>
      <div class="mi-stat-sub">${t.sub}</div>`;
    wrap.appendChild(c);
  });
}

function renderCards() {
  const wrap = $('#projects');
  wrap.innerHTML = '';
  const list = visibleProjects();

  if (!list.length) {
    const noProjects = PROJECTS.length === 0;
    const e = el('div', 'pd-empty');
    e.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        <path d="M12 11v6M9 14h6"/>
      </svg>
      <b>${esc(noProjects ? 'Пока нет проектов' : 'Ничего не найдено')}</b>
      <span>${esc(noProjects ? 'Добавьте папку проекта на вашем Mac' : 'Измените поиск или фильтр')}</span>
      ${noProjects ? '<button class="pd-btn primary" data-act="cta-add">＋ Добавить проект</button>' : ''}`;
    if (noProjects) {
      e.querySelector('[data-act="cta-add"]').addEventListener('click', () => $('#add-btn').click());
    }
    wrap.appendChild(e);
    return;
  }
  list.forEach(p => wrap.appendChild(card(p)));
}

/* git branch badge: ⎇ branch · dirty · ahead/behind */
function gitBadge(g) {
  if (!g) return '';
  const ab = (g.ahead || g.behind)
    ? `<span class="g-ab">${g.ahead ? '↑' + g.ahead : ''}${g.behind ? ' ↓' + g.behind : ''}</span>` : '';
  const dot = g.dirty ? '<span class="dirty" title="есть несохранённые изменения"></span>' : '';
  return `<span class="mi-branch" title="git: ${esc(g.branch)}${g.dirty ? ' · dirty' : ''}">
    ${ICON.branch}<span class="bn">${esc(g.branch)}</span>${dot}${ab}</span>`;
}

/* stacked language bar (segments sized by file share) */
function langBar(langs) {
  const entries = Object.entries(langs || {});
  const segs = entries.length ? (() => {
    const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
    return entries.map(([ext, n]) => {
      const k = ext.replace('.', '');
      const col = LANG_COLOR[k] || '#8a96ad';
      return `<span style="width:${(n / total * 100).toFixed(2)}%;background:${col}" title="${esc(k)} ${n}"></span>`;
    }).join('');
  })() : '';
  return `<div class="mi-bar">${segs}</div>`;
}

function card(p) {
  const st = STATUS[p.status] || STATUS.idle;
  const running = p.status === 'running';
  const c = el('div', 'mi-tile mi-proj' + (running ? ' is-running' : ''));
  c.dataset.id = p.id;

  const chips = Object.entries(p.langs || {}).slice(0, 6).map(([ext, n]) => {
    const k = ext.replace('.', '');
    return `<span class="mi-chip"><i style="background:${LANG_COLOR[k] || '#8a96ad'}"></i>${esc(k)} ${n}</span>`;
  }).join('');
  const opts = Object.keys(STATUS)
    .map(s => `<option value="${s}" ${s === p.status ? 'selected' : ''}>${STATUS[s].label}</option>`).join('');
  const hasNotes = p.notes && p.notes.trim();
  const runTitle = p.run_cmd ? `Запустить: ${p.run_cmd} (Alt-клик — изменить)` : 'Запустить (задать команду)';
  const now = Date.now() / 1000;
  const recent = p.last_modified && now - p.last_modified < 7 * 86400;
  const tone = recent ? 'is-green' : 'is-blue';
  const commit = (p.git && p.git.msg)
    ? `<div class="mi-commit" title="${esc(p.git.msg)}${p.git.rel ? ' · ' + esc(p.git.rel) : ''}">
         ${ICON.commit}<span class="c-msg">${esc(p.git.msg)}</span>${p.git.rel ? `<span class="c-rel">${esc(p.git.rel)}</span>` : ''}</div>`
    : '';

  c.innerHTML = `
    <div class="mi-proj-head">
      <div class="mi-proj-name">
        <span class="mi-dot" style="background:${st.dot}"></span>
        <span class="nm" title="${esc(p.name)}">${esc(p.name)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex:0 0 auto">
        ${gitBadge(p.git)}
        <span class="mi-del" data-act="remove" title="Убрать из Dashhy">
          <svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </span>
      </div>
    </div>
    <div class="mi-proj-path" title="${esc(p.path)}">${esc(shortPath(p.path))}</div>

    <div class="mi-proj-metrics">
      <div class="mi-m"><b class="tnum">${fmt(p.files)}</b><span>файлов</span></div>
      <div class="mi-m"><b class="tnum">${fmt(p.lines)}${p.lines_partial ? '+' : ''}</b><span>строк</span></div>
      <div class="mi-m"><b class="tnum ${tone}" title="${esc(health(p.last_modified).label)}">${relTime(p.last_modified)}</b><span>изменён</span></div>
    </div>

    ${langBar(p.langs)}
    <div class="mi-chips">${chips}</div>
    ${commit}

    <div class="mi-proj-foot">
      <select class="mi-pill mi-pill--${p.status}" data-act="status">${opts}</select>
      <div class="mi-acts">
        <button class="mi-act" data-act="terminal" title="Открыть Terminal здесь">
          <svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/></svg>
        </button>
        <button class="mi-act ${p.run_cmd ? 'has-dot' : ''}" data-act="run" title="${esc(runTitle)}">
          <svg viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4"/></svg>
        </button>
        <button class="mi-act" data-act="scan" title="Пересканировать">
          <svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.2-8.6"/><path d="M21 3v6h-6"/></svg>
        </button>
        <button class="mi-act" data-act="files" title="Файлы / README">
          <svg viewBox="0 0 24 24"><path d="M14 3v5h5"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M8 13h8M8 17h5"/></svg>
        </button>
        <button class="mi-act ${hasNotes ? 'has-dot' : ''}" data-act="notes" title="Заметки / TODO">
          <svg viewBox="0 0 24 24"><path d="M5 4h11l3 3v13H5z"/><path d="M8 10h8M8 14h8M8 17h5"/></svg>
        </button>
        <button class="mi-act" data-act="finder" title="Открыть в Finder">
          <svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
        </button>
        <button class="mi-act is-primary" data-act="editor" title="Открыть в редакторе">
          <svg viewBox="0 0 24 24"><path d="m18 16 4-4-4-4M6 8l-4 4 4 4M14.5 4l-5 16"/></svg>
        </button>
      </div>
    </div>`;

  let tipTimer;
  c.addEventListener('mouseenter', () => { tipTimer = setTimeout(() => showTip(c, p.id), 700); });
  c.addEventListener('mouseleave', () => { clearTimeout(tipTimer); hideTip(); });
  return c;
}

/* ---------- hover info popover ---------- */
let TIP_TOKEN = 0;
async function showTip(cardEl, id) {
  const token = ++TIP_TOKEN;
  let info;
  try { info = (await api(`/api/info?id=${encodeURIComponent(id)}`)).info; }
  catch (e) { return; }
  if (token !== TIP_TOKEN || !info) return;   // moved away while fetching

  const langs = (info.langs || [])
    .map(([k, n]) => `<span class="pd-tip-lang">${esc(k)} ${n}</span>`).join('');
  const tip = $('#pd-tip');
  tip.innerHTML = `
    <div class="pd-tip-h">${esc(info.name)}</div>
    <div class="pd-tip-kind">${esc(info.kind)}</div>
    ${info.desc ? `<div class="pd-tip-desc">${esc(info.desc)}</div>` : ''}
    <div class="pd-tip-stats">${esc(info.stats)}</div>
    ${langs ? `<div class="pd-tip-langs">${langs}</div>` : ''}`;
  tip.hidden = false;

  // position: prefer right of the card, flip/clamp to viewport
  const r = cardEl.getBoundingClientRect();
  const tw = tip.offsetWidth, th = tip.offsetHeight, M = 8;
  let left = r.right + 12;
  if (left + tw > window.innerWidth - M) left = r.left - tw - 12;
  left = Math.max(M, Math.min(left, window.innerWidth - tw - M));
  let top = Math.max(M, Math.min(r.top, window.innerHeight - th - M));
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}
function hideTip() { TIP_TOKEN++; const t = $('#pd-tip'); if (t) t.hidden = true; }

/* ---------- card actions (event delegation) ---------- */
$('#projects').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-act]');
  if (!btn) return;
  const cardEl = ev.target.closest('.mi-proj');
  if (!cardEl) return;
  const id = cardEl.dataset.id;
  const proj = PROJECTS.find(p => p.id === id);
  if (!proj) return;
  const act = btn.dataset.act;

  try {
    if (act === 'remove') {
      if (!await pdConfirm(`Удалить «${proj.name}» из дашборда? Папка на диске не трогается.`)) return;
      await api(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' });
      return load();
    }
    if (act === 'scan') {
      const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="pd-spin"></span>';
      try {
        const r = await api('/api/scan', { method: 'POST', body: JSON.stringify({ id }) });
        if (r.project) { Object.assign(proj, r.project); render(); toast('Готово: ' + r.project.last_stage); }
      } finally { btn.disabled = false; btn.innerHTML = old; }
      return;
    }
    if (act === 'files')  return openFiles(proj);
    if (act === 'notes')  return openNotes(proj);
    if (act === 'finder') { await api('/api/open', { method: 'POST', body: JSON.stringify({ id }) }); return toast('Открыто в Finder'); }
    if (act === 'editor') { await api('/api/open', { method: 'POST', body: JSON.stringify({ id, editor: true }) }); return toast('Открыто в редакторе'); }
    if (act === 'terminal') { await api('/api/launch', { method: 'POST', body: JSON.stringify({ id }) }); return toast('Terminal открыт'); }
    if (act === 'run') {
      if (ev.altKey || !proj.run_cmd) {
        const cmd = await pdPrompt(`Команда запуска для «${proj.name}»`, proj.run_cmd || '');
        if (cmd == null) return;                       // cancelled
        const rc = await api('/api/run-cmd', { method: 'POST', body: JSON.stringify({ id, cmd }) });
        if (rc.project) { Object.assign(proj, rc.project); render(); }
        if (!cmd) return;                              // saved empty → just clear, don't launch
      }
      await api('/api/launch', { method: 'POST', body: JSON.stringify({ id, run: true }) });
      return toast('Запущено: ' + proj.run_cmd);
    }
  } catch (e) {
    btn.disabled = false;
    toast('Ошибка: ' + (e.message || e));
  }
});

$('#projects').addEventListener('change', async (ev) => {
  const sel = ev.target.closest('[data-act="status"]');
  if (!sel) return;
  const id = ev.target.closest('.mi-proj').dataset.id;
  try {
    const r = await api('/api/status', { method: 'POST', body: JSON.stringify({ id, status: sel.value }) });
    if (r.project) { Object.assign(PROJECTS.find(p => p.id === id), r.project); render(); }
  } catch (e) { toast('Ошибка: ' + e.message); }
});

/* ---------- notes / TODO modal ---------- */
async function openNotes(proj) {
  const { root, close } = overlay(`
    <div class="pd-mini-title">📝 Заметки — ${esc(proj.name)}</div>
    <textarea class="pd-mini-area" placeholder="Где остановился, что дальше, баги, идеи…">${esc(proj.notes || '')}</textarea>
    <div class="pd-mini-foot">
      <button class="pd-btn" data-x="no">Закрыть</button>
      <button class="pd-btn primary" data-x="save">Сохранить</button>
    </div>`);
  const ta = root.querySelector('.pd-mini-area');
  ta.focus();
  root.querySelector('[data-x="no"]').onclick = close;
  root.querySelector('[data-x="save"]').onclick = async () => {
    try {
      const r = await api('/api/notes', { method: 'POST', body: JSON.stringify({ id: proj.id, notes: ta.value }) });
      if (r.project) { Object.assign(proj, r.project); render(); toast('Заметки сохранены'); }
    } catch (e) { toast('Ошибка: ' + e.message); }
    close();
  };
}

/* ---------- add project ---------- */
$('#add-btn').addEventListener('click', async () => {
  const btn = $('#add-btn');
  btn.disabled = true;
  try {
    const picked = await api('/api/pick', { method: 'POST' });
    if (!picked.path) return;                       // user cancelled dialog
    const r = await api('/api/projects', {
      method: 'POST', body: JSON.stringify({ path: picked.path }),
    });
    if (r.project) {
      await load();
      toast(`Добавлен: ${r.project.name}`);
      await api('/api/scan', { method: 'POST', body: JSON.stringify({ id: r.project.id }) });
      await load();
    } else {
      toast('Не удалось добавить папку');
    }
  } catch (e) {
    toast('Ошибка: ' + e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- files modal ---------- */
async function openFiles(proj) {
  const m = $('#files-modal');
  $('#fm-title').textContent = proj.name;
  $('#fm-path').textContent = proj.path;
  $('#fm-code').textContent = '← выберите файл';
  const tree = $('#fm-tree');
  tree.innerHTML = '<div class="pd-tree-item">Загрузка…</div>';
  m.hidden = false;

  let fileToken = (openFiles._t = (openFiles._t || 0) + 1);
  let r;
  try { r = await api(`/api/files?id=${encodeURIComponent(proj.id)}`); }
  catch (e) { tree.innerHTML = `<div class="pd-tree-item">Ошибка: ${esc(e.message)}</div>`; return; }
  const files = r.files || [];
  tree.innerHTML = '';
  if (!files.length) {
    tree.innerHTML = '<div class="pd-tree-item">Нет файлов — сначала Scan</div>';
    return;
  }
  files.forEach(f => {
    const it = el('div', 'pd-tree-item', esc(f));
    it.title = f;
    it.addEventListener('click', async () => {
      tree.querySelectorAll('.on').forEach(x => x.classList.remove('on'));
      it.classList.add('on');
      const tok = ++fileToken;
      $('#fm-code').textContent = 'Загрузка…';
      try {
        const fr = await api(`/api/file?id=${encodeURIComponent(proj.id)}&path=${encodeURIComponent(f)}`);
        if (tok !== fileToken) return;               // a newer file was clicked
        $('#fm-code').textContent = fr.content != null ? fr.content : (fr.error || 'Ошибка');
      } catch (e) {
        if (tok === fileToken) $('#fm-code').textContent = 'Ошибка: ' + e.message;
      }
    });
    tree.appendChild(it);
  });
}
$('#fm-close').addEventListener('click', () => { $('#files-modal').hidden = true; });
$('#files-modal').addEventListener('click', (e) => {
  if (e.target.id === 'files-modal') e.target.hidden = true;
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#files-modal').hidden) $('#files-modal').hidden = true;
});

/* ---------- search + sort + sidebar filter ---------- */
$('#search').addEventListener('input', (e) => { QUERY = e.target.value; renderCards(); });
const sortSel = $('#sort-sel');
if (sortSel) sortSel.addEventListener('change', (e) => { SORT = e.target.value; renderCards(); });
document.querySelectorAll('.mi-railbtn').forEach(nav => {
  nav.addEventListener('click', () => {
    document.querySelectorAll('.mi-railbtn').forEach(n => n.classList.remove('on'));
    nav.classList.add('on');
    FILTER = nav.dataset.filter || '';
    const title = $('#screen-title');
    if (title) title.textContent = nav.dataset.label || 'Dashhy';
    render();
  });
});

/* ---------- theme ---------- */
const SUN = '<path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>';
const MOON = '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>';
function applyTheme(t) {
  document.body.dataset.theme = t;
  $('#theme-icon').innerHTML = t === 'dark' ? SUN : MOON;
  try { localStorage.setItem('pd-theme', t); } catch (e) {}
}
$('#theme-toggle').addEventListener('click', () => {
  applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
});

/* ---------- grant folder access (Powerbox) ---------- */
$('#grant-btn').addEventListener('click', async () => {
  const btn = $('#grant-btn');
  btn.disabled = true;
  try {
    const picked = await api('/api/pick', { method: 'POST' });
    if (!picked.path) return;                 // cancelled
    toast('Доступ выдан, ищу проекты…');
    const disc = await api('/api/discover', { method: 'POST', body: JSON.stringify({ path: picked.path }) });
    await api('/api/scan-all', { method: 'POST' });
    await load();
    const n = (disc.added || []).length;
    toast(n ? `Найдено новых проектов: ${n}` : `Готово: доступ к «${picked.path}»`);
  } catch (e) {
    toast('Ошибка: ' + e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- refresh all ---------- */
$('#refresh-btn').addEventListener('click', async () => {
  const btn = $('#refresh-btn');
  const svg = $('#refresh-icon');
  btn.disabled = true;
  svg.innerHTML = '<animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/><path d="M21 12a9 9 0 1 1-6.2-8.6"/><path d="M21 3v6h-6"/>';
  try {
    const r = await api('/api/scan-all', { method: 'POST' });
    const count = (r.results || []).filter(x => x.ok).length;
    toast(`Обновлено: ${count} проект(ов)`);
    await load();
  } catch (e) {
    toast('Ошибка обновления: ' + e.message);
  } finally {
    btn.disabled = false;
    svg.innerHTML = '<path d="M21 12a9 9 0 1 1-6.2-8.6"/><path d="M21 3v6h-6"/>';
  }
});

/* ---------- shared inline icons ---------- */
const ICON = {
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  file:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M14 3v5h5"/><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>',
  code:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m8 8-4 4 4 4M16 8l4 4-4 4M13 5l-2 14"/></svg>',
  clock:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  play:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>',
  git:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="6" cy="6" r="2.4"/><circle cx="6" cy="18" r="2.4"/><circle cx="18" cy="9" r="2.4"/><path d="M6 8.4v7.2M18 11.4c0 3-3 3.6-6 3.6"/></svg>',
  branch: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="9" r="2.2"/><path d="M6 8.2v7.6M18 11.2c0 3.2-4 2.8-6 3.6"/></svg>',
  commit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="3.2"/><path d="M3 12h5.8M15.2 12H21"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
};

/* ---------- command palette (⌘K) ---------- */
function fuzzy(q, s) {
  q = q.toLowerCase(); s = s.toLowerCase();
  if (!q) return 0;
  let i = 0, score = 0, last = -2;
  for (const ch of q) {
    const idx = s.indexOf(ch, i);
    if (idx < 0) return -1;
    score += (idx === last + 1) ? 2 : 1;   // consecutive-char bonus
    last = idx; i = idx + 1;
  }
  return score - s.length * 0.01;          // prefer shorter matches
}

function buildCommands() {
  const cmds = [
    { label: 'Сканировать все проекты', run: () => $('#refresh-btn').click() },
    { label: 'Сменить тему', run: () => $('#theme-toggle').click() },
    { label: 'Добавить проект', run: () => $('#add-btn').click() },
    { label: 'Найти проекты в папке', run: () => $('#grant-btn').click() },
  ];
  PROJECTS.forEach(p => {
    cmds.push({
      label: `Открыть «${p.name}» в редакторе`, hint: shortPath(p.path),
      run: () => api('/api/open', { method: 'POST', body: JSON.stringify({ id: p.id, editor: true }) })
        .then(() => toast('Открыто: ' + p.name)).catch(e => toast('Ошибка: ' + e.message)),
    });
    cmds.push({
      label: `Terminal: ${p.name}`, hint: shortPath(p.path),
      run: () => api('/api/launch', { method: 'POST', body: JSON.stringify({ id: p.id }) })
        .then(() => toast('Terminal: ' + p.name)).catch(e => toast('Ошибка: ' + e.message)),
    });
  });
  return cmds;
}

function openPalette() {
  if (document.querySelector('.pd-palette')) return;   // already open
  const cmds = buildCommands();
  const root = el('div', 'pd-modal pd-palette');
  root.innerHTML = `<div class="pd-pal-card">
      <input class="pd-pal-input" placeholder="Команда или проект…  ↑↓ выбрать · Enter выполнить" />
      <div class="pd-pal-list"></div>
    </div>`;
  document.body.appendChild(root);
  const input = root.querySelector('.pd-pal-input');
  const listEl = root.querySelector('.pd-pal-list');
  let items = [], sel = 0;
  const close = () => { root.remove(); document.removeEventListener('keydown', onKey, true); };

  function renderList() {
    const q = input.value.trim();
    let scored = cmds.map(c => ({ c, s: q ? fuzzy(q, c.label + ' ' + (c.hint || '')) : 0 }));
    if (q) scored = scored.filter(x => x.s >= 0).sort((a, b) => b.s - a.s);
    items = scored.slice(0, 8).map(x => x.c);
    sel = 0;
    listEl.innerHTML = items.length
      ? items.map((c, i) => `<div class="pd-pal-item ${i === 0 ? 'on' : ''}" data-i="${i}">
          <span class="pd-pal-label">${esc(c.label)}</span>
          ${c.hint ? `<span class="pd-pal-hint">${esc(c.hint)}</span>` : ''}</div>`).join('')
      : `<div class="pd-pal-empty">Ничего не найдено</div>`;
  }
  function move(d) {
    if (!items.length) return;
    sel = (sel + d + items.length) % items.length;
    listEl.querySelectorAll('.pd-pal-item').forEach((e, i) => e.classList.toggle('on', i === sel));
    const on = listEl.querySelector('.on'); if (on) on.scrollIntoView({ block: 'nearest' });
  }
  function runSel() { const c = items[sel]; if (!c) return; close(); c.run(); }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); runSel(); }
  }
  input.addEventListener('input', renderList);
  document.addEventListener('keydown', onKey, true);
  listEl.addEventListener('click', e => { const it = e.target.closest('[data-i]'); if (it) { sel = +it.dataset.i; runSel(); } });
  root.addEventListener('click', e => { if (e.target === root) close(); });
  renderList(); input.focus();
}
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openPalette(); }
});

/* ---------- auto-refresh when the window regains focus ---------- */
let lastAuto = 0;
function autoRefresh() {
  load().catch(() => {});                 // instant: reflect current registry
  const t = Date.now();
  if (t - lastAuto < 45000) return;       // throttle the heavier rescan
  lastAuto = t;
  api('/api/scan-all', { method: 'POST' }).then(() => load()).catch(() => {});
}
window.addEventListener('focus', autoRefresh);
document.addEventListener('visibilitychange', () => { if (!document.hidden) autoRefresh(); });

/* ---------- init ---------- */
(function init() {
  let t = 'light';
  try { t = localStorage.getItem('pd-theme') || 'light'; } catch (e) {}
  applyTheme(t);
  const d = new Date();
  $('#crumb-date').textContent = d.toLocaleDateString('ru-RU',
    { weekday: 'long', day: 'numeric', month: 'long' });
  document.body.classList.add('bn-ready');
  load().catch(err => toast('Ошибка загрузки: ' + err.message));
})();

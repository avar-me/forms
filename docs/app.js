/**
 * Avar wordforms search — forms.avar.me
 */

const CONFIG = {
    MAX_SUGGESTIONS: 20,
    MAX_PREFIX_LIST: 100,
    MIN_PREFIX_LIST: 2,
    HOME_SAMPLES: 10,
    GAP_SAMPLES: 30,
    DEBOUNCE_DELAY: 150,
    CHUNK_CACHE_SIZE: 50,
    DATA_PREFIX: 'data/wordforms',
    GAPS_PREFIX: 'data/gaps',
    DICT_BASE: 'https://dev.avar.me/'
};

const state = {
    wordformsIndex: null,
    browse: null,
    manifest: null,
    chunkCache: new Map(),
    currentQuery: '',
    isLoading: false,
    activeFilter: null,
    gapFilterManifest: null,
    gapWordforms: null,
    lemmaIndex: null,
    lemmaFreq: null,
    activeLemma: null
};

function debounce(func, delay) {
    let timeoutId;
    const debounced = function (...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
    debounced.cancel = () => clearTimeout(timeoutId);
    return debounced;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function normalizeWord(word) {
    return String(word)
        .toLowerCase()
        .trim()
        .replace(/[1IiｌlL|!ǀӀІ]/g, 'ӏ');
}

function binarySearchPrefix(words, prefix) {
    const prefixNorm = normalizeWord(prefix);
    let left = 0;
    let right = words.length - 1;
    let result = -1;

    while (left <= right) {
        const mid = Math.floor((left + right) / 2);
        const wordNorm = normalizeWord(words[mid]);
        if (wordNorm >= prefixNorm) {
            result = mid;
            right = mid - 1;
        } else {
            left = mid + 1;
        }
    }

    if (result === -1) return [];

    const matches = [];
    for (let i = result; i < words.length && matches.length < CONFIG.MAX_SUGGESTIONS; i++) {
        if (normalizeWord(words[i]).startsWith(prefixNorm)) {
            matches.push(words[i]);
        } else {
            break;
        }
    }
    return matches;
}

function collectPrefixList(words, prefix, limit) {
    const prefixNorm = normalizeWord(prefix);
    let left = 0;
    let right = words.length - 1;
    let result = -1;

    while (left <= right) {
        const mid = Math.floor((left + right) / 2);
        if (normalizeWord(words[mid]) >= prefixNorm) {
            result = mid;
            right = mid - 1;
        } else {
            left = mid + 1;
        }
    }

    if (result === -1) return [];
    const matches = [];
    for (let i = result; i < words.length && matches.length < limit; i++) {
        if (normalizeWord(words[i]).startsWith(prefixNorm)) {
            matches.push(words[i]);
        } else {
            break;
        }
    }
    return matches;
}

async function loadWordformsIndex() {
    const response = await fetch(`${CONFIG.DATA_PREFIX}/index.wordforms.txt`);
    if (!response.ok) throw new Error('Не удалось загрузить индекс словоформ');
    const text = await response.text();
    state.wordformsIndex = text.split('\n').filter(Boolean);
    console.log(`Loaded index (${state.wordformsIndex.length} wordforms)`);
}

async function loadBrowse() {
    const response = await fetch(`${CONFIG.DATA_PREFIX}/browse.json`);
    if (!response.ok) throw new Error('Не удалось загрузить browse.json');
    state.browse = await response.json();
}

async function loadLemmaFreq() {
    const response = await fetch(`${CONFIG.DATA_PREFIX}/lemma_freq.json`);
    if (!response.ok) throw new Error('Не удалось загрузить lemma_freq.json');
    state.lemmaFreq = await response.json();
}

function lemmaTotal(lemma) {
    return (lemma && state.lemmaFreq?.[lemma]) || 0;
}

function pluralOccurrences(n) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return 'вхождение';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'вхождения';
    return 'вхождений';
}

async function loadManifest() {
    const response = await fetch(`${CONFIG.DATA_PREFIX}/manifest.json`);
    if (!response.ok) throw new Error('Не удалось загрузить manifest.json');
    state.manifest = await response.json();
}

async function loadChunk(chunkFile) {
    const cacheKey = chunkFile;
    if (state.chunkCache.has(cacheKey)) {
        return state.chunkCache.get(cacheKey);
    }
    const response = await fetch(`${CONFIG.DATA_PREFIX}/chunks/${chunkFile}`);
    if (!response.ok) throw new Error(`Не удалось загрузить ${chunkFile}`);
    const data = await response.json();
    if (state.chunkCache.size >= CONFIG.CHUNK_CACHE_SIZE) {
        const firstKey = state.chunkCache.keys().next().value;
        state.chunkCache.delete(firstKey);
    }
    state.chunkCache.set(cacheKey, data);
    return data;
}

function findChunkForWord(word, manifest) {
    const wordNorm = normalizeWord(word);
    let bestMatch = null;
    let bestLen = -1;

    for (const chunk of manifest.chunks) {
        const prefixNorm = normalizeWord(chunk.prefix);
        if (wordNorm.startsWith(prefixNorm) && prefixNorm.length > bestLen) {
            bestMatch = chunk.file;
            bestLen = prefixNorm.length;
        }
    }
    return bestMatch;
}

async function getWordformData(wordform) {
    const chunkFile = findChunkForWord(wordform, state.manifest);
    if (!chunkFile) return null;

    const chunkData = await loadChunk(chunkFile);
    if (chunkData[wordform]) return chunkData[wordform];

    const wordNorm = normalizeWord(wordform);
    for (const [key, entry] of Object.entries(chunkData)) {
        if (normalizeWord(key) === wordNorm) return entry;
    }
    return null;
}

function getBrowseEntry(wordform) {
    return state.browse?.[wordform] || { lemma: '', relation: '', pos: '', count: 0 };
}

async function loadLemmaIndex() {
    if (state.lemmaIndex) return;
    const response = await fetch(`${CONFIG.DATA_PREFIX}/lemma_index.json`);
    if (!response.ok) throw new Error('Не удалось загрузить индекс лемм');
    state.lemmaIndex = await response.json();
}

function lemmaLocalUrl(lemma) {
    return `index.html?lemma=${encodeURIComponent(lemma)}`;
}

function dictLemmaUrl(lemma) {
    return `${CONFIG.DICT_BASE}#word=${encodeURIComponent(lemma)}`;
}

function sourcePageUrl(wordform, lemma) {
    const params = new URLSearchParams({ form: wordform });
    if (lemma) params.set('lemma', lemma);
    return `source/?${params.toString()}`;
}

function renderSourceLink(sourceName, wordform, lemma) {
    if (!sourceName) return '—';
    const href = sourcePageUrl(wordform, lemma);
    return `<a href="${href}" class="source-link" title="Открыть происхождение">${escapeHtml(sourceName)}</a>`;
}

function renderLemmaCells(lemma) {
    if (!lemma) {
        return { lemma: '—', dict: '—' };
    }
    return {
        lemma:
            `<a href="${lemmaLocalUrl(lemma)}" class="lemma-local-link"` +
            ` title="Словоформы этой леммы">${escapeHtml(lemma)}</a>`,
        dict:
            `<a href="${dictLemmaUrl(lemma)}" class="lemma-dict-link" target="_blank" rel="noopener"` +
            ` title="Словарная статья на dev.avar.me">avar.me` +
            `<span class="lemma-link-icon" aria-hidden="true">↗</span></a>`
    };
}

function renderLemmaLink(lemma) {
    return renderLemmaCells(lemma).lemma;
}

function renderSuggestions(suggestions) {
    const el = document.getElementById('suggestions');
    if (!suggestions.length) {
        el.style.display = 'none';
        return;
    }
    el.innerHTML = suggestions.map(w => `
        <div class="suggestion-item" data-word="${escapeHtml(w)}">${escapeHtml(w)}</div>
    `).join('');
    el.style.display = 'block';
}

function renderWordformCard(data) {
    const entries = data.entries || [];
    let html = '<div class="word-card">';
    html += '<div class="word-header">';
    html += `<h2 class="word-title">${escapeHtml(data.wordform)}</h2>`;
    html += `<p class="entry-meta">${entries.length} ${entries.length === 1 ? 'запись' : 'записей'} в корпусе</p>`;
    const lemmas = [...new Set(entries.map(e => e.lemma).filter(Boolean))];
    if (lemmas.length) {
        const parts = lemmas.map(l => {
            const total = lemmaTotal(l);
            return `<a href="${lemmaLocalUrl(l)}" class="lemma-local-link">${escapeHtml(l)}</a>` +
                (total ? ` — ${total} ${pluralOccurrences(total)}` : '');
        });
        html += `<p class="entry-meta lemma-freq-note">Частотность леммы: ${parts.join('; ')}</p>`;
    }
    html += '</div>';

    html += '<div class="result-block">';
    html += '<div class="word-list-scroll"><table class="word-list"><thead><tr>';
    html += '<th>Словоформа</th><th>Лемма</th><th class="col-dict">avar.me</th>';
    html += '<th>Связь</th><th>Часть речи</th><th>Источник</th><th>×</th>';
    html += '</tr></thead><tbody>';

    for (const entry of entries) {
        const lemmaCells = renderLemmaCells(entry.lemma);
        html += `<tr class="word-list-row" tabindex="0">`;
        html += `<td class="word-list-word">${escapeHtml(data.wordform)}</td>`;
        html += `<td>${lemmaCells.lemma}</td>`;
        html += `<td class="col-dict">${lemmaCells.dict}</td>`;
        html += `<td>${entry.relation ? `<span class="relation-badge">${escapeHtml(entry.relation)}</span>` : '—'}</td>`;
        html += `<td>${entry.pos ? escapeHtml(entry.pos) : '—'}</td>`;
        html += `<td>${entry.source ? renderSourceLink(entry.source, data.wordform, entry.lemma) : '—'}</td>`;
        html += `<td class="count-badge">${entry.count}</td>`;
        html += '</tr>';
    }

    html += '</tbody></table></div></div></div>';
    return html;
}

function renderWordListTable(wordforms, options = {}) {
    const { caption = '' } = options;
    const rows = wordforms.map(wordform => {
        const b = getBrowseEntry(wordform);
        const lemmaCells = renderLemmaCells(b.lemma);
        const relation = b.relation
            ? `<span class="relation-badge">${escapeHtml(b.relation)}</span>`
            : '—';
        return `
            <tr class="word-list-row" data-word="${escapeHtml(wordform)}" tabindex="0" role="button">
                <td class="word-list-word">${escapeHtml(wordform)}</td>
                <td>${lemmaCells.lemma}</td>
                <td class="col-dict">${lemmaCells.dict}</td>
                <td>${relation}</td>
                <td>${b.pos ? escapeHtml(b.pos) : '—'}</td>
                <td class="count-badge">${b.count || ''}</td>
            </tr>
        `;
    }).join('');

    const cap = caption ? `<p class="word-list-caption">${escapeHtml(caption)}</p>` : '';
    return `
        ${cap}
        <div class="word-list-scroll">
            <table class="word-list">
                <thead>
                    <tr>
                        <th>Словоформа</th>
                        <th>Лемма</th>
                        <th class="col-dict">avar.me</th>
                        <th>Связь</th>
                        <th>Часть речи</th>
                        <th>×</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function bindWordListClicks(container) {
    container.querySelectorAll('.word-list-row[data-word]').forEach(row => {
        row.addEventListener('click', e => {
            if (e.target.closest('.lemma-local-link, .lemma-dict-link, .lemma-link')) return;
            const word = row.dataset.word;
            document.getElementById('searchInput').value = word;
            loadAndDisplayWordform(word);
        });
        row.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') {
                if (e.target.closest('.lemma-local-link, .lemma-dict-link, .lemma-link')) return;
                e.preventDefault();
                row.click();
            }
        });
    });
}

function syncUrl(params) {
    const url = new URL(window.location);
    url.search = '';
    for (const [key, value] of Object.entries(params)) {
        if (value) url.searchParams.set(key, value);
    }
    history.pushState(null, '', url);
}

function clearViewState() {
    state.activeLemma = null;
    state.activeFilter = null;
}

function showLemmaBanner(lemma, count) {
    const statsEl = document.getElementById('searchStats');
    const total = lemmaTotal(lemma);
    const freq = total ? ` · ${total} ${pluralOccurrences(total)}` : '';
    statsEl.innerHTML = `
        Лемма: <strong>${escapeHtml(lemma)}</strong>
        · ${count} ${count === 1 ? 'словоформа' : count < 5 ? 'словоформы' : 'словоформ'}${freq}
        · <a href="index.html">сбросить</a>`;
}

function displayLemmaForms(lemma, { updateUrl = true } = {}) {
    const wordforms = state.lemmaIndex?.[lemma] || [];
    const resultsEl = document.getElementById('results');
    const randomSection = document.getElementById('randomWordsSection');
    const suggestionsEl = document.getElementById('suggestions');

    state.activeLemma = lemma;
    state.activeFilter = null;
    suggestionsEl.style.display = 'none';

    if (!wordforms.length) {
        resultsEl.innerHTML = `
            <div class="no-results">
                <p>Нет словоформ для леммы «${escapeHtml(lemma)}»</p>
            </div>`;
        resultsEl.style.display = 'block';
        if (randomSection) randomSection.style.display = 'none';
        showLemmaBanner(lemma, 0);
        if (updateUrl) syncUrl({ lemma });
        return;
    }

    const caption = `Словоформы леммы «${lemma}» — ${wordforms.length}`;
    resultsEl.innerHTML = renderWordListTable(wordforms, { caption });
    resultsEl.style.display = 'block';
    bindWordListClicks(resultsEl);
    if (randomSection) randomSection.style.display = 'none';
    showLemmaBanner(lemma, wordforms.length);
    if (updateUrl) syncUrl({ lemma });
}

async function loadAndDisplayLemmaForms(lemma) {
    showLoading(true);
    try {
        await loadLemmaIndex();
        showLoading(false);
        displayLemmaForms(lemma);
    } catch (err) {
        showLoading(false);
        showError(err.message || 'Ошибка загрузки леммы');
    }
}

function renderHomeSamples() {
    const container = document.getElementById('homeSamples');
    const captionEl = document.getElementById('homeSamplesCaption');
    if (!container || !state.wordformsIndex?.length) return;

    let pool = state.wordformsIndex;
    let sampleSize = CONFIG.HOME_SAMPLES;
    let caption = `${CONFIG.HOME_SAMPLES} случайных словоформ`;

    if (state.activeFilter && state.gapWordforms?.length) {
        pool = state.gapWordforms;
        sampleSize = CONFIG.GAP_SAMPLES;
        const meta = state.gapFilterManifest?.filters?.[state.activeFilter];
        const label = meta?.label || state.activeFilter;
        const total = state.gapWordforms.length;
        caption = `${Math.min(sampleSize, total)} из ${total}: ${label}`;
    }

    const picks = pickRandom(pool, sampleSize);

    if (captionEl) captionEl.textContent = caption;
    container.innerHTML = renderWordListTable(picks);
    bindWordListClicks(container);
}

function pickRandom(items, count) {
    const picks = [];
    const used = new Set();
    const n = Math.min(count, items.length);
    while (picks.length < n) {
        const idx = Math.floor(Math.random() * items.length);
        if (used.has(idx)) continue;
        used.add(idx);
        picks.push(items[idx]);
    }
    return picks;
}

async function loadGapFilter(filterId) {
    if (!state.gapFilterManifest) {
        const response = await fetch(`${CONFIG.GAPS_PREFIX}/manifest.json`);
        if (!response.ok) throw new Error('Не удалось загрузить фильтры пробелов');
        state.gapFilterManifest = await response.json();
    }

    const resolvedId = state.gapFilterManifest.legacy_filters?.[filterId] || filterId;
    const meta = state.gapFilterManifest.filters?.[resolvedId];
    if (!meta) throw new Error(`Неизвестный фильтр: ${filterId}`);

    const response = await fetch(`${CONFIG.GAPS_PREFIX}/${meta.file}`);
    if (!response.ok) throw new Error(`Не удалось загрузить ${meta.file}`);
    const text = await response.text();
    state.gapWordforms = text.split('\n').filter(Boolean);
    state.activeFilter = resolvedId;
}

function showFilterBanner(filterId) {
    const resolvedId = state.gapFilterManifest?.legacy_filters?.[filterId] || filterId;
    const meta = state.gapFilterManifest?.filters?.[resolvedId];
    if (!meta) return;
    const statsEl = document.getElementById('searchStats');
    const mentionHint = meta.mention_count
        ? ` · ${meta.mention_count.toLocaleString('ru-RU')} упоминаний`
        : '';
    statsEl.innerHTML = `
        Фильтр: <strong>${escapeHtml(meta.label)}</strong>
        · ${meta.count.toLocaleString('ru-RU')} словоформ${mentionHint}
        · <a href="index.html">сбросить</a>
        · <a href="index.html?filter=${encodeURIComponent(resolvedId)}">другие 30</a>`;
}

function renderPrefixList(query, wordforms) {
    const resultsEl = document.getElementById('results');
    const randomSection = document.getElementById('randomWordsSection');
    const caption = wordforms.length >= CONFIG.MAX_PREFIX_LIST
        ? `Словоформы на «${query}» (первые ${CONFIG.MAX_PREFIX_LIST})`
        : `Словоформы на «${query}» — ${wordforms.length}`;

    resultsEl.innerHTML = renderWordListTable(wordforms, { caption });
    resultsEl.style.display = 'block';
    bindWordListClicks(resultsEl);
    if (randomSection) randomSection.style.display = 'none';
    updateSearchStats(query, wordforms.length);
}

function showLoading(show = true) {
    document.getElementById('loading').style.display = show ? 'flex' : 'none';
    if (show) document.getElementById('results').style.display = 'none';
}

function showError(message) {
    const errorEl = document.getElementById('error');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
    setTimeout(() => { errorEl.style.display = 'none'; }, 5000);
}

function updateSearchStats(query, count) {
    const statsEl = document.getElementById('searchStats');
    if (!query) {
        statsEl.textContent = '';
        return;
    }
    statsEl.textContent = count ? `Найдено: ${count}` : 'Ничего не найдено';
}

async function loadAndDisplayWordform(wordform) {
    const resultsEl = document.getElementById('results');
    const randomSection = document.getElementById('randomWordsSection');
    const suggestionsEl = document.getElementById('suggestions');

    suggestionsEl.style.display = 'none';
    showLoading(true);

    try {
        const data = await getWordformData(wordform);
        showLoading(false);

        if (!data) {
            resultsEl.innerHTML = `
                <div class="no-results">
                    <p>«${escapeHtml(wordform)}» не найдено</p>
                    <p class="no-results-hint">Попробуйте другой префикс или проверьте написание</p>
                </div>`;
            resultsEl.style.display = 'block';
            if (randomSection) randomSection.style.display = 'none';
            updateSearchStats(wordform, 0);
            return;
        }

        resultsEl.innerHTML = renderWordformCard(data);
        resultsEl.style.display = 'block';
        bindWordListClicks(resultsEl);
        if (randomSection) randomSection.style.display = 'none';
        syncUrl({ q: wordform });
        updateSearchStats(wordform, 1);
    } catch (err) {
        showLoading(false);
        showError(err.message || 'Ошибка загрузки');
    }
}

function handleSearchInput(query) {
    const q = query.trim();
    state.currentQuery = q;
    const clearBtn = document.getElementById('clearBtn');
    clearBtn.style.display = q ? 'block' : 'none';

    const resultsEl = document.getElementById('results');
    const randomSection = document.getElementById('randomWordsSection');

    if (!q) {
        document.getElementById('suggestions').style.display = 'none';
        resultsEl.style.display = 'none';
        resultsEl.innerHTML = '';
        clearViewState();
        syncUrl({});
        if (randomSection) randomSection.style.display = 'block';
        renderHomeSamples();
        updateSearchStats('', 0);
        return;
    }

    clearViewState();

    const suggestions = binarySearchPrefix(state.wordformsIndex, q);
    renderSuggestions(suggestions);

    const exact = suggestions.find(w => normalizeWord(w) === normalizeWord(q));
    if (exact) {
        loadAndDisplayWordform(exact);
        return;
    }

    if (q.length >= CONFIG.MIN_PREFIX_LIST) {
        const list = collectPrefixList(state.wordformsIndex, q, CONFIG.MAX_PREFIX_LIST);
        if (list.length) {
            renderPrefixList(q, list);
            return;
        }
    }

    resultsEl.innerHTML = `
        <div class="no-results">
            <p>Нет словоформ на «${escapeHtml(q)}»</p>
            <p class="no-results-hint">Выберите подсказку или введите больше букв</p>
        </div>`;
    resultsEl.style.display = 'block';
    if (randomSection) randomSection.style.display = 'none';
    updateSearchStats(q, 0);
}

const debouncedSearch = debounce(handleSearchInput, CONFIG.DEBOUNCE_DELAY);

async function init() {
    showLoading(true);
    try {
        const params = new URLSearchParams(window.location.search);
        const filter = params.get('filter');
        const lemma = params.get('lemma');
        const q = params.get('q');

        await Promise.all([loadWordformsIndex(), loadBrowse(), loadManifest(), loadLemmaFreq()]);

        showLoading(false);

        if (lemma) {
            await loadLemmaIndex();
            displayLemmaForms(lemma, { updateUrl: false });
        } else if (filter) {
            await loadGapFilter(filter);
            showFilterBanner(filter);
            renderHomeSamples();
        } else {
            renderHomeSamples();
        }

        if (q && !lemma) {
            document.getElementById('searchInput').value = q;
            handleSearchInput(q);
        }
    } catch (err) {
        showLoading(false);
        showError(err.message || 'Ошибка инициализации');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('searchInput');
    const clearBtn = document.getElementById('clearBtn');
    const suggestionsEl = document.getElementById('suggestions');

    searchInput.addEventListener('input', e => debouncedSearch(e.target.value));
    searchInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            debouncedSearch.cancel?.();
            handleSearchInput(searchInput.value);
        }
        if (e.key === 'Escape') {
            searchInput.value = '';
            handleSearchInput('');
        }
    });

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        handleSearchInput('');
        searchInput.focus();
    });

    suggestionsEl.addEventListener('click', e => {
        const item = e.target.closest('.suggestion-item');
        if (!item) return;
        const word = item.dataset.word;
        searchInput.value = word;
        loadAndDisplayWordform(word);
    });

    document.addEventListener('click', e => {
        if (!e.target.closest('.search-container')) {
            suggestionsEl.style.display = 'none';
        }
    });

    document.addEventListener('click', e => {
        const link = e.target.closest('.lemma-local-link');
        if (!link) return;
        e.preventDefault();
        const href = link.getAttribute('href') || '';
        const lemma = new URL(href, window.location.href).searchParams.get('lemma');
        if (!lemma) return;
        document.getElementById('searchInput').value = '';
        document.getElementById('clearBtn').style.display = 'none';
        loadAndDisplayLemmaForms(lemma);
    });

    window.addEventListener('popstate', () => {
        const params = new URLSearchParams(window.location.search);
        const lemma = params.get('lemma');
        const filter = params.get('filter');
        const q = params.get('q');
        const searchInput = document.getElementById('searchInput');

        if (lemma) {
            searchInput.value = '';
            loadAndDisplayLemmaForms(lemma);
            return;
        }

        clearViewState();
        if (filter) {
            loadGapFilter(filter).then(() => {
                showFilterBanner(filter);
                renderHomeSamples();
            });
            return;
        }

        searchInput.value = q || '';
        handleSearchInput(searchInput.value);
    });

    init();
});

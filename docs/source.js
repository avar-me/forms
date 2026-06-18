/**
 * Source provenance page — forms.avar.me/source/?form=…
 */

const CONFIG = {
    DATA_PREFIX: '../data/sources',
    DICT_BASE: 'https://dev.avar.me/',
    CHUNK_CACHE_SIZE: 20
};

const SUBSOURCE_LABELS = {
    headword: 'Заголовок статьи',
    explicit_relation: 'Явная связь (from)',
    forms: 'Поле forms[]',
    gender_forms: 'Родовые формы',
    examples: 'Пример av',
    wordforms: 'Словоформа из источника'
};

const SUBSOURCE_ORDER = ['headword', 'explicit_relation', 'forms', 'gender_forms', 'examples', 'wordforms'];

const state = {
    manifest: null,
    chunkCache: new Map()
};

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

function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name) || '';
}

function dictLemmaUrl(lemma) {
    return `${CONFIG.DICT_BASE}#word=${encodeURIComponent(lemma)}`;
}

function searchUrl(wordform) {
    return `../index.html?q=${encodeURIComponent(wordform)}`;
}

async function loadManifest() {
    const response = await fetch(`${CONFIG.DATA_PREFIX}/manifest.json`);
    if (!response.ok) throw new Error('Не удалось загрузить manifest.json');
    state.manifest = await response.json();
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

async function loadChunk(chunkFile) {
    if (state.chunkCache.has(chunkFile)) {
        return state.chunkCache.get(chunkFile);
    }
    const response = await fetch(`${CONFIG.DATA_PREFIX}/chunks/${chunkFile}`);
    if (!response.ok) throw new Error(`Не удалось загрузить ${chunkFile}`);
    const data = await response.json();
    if (state.chunkCache.size >= CONFIG.CHUNK_CACHE_SIZE) {
        const firstKey = state.chunkCache.keys().next().value;
        state.chunkCache.delete(firstKey);
    }
    state.chunkCache.set(chunkFile, data);
    return data;
}

async function getProvenance(wordform) {
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

function renderEntryLink(entry) {
    if (!entry) return '';
    return `<a href="${dictLemmaUrl(entry)}" class="lemma-dict-link" target="_blank" rel="noopener">${escapeHtml(entry)}<span class="lemma-link-icon" aria-hidden="true">↗</span></a>`;
}

function renderFormsList(forms) {
    if (!forms?.length) return '';
    const items = forms.map(form => `<li><code>${escapeHtml(form)}</code></li>`).join('');
    return `<div class="prov-field"><span class="prov-label">Формы статьи</span><ul class="prov-forms">${items}</ul></div>`;
}

function renderMention(mention) {
    const subsource = mention.subsource || 'unknown';
    const parts = [];
    parts.push(`<div class="prov-mention-head"><span class="prov-badge">${escapeHtml(SUBSOURCE_LABELS[subsource] || subsource)}</span></div>`);

    if (mention.entry) {
        parts.push(`<div class="prov-field"><span class="prov-label">Статья словаря</span> ${renderEntryLink(mention.entry)}</div>`);
    }
    if (mention.from_lemma) {
        parts.push(`<div class="prov-field"><span class="prov-label">От леммы</span> ${renderEntryLink(mention.from_lemma)}</div>`);
    }
    if (mention.sense) {
        parts.push(`<div class="prov-field"><span class="prov-label">Значение</span> <span class="prov-sense">${escapeHtml(mention.sense)}</span></div>`);
    }
    if (mention.av) {
        parts.push(`<blockquote class="prov-av">${escapeHtml(mention.av)}</blockquote>`);
    }
    if (mention.ru) {
        parts.push(`<p class="prov-ru">${escapeHtml(mention.ru)}</p>`);
    }
    parts.push(renderFormsList(mention.entry_forms));

    const meta = [];
    if (mention.lemma && mention.lemma !== mention.entry) {
        meta.push(`<span>Лемма: <strong>${escapeHtml(mention.lemma)}</strong></span>`);
    }
    if (mention.relation) {
        meta.push(`<span>Связь: <strong>${escapeHtml(mention.relation)}</strong></span>`);
    }
    if (mention.pos || mention.entry_pos) {
        meta.push(`<span>Часть речи: <strong>${escapeHtml(mention.pos || mention.entry_pos)}</strong></span>`);
    }
    if (mention.confidence && mention.confidence !== 'high') {
        meta.push(`<span>Уверенность: <strong>${escapeHtml(mention.confidence)}</strong></span>`);
    }
    if (meta.length) {
        parts.push(`<div class="prov-meta">${meta.join(' · ')}</div>`);
    }

    return `<article class="prov-mention">${parts.join('')}</article>`;
}

function groupMentions(mentions) {
    const groups = new Map();
    for (const mention of mentions) {
        const key = mention.subsource || 'unknown';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(mention);
    }
    return SUBSOURCE_ORDER
        .filter(key => groups.has(key))
        .map(key => ({ subsource: key, mentions: groups.get(key) }));
}

function filterMentions(mentions, lemmaFilter) {
    if (!lemmaFilter) return mentions;
    const norm = normalizeWord(lemmaFilter);
    return mentions.filter(mention => {
        const lemma = mention.lemma || mention.entry || '';
        return normalizeWord(lemma) === norm;
    });
}

function renderSourceBlock(sourceData, lemmaFilter) {
    const mentions = filterMentions(sourceData.mentions || [], lemmaFilter);
    if (!mentions.length) return '';

    const groups = groupMentions(mentions);
    let html = `<section class="prov-source">`;
    html += `<h2 class="prov-source-title">${escapeHtml(sourceData.name || sourceData.id)}</h2>`;
    html += `<p class="prov-source-meta">${mentions.length} ${mentions.length === 1 ? 'упоминание' : 'упоминаний'} в этом источнике</p>`;

    for (const group of groups) {
        html += `<div class="prov-group">`;
        html += `<h3 class="prov-group-title">${escapeHtml(SUBSOURCE_LABELS[group.subsource] || group.subsource)}</h3>`;
        html += group.mentions.map(renderMention).join('');
        html += `</div>`;
    }

    html += `</section>`;
    return html;
}

function renderPage(wordform, data, lemmaFilter) {
    const sources = Object.values(data.sources || {});
    const blocks = sources.map(source => renderSourceBlock(source, lemmaFilter)).filter(Boolean);

    let html = `<div class="source-card">`;
    html += `<div class="source-header">`;
    html += `<p class="source-back"><a href="${searchUrl(wordform)}" class="source-back-link">← К поиску: ${escapeHtml(wordform)}</a></p>`;
    html += `<h2 class="word-title">${escapeHtml(wordform)}</h2>`;
    if (lemmaFilter) {
        html += `<p class="source-filter-note">Показаны упоминания для леммы <strong>${escapeHtml(lemmaFilter)}</strong> · <a href="?form=${encodeURIComponent(wordform)}">показать все</a></p>`;
    }
    html += `</div>`;

    if (!blocks.length) {
        html += `<p class="source-empty">Происхождение для этой словоформы не найдено.</p>`;
    } else {
        html += blocks.join('');
    }

    html += `</div>`;
    return html;
}

function showError(message) {
    document.getElementById('sourceLoading').style.display = 'none';
    document.getElementById('sourceContent').style.display = 'none';
    const errorEl = document.getElementById('sourceError');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
}

async function initSourcePage() {
    const wordform = getQueryParam('form');
    const lemmaFilter = getQueryParam('lemma');

    if (!wordform) {
        showError('Укажите словоформу в параметре ?form=');
        return;
    }

    document.title = `${wordform} — источник — avar.me`;

    try {
        await loadManifest();
        const data = await getProvenance(wordform);
        if (!data) {
            showError(`Происхождение для «${wordform}» не найдено.`);
            return;
        }

        document.getElementById('sourceLoading').style.display = 'none';
        document.getElementById('sourceError').style.display = 'none';
        const content = document.getElementById('sourceContent');
        content.innerHTML = renderPage(wordform, data, lemmaFilter);
        content.style.display = 'block';
    } catch (error) {
        console.error(error);
        showError(error.message || 'Ошибка загрузки');
    }
}

document.addEventListener('DOMContentLoaded', initSourcePage);

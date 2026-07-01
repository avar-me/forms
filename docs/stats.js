/**
 * Statistics page — charts and numbers
 */

const GAP_LINK_BASE = 'index.html?filter=';

const GAP_LABELS = {
    needs_work: {
        label: 'Нужна ручная работа',
        description: 'Есть упоминания без уверенного маппинга',
    },
    fully_unmapped: {
        label: 'Без маппинга',
        description: 'Нет ни одной записи с найденной леммой',
    },
    partial: {
        label: 'Частичный маппинг',
        description: 'Есть и ясные записи, и пробелы в других упоминаниях',
    },
    homograph: {
        label: 'Омонимы',
        description: 'Несколько лемм для одной словоформы — обычно норма',
    },
    strange: {
        label: 'Аномалии',
        description: 'Подозрительные записи без ясного контекста',
    },
    foreign_words: {
        label: 'Иностранные слова',
        description: 'Латинские слова/аббревиатуры с аварскими окончаниями: COVID, Telegram, IT и т.д.',
    },
};

const GAP_FILTER_ORDER = ['needs_work', 'fully_unmapped', 'partial', 'homograph', 'strange', 'foreign_words'];

const CHART_COLORS = [
    '#5e7a6f', '#1a5f8a', '#6b9080', '#4a6670', '#7a9e8e',
    '#3d6b5e', '#047857', '#5c7a6b', '#2d6a6a', '#0f766e'
];

const chartDefaults = {
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
        legend: {
            labels: {
                font: { family: '"Onest", system-ui, sans-serif', size: 12 },
                color: '#5a6570'
            }
        }
    }
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(n) {
    const value = Number(n);
    if (!Number.isFinite(value)) {
        return '0';
    }
    return new Intl.NumberFormat('ru-RU').format(value);
}

function pct(part, total) {
    const p = Number(part);
    const t = Number(total);
    if (!Number.isFinite(p) || !Number.isFinite(t) || t <= 0) {
        return '0%';
    }
    return `${((p / t) * 100).toFixed(1)}%`;
}

function gapLink(filterId) {
    return `${GAP_LINK_BASE}${encodeURIComponent(filterId)}`;
}

function renderStatCards(stats, meta) {
    const el = document.getElementById('statCards');
    const cards = [
        { value: formatNumber(meta.total_wordforms || stats.total_aggregated_records), label: 'Уникальных словоформ' },
        { value: formatNumber(stats.total_raw_records), label: 'Всего упоминаний' },
        { value: formatNumber(stats.total_aggregated_records), label: 'Агрегированных записей' },
        { value: formatNumber(Object.keys(stats.per_source_raw || {}).length), label: 'Источников' },
    ];
    el.innerHTML = cards.map(c => `
        <div class="stat-card">
            <div class="stat-card-value">${escapeHtml(String(c.value))}</div>
            <div class="stat-card-label">${escapeHtml(c.label)}</div>
        </div>
    `).join('');
}

function makeDoughnut(canvasId, labels, data, title) {
    const ctx = document.getElementById(canvasId);
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: CHART_COLORS.slice(0, labels.length),
                borderWidth: 2,
                borderColor: '#ffffff'
            }]
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                title: {
                    display: !!title,
                    text: title,
                    font: { family: '"Literata", Georgia, serif', size: 14, weight: '600' },
                    color: '#1c2229',
                    padding: { bottom: 12 }
                }
            }
        }
    });
}

function makeHorizontalBar(canvasId, labels, data, title) {
    const ctx = document.getElementById(canvasId);
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: CHART_COLORS[0],
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: {
                    display: !!title,
                    text: title,
                    font: { family: '"Literata", Georgia, serif', size: 14, weight: '600' },
                    color: '#1c2229'
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(28,34,41,0.06)' },
                    ticks: { font: { family: '"Onest", sans-serif' }, color: '#5a6570' }
                },
                y: {
                    grid: { display: false },
                    ticks: { font: { family: '"Onest", sans-serif', size: 11 }, color: '#1c2229' }
                }
            }
        }
    });
}

function renderSourceStatsTable(stats) {
    const el = document.getElementById('sourceStatsTable');
    const rows = stats.source_stats || [];
    if (!rows.length) { el.innerHTML = '<p>Нет данных</p>'; return; }
    const header = `
        <table class="data-table">
            <thead><tr>
                <th>Источник</th>
                <th>Уникальных словоформ</th>
                <th>Всего вхождений</th>
                <th>Только в этом источнике</th>
            </tr></thead>
            <tbody>
    `;
    const body = rows.map(r => `
        <tr>
            <td>${escapeHtml(r.source)}</td>
            <td class="num">${formatNumber(r.unique)}</td>
            <td class="num">${formatNumber(r.total)}</td>
            <td class="num">${formatNumber(r.exclusive)}</td>
        </tr>
    `).join('');
    el.innerHTML = header + body + '</tbody></table>';
}

function renderFreqDistTable(stats) {
    const el = document.getElementById('freqDistTable');
    const rows = stats.freq_distribution || [];
    if (!rows.length) { el.innerHTML = '<p>Нет данных</p>'; return; }
    const maxVal = Math.max(...rows.map(r => r.wordforms), 1);
    const header = `
        <table class="data-table">
            <thead><tr>
                <th>Раз встречается</th>
                <th>Словоформ</th>
                <th></th>
            </tr></thead>
            <tbody>
    `;
    const body = rows.map(r => {
        const barW = Math.round((r.wordforms / maxVal) * 100);
        return `
            <tr>
                <td>${escapeHtml(r.label)}</td>
                <td class="num">${formatNumber(r.wordforms)}</td>
                <td class="bar-cell"><div class="bar-fill" style="width:${barW}%"></div></td>
            </tr>
        `;
    }).join('');
    el.innerHTML = header + body + '</tbody></table>';
}

function renderCoverageDetails(stats, gapManifest) {
    const totalMentions = stats.total_raw_records || 1;
    const manifestFilters = gapManifest?.filters || {};

    const items = GAP_FILTER_ORDER.map((filterId) => {
        const fromManifest = manifestFilters[filterId];
        const labels = GAP_LABELS[filterId] || { label: filterId, description: '' };
        const wordforms = fromManifest?.count ?? stats.gap_wordforms?.[filterId] ?? 0;
        const mentions = fromManifest?.mention_count ?? stats.gap_mentions?.[filterId] ?? 0;
        const meta = {
            label: fromManifest?.label || labels.label,
            description: fromManifest?.description || labels.description,
        };
        return { filterId, meta, wordforms, mentions };
    });

    document.getElementById('coverageDetails').innerHTML = items.map(({ filterId, meta, wordforms, mentions }) => {
        const mentionPct = pct(mentions, totalMentions);
        const inner = `
            <strong>${escapeHtml(formatNumber(wordforms))}</strong>
            <span>${escapeHtml(meta.label)}</span>
            <span class="coverage-item-meta">${escapeHtml(meta.description)}</span>
            <span class="coverage-link-hint">${escapeHtml(formatNumber(mentions))} упоминаний (${mentionPct}) · показать 30 случайных</span>
        `;
        if (wordforms > 0) {
            return `<a class="coverage-item coverage-item-link" href="${gapLink(filterId)}">${inner}</a>`;
        }
        return `<div class="coverage-item">${inner}</div>`;
    }).join('');
}

async function initStats() {
    const loading = document.getElementById('statsLoading');
    const content = document.getElementById('statsContent');
    const errorEl = document.getElementById('statsError');

    try {
        const [statsRes, metaRes, gapsRes] = await Promise.all([
            fetch('data/stats.json'),
            fetch('data/site-meta.json'),
            fetch('data/gaps/manifest.json')
        ]);

        if (!statsRes.ok) throw new Error('Не удалось загрузить stats.json');
        const stats = await statsRes.json();
        const meta = metaRes.ok ? await metaRes.json() : {};
        const gapManifest = gapsRes.ok ? await gapsRes.json() : null;

        loading.style.display = 'none';
        content.style.display = 'block';

        renderStatCards(stats, meta);

        const subLabels = Object.keys(stats.per_subsource_raw || {});
        const subData = Object.values(stats.per_subsource_raw || {});
        makeDoughnut('chartSubsources', subLabels, subData, 'По подисточникам');

        const needsWorkMentions = stats.needs_work_mentions
            ?? stats.gap_mentions?.needs_work
            ?? 0;
        const withMapping = stats.total_raw_records - needsWorkMentions;
        makeDoughnut(
            'chartCoverage',
            ['С маппингом', 'Нужна работа'],
            [withMapping, needsWorkMentions],
            'Покрытие маппингом'
        );

        const topLemmas = (stats.top_lemmas || []).slice(0, 12);
        makeHorizontalBar(
            'chartTopLemmas',
            topLemmas.map(([w]) => w),
            topLemmas.map(([, c]) => c),
            'Топ-12 лемм по числу словоформ'
        );

        const topRelations = (stats.top_relations || []).slice(0, 10);
        makeHorizontalBar(
            'chartRelations',
            topRelations.map(([r]) => r),
            topRelations.map(([, c]) => c),
            'Типы грамматических связей'
        );

        const topWordforms = (stats.top_wordforms || []).slice(0, 12);
        makeHorizontalBar(
            'chartTopWordforms',
            topWordforms.map(([w]) => w),
            topWordforms.map(([, c]) => c),
            'Топ-12 словоформ по частоте'
        );

        renderSourceStatsTable(stats);
        renderFreqDistTable(stats);
        renderCoverageDetails(stats, gapManifest);
    } catch (err) {
        loading.style.display = 'none';
        errorEl.textContent = err.message || 'Ошибка загрузки';
        errorEl.style.display = 'block';
    }
}

document.addEventListener('DOMContentLoaded', initStats);

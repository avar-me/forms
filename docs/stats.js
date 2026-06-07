/**
 * Statistics page — charts and numbers
 */

const GAP_LINK_BASE = 'index.html?filter=';

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
    return new Intl.NumberFormat('ru-RU').format(n);
}

function pct(part, total) {
    if (!total) return '0%';
    return `${((part / total) * 100).toFixed(1)}%`;
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

function renderCoverageDetails(stats, gapManifest) {
    const totalMentions = stats.total_raw_records || 1;
    const filters = gapManifest?.filters || {};
    const filterOrder = ['needs_work', 'fully_unmapped', 'partial', 'homograph', 'strange'];

    const items = filterOrder
        .map((filterId) => {
            const meta = filters[filterId];
            if (!meta) return null;
            const wordforms = meta.count || 0;
            const mentions = meta.mention_count ?? stats.gap_mentions?.[filterId] ?? 0;
            return { filterId, meta, wordforms, mentions };
        })
        .filter(Boolean);

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

        renderCoverageDetails(stats, gapManifest);
    } catch (err) {
        loading.style.display = 'none';
        errorEl.textContent = err.message || 'Ошибка загрузки';
        errorEl.style.display = 'block';
    }
}

document.addEventListener('DOMContentLoaded', initStats);

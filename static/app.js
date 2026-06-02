let activeSession = null;
let currentPage = 1;
let totalPages = 1;
let totalPosts = 0;
let searchTimer = null;
let wpConfigured = false;

// --- Session Management ---
async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        const el = document.getElementById('sessionList');

        if (!sessions.length) {
            el.innerHTML = '<div class="text-center py-4 text-muted small">Belum ada sesi scrap</div>';
            return;
        }

        el.innerHTML = sessions.map(s => `
            <div class="session-item position-relative${activeSession === s.session_id ? ' active' : ''}"
                 onclick="switchSession('${s.session_id}')">
                <button class="btn btn-sm text-danger position-absolute top-0 end-0 p-1"
                        onclick="event.stopPropagation(); deleteSession('${s.session_id}')"
                        title="Hapus sesi ini">
                    <i class="bi bi-trash"></i>
                </button>
                <div class="fw-semibold small">${s.date}</div>
                <div class="d-flex justify-content-between small">
                    <span>${s.total_posts} post</span>
                    <span>${s.data_from || '?'} &rarr; ${s.data_to || '?'}</span>
                </div>
                <small>${s.total_media} file media</small>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to load sessions:', e);
    }
}

async function deleteSession(sessionId) {
    if (!confirm(`Hapus sesi ${sessionId} beserta semua data dan media-nya?`)) return;

    try {
        const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        const data = await res.json();

        if (data.error) {
            alert('Gagal menghapus: ' + data.error);
            return;
        }

        if (activeSession === sessionId) {
            activeSession = null;
            currentPage = 1;
            document.getElementById('activeSessionLabel').textContent = 'Pilih sesi scrap';
            document.getElementById('postCount').textContent = '0';
            document.getElementById('postsBody').innerHTML =
                '<tr><td colspan="9" class="text-center py-5 text-muted">Pilih sesi di sebelah kiri</td></tr>';
            document.getElementById('pagination').innerHTML = '';
            document.getElementById('paginationInfo').textContent = '0 hasil';
            document.getElementById('statsCard').classList.add('d-none');
            document.getElementById('analyticsCard').classList.add('d-none');
        }

        loadSessions();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function switchSession(sessionId) {
    activeSession = sessionId;
    currentPage = 1;
    document.getElementById('activeSessionLabel').textContent = 'Sesi: ' + sessionId;

    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset?.sessionId === sessionId);
    });

    // Refresh session list highlight
    loadSessions();

    await loadStats(sessionId);
    await loadAnalytics(sessionId);
    await loadPosts();
}

// --- Posts ---
async function loadPosts() {
    if (!activeSession) return;

    const search = document.getElementById('searchInput').value;
    const sortVal = document.getElementById('sortSelect').value;
    const [sort_by, sort_order] = sortVal.split('_');

    try {
        const params = new URLSearchParams({
            page: currentPage,
            per_page: 30,
            search,
            sort_by,
            sort_order,
        });
        const res = await fetch(`/api/sessions/${activeSession}/posts?${params}`);
        const data = await res.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        totalPosts = data.total;
        totalPages = data.total_pages;
        document.getElementById('postCount').textContent = data.total;

        renderPosts(data.posts);
        renderPagination();
    } catch (e) {
        console.error('Failed to load posts:', e);
    }
}

function renderPosts(posts) {
    const tbody = document.getElementById('postsBody');
    if (!posts.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center py-5 text-muted">Tidak ada hasil</td></tr>';
        return;
    }

    const offset = (currentPage - 1) * 30;

    tbody.innerHTML = posts.map((p, i) => {
        const typeIcon = p.media_type === 'IMAGE' ? 'bi-file-image' :
                         p.media_type === 'VIDEO' ? 'bi-file-play' :
                         'bi-collection';
        const typeBadgeClass = p.media_type === 'IMAGE' ? 'bg-success' :
                               p.media_type === 'VIDEO' ? 'bg-danger' :
                               'bg-warning text-dark';
        const childrenCount = p.children ? p.children.length : 0;
        const thumbSrc = getThumbSrc(p);
        const hasMedia = thumbSrc || p.media_type === 'VIDEO';

        return `
        <tr>
            <td class="text-center"><input type="checkbox" class="post-checkbox" value="${p.id}" onchange="updateSelectedCount()"></td>
            <td class="small text-center fw-bold" style="cursor:pointer" onclick="openPostDetail('${p.id}')">${p.rank || '-'}</td>
            <td style="cursor:pointer" onclick="openPostDetail('${p.id}')">
                ${hasMedia ? `
                <div class="media-thumb-video">
                    <img src="${thumbSrc}" class="media-thumb"
                         onerror="this.parentElement.innerHTML='<span class=\\'text-muted small\\'>No img</span>'"
                         loading="lazy">
                    ${p.media_type === 'VIDEO' ? '<span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#fff;font-size:18px;text-shadow:0 1px 3px rgba(0,0,0,.5);pointer-events:none">&#9654;</span>' : ''}
                    ${childrenCount > 0 ? `<span style="position:absolute;bottom:2px;right:2px;background:rgba(0,0,0,.6);color:#fff;font-size:10px;padding:1px 5px;border-radius:3px">${childrenCount}</span>` : ''}
                </div>` : '<span class="text-muted small">-</span>'}
            </td>
            <td class="small" style="cursor:pointer" onclick="openPostDetail('${p.id}')">${formatDate(p.timestamp)}</td>
            <td style="cursor:pointer" onclick="openPostDetail('${p.id}')"><div class="caption-cell small">${escapeHtml((p.caption || '').substring(0, 150))}</div></td>
            <td style="cursor:pointer" onclick="openPostDetail('${p.id}')"><span class="badge ${typeBadgeClass} type-badge">${p.media_type === 'CAROUSEL_ALBUM' ? 'ALBUM' : p.media_type}</span></td>
            <td class="small text-center" style="cursor:pointer" onclick="openPostDetail('${p.id}')">
                ${p.sentiment === 'positive' ? '<span class="badge bg-success">Positif</span>' :
                  p.sentiment === 'negative' ? '<span class="badge bg-danger">Negatif</span>' :
                  '<span class="badge bg-secondary">Netral</span>'}
            </td>
            <td class="small text-center" style="cursor:pointer" onclick="openPostDetail('${p.id}')">${p.like_count || 0}</td>
            <td class="small text-center" style="cursor:pointer" onclick="openPostDetail('${p.id}')">${p.comments_count || 0}</td>
        </tr>`;
    }).join('');
}

function renderPagination() {
    const ul = document.getElementById('pagination');
    const info = document.getElementById('paginationInfo');

    if (totalPages <= 1) {
        ul.innerHTML = '';
        info.textContent = `${totalPosts} hasil`;
        return;
    }

    info.textContent = `Halaman ${currentPage}/${totalPages} (${totalPosts} hasil)`;

    let html = '';
    html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="goToPage(${currentPage - 1})">&laquo;</a></li>`;

    const start = Math.max(1, currentPage - 2);
    const end = Math.min(totalPages, currentPage + 2);
    for (let i = start; i <= end; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="goToPage(${i})">${i}</a></li>`;
    }

    html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="goToPage(${currentPage + 1})">&raquo;</a></li>`;

    ul.innerHTML = html;
}

function goToPage(page) {
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    loadPosts();
}

// --- Stats ---
async function loadStats(sessionId) {
    try {
        const res = await fetch(`/api/sessions/${sessionId}/stats`);
        const s = await res.json();
        if (s.error) return;

        const card = document.getElementById('statsCard');
        card.classList.remove('d-none');

        const typeLabels = { IMAGE: 'Foto', VIDEO: 'Video', CAROUSEL_ALBUM: 'Album' };
        let typeHtml = '';
        for (const [k, v] of Object.entries(s.type_counts)) {
            typeHtml += `<span class="badge bg-secondary me-1">${typeLabels[k] || k}: ${v}</span>`;
        }

        document.getElementById('statsContent').innerHTML = `
        <div class="row g-2 text-center">
            <div class="col-2">
                <div class="fw-bold fs-5">${s.total_posts}</div>
                <small class="text-muted">Total Post</small>
            </div>
            <div class="col-2">
                <div class="fw-bold fs-5">${s.total_likes.toLocaleString()}</div>
                <small class="text-muted">Total Likes</small>
            </div>
            <div class="col-2">
                <div class="fw-bold fs-5">${s.total_comments.toLocaleString()}</div>
                <small class="text-muted">Total Komentar</small>
            </div>
            <div class="col-2">
                <div class="fw-bold fs-5">${s.avg_likes}</div>
                <small class="text-muted">Rata &hearts;</small>
            </div>
            <div class="col-2">
                <div class="fw-bold fs-5">${s.date_range ? s.date_range.from + ' &rarr; ' + s.date_range.to : '-'}</div>
                <small class="text-muted">Rentang Tanggal</small>
            </div>
            <div class="col-2 text-end">${typeHtml}</div>
        </div>`;
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

// --- Analytics ---
let analyticsData = {};
let chartInstances = {};

async function loadAnalytics(sessionId) {
    analyticsData = {};
    destroyAllCharts();
    try {
        const [eng, sent, ins, bestTime, wc, cats] = await Promise.all([
            fetch(`/api/sessions/${sessionId}/analytics/engagement`).then(r => r.json()),
            fetch(`/api/sessions/${sessionId}/analytics/sentiment`).then(r => r.json()),
            fetch(`/api/sessions/${sessionId}/analytics/insights`).then(r => r.json()),
            fetch(`/api/sessions/${sessionId}/analytics/best-time`).then(r => r.json()),
            fetch(`/api/sessions/${sessionId}/analytics/wordcloud?max=80`).then(r => r.json()),
            fetch(`/api/sessions/${sessionId}/analytics/content-categories`).then(r => r.json()),
        ]);
        analyticsData = {
            engagement: eng, sentiment: sent, insights: ins,
            bestTime: bestTime, wordcloud: wc, categories: cats,
        };
        document.getElementById('analyticsCard').classList.remove('d-none');
        renderAnalyticsTab('engagement');
    } catch (e) {
        console.error('Failed to load analytics:', e);
    }
}

function switchAnalyticsTab(tab) {
    document.querySelectorAll('#analyticsCard .btn-group .btn').forEach(b => b.classList.remove('active'));
    const btnMap = {
        engagement: 'tabEngagement', sentiment: 'tabSentiment',
        insights: 'tabInsights', bestTime: 'tabBestTime',
        wordcloud: 'tabWordCloud', categories: 'tabCategories',
    };
    document.getElementById(btnMap[tab]).classList.add('active');
    renderAnalyticsTab(tab);
}

function renderAnalyticsTab(tab) {
    destroyAllCharts();
    if (tab === 'engagement') renderEngagement();
    else if (tab === 'sentiment') renderSentiment();
    else if (tab === 'insights') renderInsights();
    else if (tab === 'bestTime') renderBestTime();
    else if (tab === 'wordcloud') renderWordCloud();
    else if (tab === 'categories') renderCategories();
}

function destroyAllCharts() {
    Object.values(chartInstances).forEach(c => { if (c) c.destroy(); });
    chartInstances = {};
    document.querySelectorAll('#analyticsContent canvas').forEach(c => c.remove());
}

function renderEngagement() {
    const d = analyticsData.engagement;
    if (!d || d.error) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    const typeLabels = { IMAGE: 'Foto', VIDEO: 'Video', CAROUSEL_ALBUM: 'Album' };
    let typeHtml = '';
    for (const [k, v] of Object.entries(d.by_media_type || {})) {
        const pct = d.average_engagement_rate ? ((v.avg_engagement_rate / d.average_engagement_rate) * 100).toFixed(0) : 0;
        typeHtml += `<div class="mb-1"><span class="badge bg-secondary me-1">${typeLabels[k] || k}</span> <span class="fw-semibold">${v.avg_engagement_rate}%</span> <small class="text-muted">(${v.count} post, ${pct}% dari rata2)</small></div>`;
    }

    let topHtml = '';
    (d.top_5_posts || []).forEach((p, i) => {
        topHtml += `<div class="mb-1 small"><span class="badge bg-light text-dark me-1">#${i+1}</span> ${p.engagement_rate}% — ${escapeHtml((p.caption || '').substring(0, 60))}</div>`;
    });

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-7">
            <div class="row g-2 mb-2">
                <div class="col-4">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="fw-bold fs-5">${d.average_engagement_rate}%</div>
                        <small class="text-muted">Rata-rata ER</small>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="fw-bold fs-5">${(d.total_interactions || 0).toLocaleString()}</div>
                        <small class="text-muted">Total Interaksi</small>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 bg-light rounded text-center">
                        <div class="fw-bold fs-5">${(d.followers_count || 0).toLocaleString()}</div>
                        <small class="text-muted">Followers</small>
                    </div>
                </div>
            </div>
            <h6 class="mb-1">Per Tipe Media</h6>
            ${typeHtml || '<small class="text-muted">Tidak ada data</small>'}
            <hr class="my-1">
            <h6 class="mb-1">Top 5 Post</h6>
            ${topHtml || '<small class="text-muted">Tidak ada data</small>'}
        </div>
        <div class="col-md-5">
            <h6 class="mb-1">Tren Engagement Bulanan</h6>
            <canvas id="chartEngagementTrend" height="200"></canvas>
        </div>
    </div>`;

    const months = Object.keys(d.monthly_trend || {});
    const values = Object.values(d.monthly_trend || {});
    if (months.length) {
        const ctx = document.getElementById('chartEngagementTrend').getContext('2d');
        chartInstances.engagement = new Chart(ctx, {
            type: 'line',
            data: {
                labels: months,
                datasets: [{
                    label: 'Engagement Rate (%)',
                    data: values,
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13,110,253,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointBackgroundColor: '#0d6efd',
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { callback: v => v + '%' } }
                }
            }
        });
    }
}

function renderSentiment() {
    const d = analyticsData.sentiment;
    if (!d || d.error) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    const pct = d.distribution_pct || {};
    const dist = d.distribution || {};

    function bar(label, pctVal, count, color) {
        return `<div class="mb-1"><span class="badge bg-${color} me-1">${label}</span> ${pctVal}% <small class="text-muted">(${count} post)</small><div class="progress" style="height:20px"><div class="progress-bar bg-${color}" style="width:${pctVal}%"></div></div></div>`;
    }

    let topPosHtml = '';
    (d.top_positive || []).forEach(p => {
        topPosHtml += `<div class="mb-1 small">+${p.score} ${escapeHtml((p.caption || '').substring(0, 60))}</div>`;
    });

    let topNegHtml = '';
    (d.top_negative || []).forEach(p => {
        topNegHtml += `<div class="mb-1 small">${p.score} ${escapeHtml((p.caption || '').substring(0, 60))}</div>`;
    });

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-4">
            <h6 class="mb-1">Distribusi Sentimen</h6>
            <canvas id="chartSentiment" height="180"></canvas>
        </div>
        <div class="col-md-4">
            ${bar('Positif', pct.positive || 0, dist.positive || 0, 'success')}
            ${bar('Netral', pct.neutral || 0, dist.neutral || 0, 'secondary')}
            ${bar('Negatif', pct.negative || 0, dist.negative || 0, 'danger')}
            <div class="fw-bold fs-5 text-center mt-1">${d.total_posts || 0} <small class="text-muted fs-6">total post</small></div>
        </div>
        <div class="col-md-2">
            <h6 class="mb-1">Paling Positif</h6>
            ${topPosHtml || '<small class="text-muted">Tidak ada</small>'}
        </div>
        <div class="col-md-2">
            <h6 class="mb-1">Paling Negatif</h6>
            ${topNegHtml || '<small class="text-muted">Tidak ada</small>'}
        </div>
    </div>`;

    setTimeout(() => {
        const ctx = document.getElementById('chartSentiment');
        if (!ctx) return;
        chartInstances.sentiment = new Chart(ctx.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Positif', 'Netral', 'Negatif'],
                datasets: [{
                    data: [dist.positive || 0, dist.neutral || 0, dist.negative || 0],
                    backgroundColor: ['#198754', '#6c757d', '#dc3545'],
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 10 } } } }
            }
        });
    }, 100);
}

function renderInsights() {
    const d = analyticsData.insights;
    if (!d || d.error) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    let dayHtml = '';
    const dayOrder = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu'];
    const dayVals = d.day_breakdown || {};
    const maxDay = Math.max(...Object.values(dayVals).map(v => v.avg_interactions || 0), 1);
    dayOrder.forEach(day => {
        const info = dayVals[day];
        if (info) {
            const pct = (info.avg_interactions / maxDay * 100).toFixed(0);
            dayHtml += `<div class="mb-1"><small class="text-muted">${day}</small><div class="progress" style="height:16px"><div class="progress-bar ${day === d.best_posting_day ? 'bg-success' : 'bg-info'}" style="width:${pct}%">${info.avg_interactions} (${info.count} post)</div></div></div>`;
        }
    });

    let hashtagHtml = '';
    (d.top_hashtags || []).slice(0, 10).forEach(h => {
        hashtagHtml += `<span class="badge bg-light text-dark me-1 mb-1">#${h.tag} <small class="text-muted">${h.frequency}x, ${h.avg_interactions} int.</small></span>`;
    });

    let captionHtml = '';
    const buckets = d.caption_length_insight || {};
    const maxBucket = Math.max(...Object.values(buckets).map(v => v.avg_interactions || 0), 1);
    for (const [bucket, info] of Object.entries(buckets)) {
        const pct = (info.avg_interactions / maxBucket * 100).toFixed(0);
        captionHtml += `<div class="mb-1"><small class="text-muted">${bucket} karakter</small><div class="progress" style="height:16px"><div class="progress-bar bg-warning text-dark" style="width:${pct}%">${info.avg_interactions} int. (${info.count} post)</div></div></div>`;
    }

    const typeLabels = { IMAGE: 'Foto', VIDEO: 'Video', CAROUSEL_ALBUM: 'Album' };
    let typeHtml = '';
    const typePerf = d.media_type_performance || {};
    const maxType = Math.max(...Object.values(typePerf).map(v => v.avg_engagement_rate || 0), 0.001);
    for (const [k, v] of Object.entries(typePerf)) {
        const pct = (v.avg_engagement_rate / maxType * 100).toFixed(0);
        typeHtml += `<div class="mb-1"><span class="badge bg-secondary me-1">${typeLabels[k] || k}</span><div class="progress" style="height:16px"><div class="progress-bar ${k === d.best_media_type ? 'bg-success' : 'bg-primary'}" style="width:${pct}%">${v.avg_engagement_rate}% (${v.count} post)</div></div></div>`;
    }

    const cons = d.engagement_consistency || {};

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-6">
            <h6 class="mb-1">Performa per Hari</h6>
            <small class="text-muted d-block mb-1">Hari terbaik: <strong>${d.best_posting_day || '-'}</strong></small>
            <canvas id="chartDayBreakdown" height="140"></canvas>
            <hr class="my-1">
            <h6 class="mb-1">Performa Tipe Konten</h6>
            <small class="text-muted d-block mb-1">Terbaik: <strong>${typeLabels[d.best_media_type] || d.best_media_type || '-'}</strong></small>
            ${typeHtml || '<small class="text-muted">Tidak ada data</small>'}
        </div>
        <div class="col-md-6">
            <h6 class="mb-1">Konsistensi Engagement</h6>
            <div class="row g-1 mb-2">
                <div class="col-4">
                    <div class="p-1 bg-light rounded text-center">
                        <div class="fw-bold">${cons.average_interactions || 0}</div>
                        <small class="text-muted">Rata-rata</small>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-1 bg-light rounded text-center">
                        <div class="fw-bold">${cons.coefficient_of_variation_pct || 0}%</div>
                        <small class="text-muted">CV</small>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-1 bg-light rounded text-center">
                        <div class="fw-bold small">${cons.interpretation || '-'}</div>
                        <small class="text-muted">Status</small>
                    </div>
                </div>
            </div>
            <h6 class="mb-1">Hash Tag Populer</h6>
            <div>${hashtagHtml || '<small class="text-muted">Tidak ada hashtag</small>'}</div>
            <hr class="my-1">
            <h6 class="mb-1">Panjang Caption vs Interaksi</h6>
            ${captionHtml || '<small class="text-muted">Tidak ada data</small>'}
        </div>
    </div>`;

    setTimeout(() => {
        const dayCtx = document.getElementById('chartDayBreakdown');
        if (!dayCtx) return;
        const dayOrder2 = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu'];
        const dayVals2 = d.day_breakdown || {};
        const labels2 = dayOrder2.filter(day => dayVals2[day]);
        const data2 = labels2.map(day => dayVals2[day].avg_interactions);
        const colors2 = labels2.map(day => day === d.best_posting_day ? '#198754' : '#0d6efd');
        chartInstances.insights = new Chart(dayCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels2,
                datasets: [{
                    label: 'Rata-rata Interaksi',
                    data: data2,
                    backgroundColor: colors2,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { font: { size: 9 } } },
                    x: { ticks: { font: { size: 9 } } }
                }
            }
        });
    }, 100);
}

function renderBestTime() {
    const d = analyticsData.bestTime;
    if (!d || d.error) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    const days = d.day_names || ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu'];
    const heatmap = d.heatmap || [];

    let tableHtml = '<table class="table table-sm table-bordered mb-0" style="font-size:10px"><thead><tr><th style="min-width:60px">Hari</th>';
    for (let h = 0; h < 24; h++) {
        tableHtml += `<th class="text-center ${h >= 6 && h <= 18 ? 'text-primary' : ''}" style="min-width:22px;padding:2px">${String(h).padStart(2,'0')}</th>`;
    }
    tableHtml += '</tr></thead><tbody>';

    let maxVal = 0;
    heatmap.forEach(row => {
        row.hours.forEach(cell => {
            if (cell.avg_interactions > maxVal) maxVal = cell.avg_interactions;
        });
    });
    maxVal = Math.max(maxVal, 1);

    heatmap.forEach((row, di) => {
        tableHtml += `<tr><td class="fw-semibold small" style="padding:2px 4px">${row.day}</td>`;
        row.hours.forEach(cell => {
            const ratio = cell.avg_interactions / maxVal;
            const r = Math.round(240 - ratio * 215);
            const g = Math.round(240 - ratio * 215);
            const b = 253;
            const bg = cell.avg_interactions > 0 ? `rgb(${r},${g},${b})` : '#f8f9fa';
            const highlight = cell.avg_interactions > 0 && ratio >= 0.8 ? 'border:2px solid #0d6efd' : '';
            tableHtml += `<td class="text-center" style="padding:3px 1px;background:${bg};${highlight};cursor:pointer" title="${row.day} ${String(cell.hour).padStart(2,'0')}:00 — ${cell.avg_interactions} rata-rata interaksi (${cell.count} post)">
                ${cell.count > 0 ? `<small>${cell.avg_interactions > 0 ? Math.round(cell.avg_interactions) : ''}</small>` : ''}
            </td>`;
        });
        tableHtml += '</tr>';
    });
    tableHtml += '</tbody></table>';

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-8">
            <h6 class="mb-1">Heatmap Waktu Posting Terbaik</h6>
            <small class="text-muted d-block mb-2">Rata-rata interaksi per hari dan jam (klik sel untuk detail)</small>
            <div style="overflow-x:auto">${tableHtml}</div>
        </div>
        <div class="col-md-4">
            ${d.best_time ? `
            <div class="p-3 bg-success bg-opacity-10 rounded text-center mb-2">
                <small class="text-muted">Waktu Posting Terbaik</small>
                <div class="fw-bold fs-5">${d.best_time.day}</div>
                <div class="fw-bold fs-4 text-success">${String(d.best_time.hour).padStart(2, '0')}:00</div>
                <small class="text-muted">Rata-rata ${d.best_time.avg_interactions} interaksi</small>
            </div>` : ''}
            <h6 class="mb-1">Rekomendasi</h6>
            <div class="p-2 bg-light rounded small">
                ${d.best_time ? `
                <p class="mb-1"><strong>Posting terbaik:</strong> Hari ${d.best_time.day} pukul ${String(d.best_time.hour).padStart(2,'0')}:00</p>
                <p class="mb-0 text-muted">Posting di jam ini untuk engagement maksimal.</p>
                ` : '<p class="mb-0 text-muted">Belum cukup data untuk rekomendasi.</p>'}
            </div>
        </div>
    </div>`;
}

function renderWordCloud() {
    const d = analyticsData.wordcloud;
    if (!d || d.error || !d.length) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-8">
            <h6 class="mb-1">Word Cloud Caption & Komentar</h6>
            <div id="wordcloudContainer" style="width:100%;height:400px;position:relative"></div>
        </div>
        <div class="col-md-4">
            <h6 class="mb-1">Kata Terpopuler</h6>
            <div style="max-height:400px;overflow-y:auto" id="wordcloudList"></div>
        </div>
    </div>`;

    const listEl = document.getElementById('wordcloudList');
    listEl.innerHTML = d.slice(0, 30).map(w =>
        `<div class="d-flex justify-content-between small py-1 border-bottom"><span>${escapeHtml(w.word)}</span><span class="fw-bold text-primary">${w.count}x</span></div>`
    ).join('');

    const weightSum = d.reduce((s, w) => s + w.count, 0);
    const words = d.map(w => [w.word, (w.count / weightSum) * 100]);

    try {
        WordCloud(document.getElementById('wordcloudContainer'), {
            list: words,
            gridSize: 8,
            weightFactor: 2.5,
            fontFamily: 'sans-serif',
            color: 'random-dark',
            rotateRatio: 0.3,
            backgroundColor: '#f8f9fa',
            minSize: 10,
            shape: 'circle',
        });
    } catch(e) {
        console.error('Wordcloud error:', e);
    }
}

function renderCategories() {
    const d = analyticsData.categories;
    if (!d || d.error) {
        document.getElementById('analyticsContent').innerHTML = '<div class="text-center py-3 text-muted small">Data tidak tersedia</div>';
        return;
    }

    const catLabels = {
        produk: 'Produk', promo: 'Promo', edukasi: 'Edukasi',
        lifestyle: 'Lifestyle', inspirasi: 'Inspirasi',
        behind_scene: 'Behind Scene', uncategorized: 'Lainnya',
    };
    const catColors = {
        produk: '#0d6efd', promo: '#dc3545', edukasi: '#198754',
        lifestyle: '#fd7e14', inspirasi: '#6f42c1',
        behind_scene: '#20c997', uncategorized: '#6c757d',
    };

    const perf = d.category_performance || {};
    let perfHtml = '';
    const sortedCats = Object.entries(perf).sort((a, b) => b[1].avg_interactions - a[1].avg_interactions);
    const maxCatInt = Math.max(...sortedCats.map(([,v]) => v.avg_interactions), 1);
    sortedCats.forEach(([cat, v]) => {
        const pct = (v.avg_interactions / maxCatInt * 100).toFixed(0);
        const color = catColors[cat] || '#6c757d';
        const label = catLabels[cat] || cat;
        perfHtml += `<div class="mb-1"><span class="badge" style="background:${color}">${label}</span> <small class="text-muted">${v.count} post</small><div class="progress" style="height:18px"><div class="progress-bar" style="width:${pct}%;background:${color}">${v.avg_interactions} int.</div></div></div>`;
    });

    const dist = d.category_distribution || {};
    const totalCats = Object.values(dist).reduce((a, b) => a + b, 0);

    document.getElementById('analyticsContent').innerHTML = `
    <div class="row g-2">
        <div class="col-md-6">
            <h6 class="mb-1">Distribusi Kategori Konten</h6>
            <canvas id="chartCategories" height="220"></canvas>
        </div>
        <div class="col-md-6">
            <h6 class="mb-1">Performa per Kategori</h6>
            <small class="text-muted d-block mb-1">Terbaik: <strong>${catLabels[d.best_category] || d.best_category || '-'}</strong></small>
            ${perfHtml || '<small class="text-muted">Tidak ada data</small>'}
            <hr class="my-1">
            <div class="d-flex flex-wrap gap-1">
                ${Object.entries(dist).map(([cat, count]) => {
                    const label = catLabels[cat] || cat;
                    const color = catColors[cat] || '#6c757d';
                    const pct = totalCats ? (count / totalCats * 100).toFixed(1) : 0;
                    return `<span class="badge" style="background:${color}">${label}: ${count} (${pct}%)</span>`;
                }).join('')}
            </div>
        </div>
    </div>`;

    setTimeout(() => {
        const ctx = document.getElementById('chartCategories');
        if (!ctx) return;
        const cctx = ctx.getContext('2d');
        chartInstances.categories = new Chart(cctx, {
            type: 'doughnut',
            data: {
                labels: Object.keys(dist).map(k => catLabels[k] || k),
                datasets: [{
                    data: Object.values(dist),
                    backgroundColor: Object.keys(dist).map(k => catColors[k] || '#6c757d'),
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 8, font: { size: 10 } } }
                }
            }
        });
    }, 100);
}

async function startScrap() {
    const bar = document.getElementById('scrapBar');
    const msg = document.getElementById('scrapMessage');
    const btn = document.getElementById('btnScrap');
    const closeBtn = document.getElementById('btnScrapClose');
    const modalEl = document.getElementById('scrapModal');

    const date_from = document.getElementById('dateFrom').value;
    const date_to = document.getElementById('dateTo').value;
    const media_types = [];
    if (document.getElementById('typeImage').checked) media_types.push('IMAGE');
    if (document.getElementById('typeVideo').checked) media_types.push('VIDEO');
    if (document.getElementById('typeCarousel').checked) media_types.push('CAROUSEL_ALBUM');
    const fetch_comments = document.getElementById('fetchComments').checked;

    // Reset modal
    bar.style.width = '0%';
    bar.className = 'progress-bar progress-bar-striped progress-bar-animated';
    msg.textContent = 'Memulai...';
    document.getElementById('wpProgress').classList.add('d-none');
    closeBtn.disabled = true;

    // Show modal
    pendingSessionId = null;
    const modal = new bootstrap.Modal(modalEl);
    modal.show();

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Scrapping...';

    try {
        const res = await fetch('/api/scrap', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date_from, date_to, media_types, fetch_comments }),
        });
        const data = await res.json();

        if (data.error) {
            msg.textContent = 'Error: ' + data.error;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> Mulai Scrap';
            closeBtn.disabled = false;
            return;
        }

        pollScrapStatus(data.progress_key);
    } catch (e) {
        msg.textContent = 'Error: ' + e.message;
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> Mulai Scrap';
        closeBtn.disabled = false;
    }
}

function pollScrapStatus(key) {
    const bar = document.getElementById('scrapBar');
    const msg = document.getElementById('scrapMessage');
    const btn = document.getElementById('btnScrap');
    const wpProg = document.getElementById('wpProgress');
    const wpBar = document.getElementById('wpBar');
    const wpMsg = document.getElementById('wpMessage');

    const timer = setInterval(async () => {
        try {
            const res = await fetch(`/api/scrap/status?key=${encodeURIComponent(key)}`);
            const status = await res.json();

            msg.textContent = status.message || '';

            if (status.download_pct > 0) {
                bar.style.width = status.download_pct + '%';
                bar.classList.remove('progress-bar-animated');
            } else {
                bar.style.width = '30%';
            }

            if (status.wp_total > 0) {
                wpProg.classList.remove('d-none');
                const wpPct = Math.round((status.wp_posted || 0) / status.wp_total * 100);
                wpBar.style.width = wpPct + '%';
                wpMsg.textContent = `WordPress: ${status.wp_posted || 0}/${status.wp_total} post`;
                if (status.wp_posted >= status.wp_total) {
                    wpBar.classList.remove('progress-bar-animated');
                }
            }

            if (status.status === 'done') {
                clearInterval(timer);
                bar.style.width = '100%';
                bar.classList.remove('progress-bar-animated');
                bar.classList.add('bg-success');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> Mulai Scrap';

                if (status.wp_total > 0) {
                    wpBar.style.width = '100%';
                    wpBar.classList.remove('progress-bar-animated');
                }

                document.getElementById('btnScrapClose').disabled = false;

                if (status.session_id) {
                    pendingSessionId = status.session_id;
                }
            } else if (status.status === 'error') {
                clearInterval(timer);
                bar.classList.remove('progress-bar-animated');
                bar.classList.add('bg-danger');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> Mulai Scrap';
                document.getElementById('btnScrapClose').disabled = false;
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    }, 1000);
}

let pendingSessionId = null;

function closeScrapModal() {
    const modal = bootstrap.Modal.getInstance(document.getElementById('scrapModal'));
    if (modal) modal.hide();
    if (pendingSessionId) {
        switchSession(pendingSessionId);
        loadSessions();
        pendingSessionId = null;
    }
}

// --- Post Detail Modal ---
let currentPost = null;
let currentMediaIndex = 0;

async function openPostDetail(postId) {
    if (!activeSession) return;
    try {
        const res = await fetch(`/api/sessions/${activeSession}/posts/${postId}`);
        const post = await res.json();
        if (post.error) return;
        currentPost = post;
        currentMediaIndex = 0;
        showPostModal(post);
    } catch (e) {
        console.error('Failed to load post detail:', e);
    }
}

function showPostModal(post) {
    document.getElementById('modalType').textContent = post.media_type;
    document.getElementById('modalLikes').textContent = post.like_count || 0;
    document.getElementById('modalComments').textContent = post.comments_count || 0;
    document.getElementById('modalDate').textContent = formatDate(post.timestamp);
    document.getElementById('modalPermalink').href = post.permalink || '#';
    document.getElementById('modalCaption').textContent = post.caption || '(tidak ada caption)';

    // Build media items array
    const mediaItems = [];
    if (post.media_type === 'CAROUSEL_ALBUM' && post.children && post.children.length) {
        post.children.forEach(c => {
            mediaItems.push({
                url: c.media_url || c.thumbnail_url,
                type: c.media_type,
                file: null, // We'll check local files
            });
        });
    } else if (post.media_type === 'IMAGE' || post.media_type === 'VIDEO') {
        mediaItems.push({
            url: post.media_url,
            type: post.media_type,
            file: post.media_files && post.media_files.length > 0 ? post.media_files[0] : null,
        });
    }

    // Try to find local files for carousel children
    if (post.media_type === 'CAROUSEL_ALBUM' && post.children && post.children.length) {
        post.children.forEach((c, i) => {
            const key = `${post.id}_${c.id}`;
            const match = (post.media_files || []).find(f => f.includes(key));
            if (match) mediaItems[i].file = match;
        });
    }

    currentPost._mediaItems = mediaItems;
    renderModalMedia(currentMediaIndex = 0);

    // Render comments
    const section = document.getElementById('modalCommentsSection');
    const list = document.getElementById('modalCommentsList');
    const comments = post.comments || [];
    if (comments.length > 0) {
        list.innerHTML = comments.map(c => {
            const text = c.text || '';
            const username = c.username || '';
            const sent = getPostSentiment(text);
            const badge = sent.sentiment === 'positive' ? 'bg-success' :
                          sent.sentiment === 'negative' ? 'bg-danger' : 'bg-secondary';
            const label = sent.sentiment === 'positive' ? 'Positif' :
                          sent.sentiment === 'negative' ? 'Negatif' : 'Netral';
            return `
            <div class="mb-2 p-2 bg-light rounded">
                <div class="d-flex justify-content-between">
                    <strong class="small">${escapeHtml(username)}</strong>
                    <span class="badge ${badge}">${label}</span>
                </div>
                <div class="small mt-1">${escapeHtml(text)}</div>
            </div>`;
        }).join('');
        section.classList.remove('d-none');
    } else {
        section.classList.add('d-none');
    }

    const modal = new bootstrap.Modal(document.getElementById('postModal'));
    modal.show();
}

function renderModalMedia(index) {
    const container = document.getElementById('postModalMedia');
    const items = currentPost._mediaItems || [];
    const prevBtn = document.getElementById('mediaPrev');
    const nextBtn = document.getElementById('mediaNext');
    const counter = document.getElementById('mediaCounter');

    if (items.length === 0) {
        container.innerHTML = '<div class="text-muted p-3">Tidak ada media</div>';
        prevBtn.classList.add('d-none');
        nextBtn.classList.add('d-none');
        counter.style.display = 'none';
        return;
    }

    const item = items[index];
    const fileSrc = item.file ? `/api/media/${activeSession}/${item.file.replace(/^.*?media[\\/]/, '')}` : null;
    const src = fileSrc || item.url;

    if (item.type === 'VIDEO') {
        container.innerHTML = `<video controls autoplay><source src="${src}" type="video/mp4"></video>`;
    } else {
        container.innerHTML = `<img src="${src}" alt="Post media" onerror="this.parentElement.innerHTML='<span class=\\'text-muted\\'>Gagal memuat media</span>'">`;
    }

    // Show carousel children thumbs
    const childrenContainer = document.getElementById('modalChildren');
    if (items.length > 1) {
        childrenContainer.innerHTML = `
        <hr class="my-2">
        <small class="text-muted d-block mb-1">${items.length} media dalam album ini:</small>
        <div class="carousel-thumbs">
            ${items.map((it, i) => {
                const thumbSrc = it.file ? `/api/media/${activeSession}/${it.file.replace(/^.*?media[\\/]/, '')}` : it.url;
                return `<img src="${thumbSrc}" class="${i === index ? 'active' : ''}"
                     onclick="renderModalMedia(${i})"
                     onerror="this.outerHTML='<span class=\\'badge bg-secondary\\'>${i+1}</span>'"
                     loading="lazy">`;
            }).join('')}
        </div>`;
    } else {
        childrenContainer.innerHTML = '';
    }

    // Navigation
    if (items.length > 1) {
        prevBtn.classList.remove('d-none');
        nextBtn.classList.remove('d-none');
        counter.style.display = 'block';
        counter.textContent = `${index + 1} / ${items.length}`;
        prevBtn.onclick = () => navigateMedia(-1);
        nextBtn.onclick = () => navigateMedia(1);
    } else {
        prevBtn.classList.add('d-none');
        nextBtn.classList.add('d-none');
        counter.style.display = 'none';
    }
}

function navigateMedia(dir) {
    const items = currentPost._mediaItems || [];
    const newIndex = currentMediaIndex + dir;
    if (newIndex < 0 || newIndex >= items.length) return;
    renderModalMedia(currentMediaIndex = newIndex);
}

// --- Downloads ---
function downloadCSV() {
    if (!activeSession) return alert('Pilih sesi terlebih dahulu');
    window.open(`/api/sessions/${activeSession}/csv`, '_blank');
}

function downloadImages() {
    if (!activeSession) return alert('Pilih sesi terlebih dahulu');
    window.open(`/api/sessions/${activeSession}/images`, '_blank');
}

// --- Search & Sort ---
function debounceSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        currentPage = 1;
        loadPosts();
    }, 400);
}

// --- WordPress ---
async function checkWpStatus() {
    try {
        const res = await fetch('/api/wp/status');
        const data = await res.json();
        wpConfigured = data.configured;

        if (data.configured) {
            document.getElementById('navWpBadge').classList.remove('d-none');
            document.getElementById('btnPostToWP').classList.remove('d-none');
        }
    } catch (e) {
        console.error('Failed to check WP status:', e);
    }
}

// --- WP Selection ---
function toggleSelectAll(checkbox) {
    document.querySelectorAll('.post-checkbox').forEach(cb => cb.checked = checkbox.checked);
    updateSelectedCount();
}

function updateSelectedCount() {
    const selected = document.querySelectorAll('.post-checkbox:checked').length;
    const btn = document.getElementById('btnPostSelected');
    const label = document.getElementById('wpSelectedLabel');
    if (selected > 0 && wpConfigured) {
        btn.classList.remove('d-none');
        label.textContent = `WP (${selected})`;
    } else {
        btn.classList.add('d-none');
    }
}

function getSelectedPostIds() {
    return Array.from(document.querySelectorAll('.post-checkbox:checked')).map(cb => cb.value);
}

function postSelectedToWP() {
    const ids = getSelectedPostIds();
    if (!ids.length) return;

    // Show scrap modal for WP progress
    const bar = document.getElementById('scrapBar');
    const msg = document.getElementById('scrapMessage');
    bar.style.width = '0%';
    bar.className = 'progress-bar progress-bar-striped progress-bar-animated';
    msg.textContent = 'Mengupload ke WordPress...';
    document.getElementById('wpProgress').classList.add('d-none');
    document.getElementById('btnScrapClose').disabled = true;
    new bootstrap.Modal(document.getElementById('scrapModal')).show();

    const btn = document.getElementById('btnPostSelected');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    postSessionToWP(ids);
}

async function postSessionToWP(postIds) {
    if (!activeSession) return alert('Pilih sesi terlebih dahulu');
    if (!wpConfigured) return alert('WordPress belum dikonfigurasi di .env');

    const btn = document.getElementById('btnPostToWP');
    if (!postIds || !postIds.length) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    }

    try {
        const res = await fetch(`/api/sessions/${activeSession}/post-to-wp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ post_ids: postIds || [] }),
        });
        const data = await res.json();

        if (data.error) {
            alert('Error: ' + data.error);
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-wordpress"></i> WP All';
            return;
        }

        pollWpStatus(data.progress_key, postIds);
    } catch (e) {
        alert('Error: ' + e.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-wordpress"></i> WP All';
    }
}

function pollWpStatus(key, postIds) {
    const btnAll = document.getElementById('btnPostToWP');
    const btnSel = document.getElementById('btnPostSelected');
    const bar = document.getElementById('scrapBar');
    const msg = document.getElementById('scrapMessage');
    const wpProg = document.getElementById('wpProgress');
    const wpBar = document.getElementById('wpBar');
    const wpMsg = document.getElementById('wpMessage');
    const closeBtn = document.getElementById('btnScrapClose');

    const isSelective = postIds && postIds.length > 0;
    const activeBtn = isSelective ? btnSel : btnAll;

    const timer = setInterval(async () => {
        try {
            const res = await fetch(`/api/scrap/status?key=${encodeURIComponent(key)}`);
            const status = await res.json();

            if (status.wp_total > 0) {
                activeBtn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${status.wp_posted}/${status.wp_total}`;

                // Update modal if selective
                if (isSelective) {
                    wpProg.classList.remove('d-none');
                    const wpPct = Math.round((status.wp_posted || 0) / status.wp_total * 100);
                    wpBar.style.width = wpPct + '%';
                    wpMsg.textContent = `WordPress: ${status.wp_posted || 0}/${status.wp_total} post`;
                    msg.textContent = `Mengupload ${status.wp_posted || 0}/${status.wp_total} ke WordPress...`;
                }
            }

            if (status.status === 'done') {
                clearInterval(timer);
                bar.style.width = '100%';
                bar.classList.remove('progress-bar-animated');
                bar.classList.add('bg-success');
                if (isSelective) {
                    wpBar.style.width = '100%';
                    wpBar.classList.remove('progress-bar-animated');
                    msg.textContent = 'Selesai!';
                }
                activeBtn.disabled = false;
                activeBtn.innerHTML = isSelective ? '<i class="bi bi-wordpress"></i> WP' : '<i class="bi bi-wordpress"></i> WP All';
                const ok = (status.wp_results || []).filter(r => r.success).length;
                const total = status.wp_total || ok;
                closeBtn.disabled = false;
                pendingSessionId = null;
                if (isSelective) {
                    document.querySelectorAll('.post-checkbox:checked').forEach(cb => cb.checked = false);
                    document.getElementById('selectAll').checked = false;
                    updateSelectedCount();
                }
            } else if (status.status === 'error') {
                clearInterval(timer);
                bar.classList.remove('progress-bar-animated');
                bar.classList.add('bg-danger');
                activeBtn.disabled = false;
                activeBtn.innerHTML = isSelective ? '<i class="bi bi-wordpress"></i> WP' : '<i class="bi bi-wordpress"></i> WP All';
                closeBtn.disabled = false;
            }
        } catch (e) {
            console.error('WP poll error:', e);
        }
    }, 1500);
}

// --- Helpers ---
function getThumbSrc(post) {
    if (post.media_files && post.media_files.length > 0) {
        const f = post.media_files[0];
        const rel = f.replace(/^.*?media[\\/]/, '');
        return `/api/media/${activeSession}/${rel}`;
    }
    if (post.media_type === 'VIDEO' && post.thumbnail_url) return post.thumbnail_url;
    if (post.media_url) return post.media_url;
    if (post.media_type === 'CAROUSEL_ALBUM' && post.children && post.children.length) {
        const c = post.children[0];
        return c.media_url || c.thumbnail_url || null;
    }
    return null;
}

function formatDate(ts) {
    if (!ts) return '-';
    const d = ts.substring(0, 10);
    const parts = d.split('-');
    if (parts.length !== 3) return d;
    const months = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
    return `${parts[2]} ${months[parseInt(parts[1]) - 1] || parts[1]} ${parts[0]}`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function showError(msg) {
    document.getElementById('postsBody').innerHTML =
        `<tr><td colspan="9" class="text-center py-5 text-danger">${escapeHtml(msg)}</td></tr>`;
}

const POSITIVE_WORDS = new Set([
    "baik","bagus","hebat","keren","mantap","sukses","indah","cantik",
    "menarik","nyaman","senang","bahagia","puas","bangga","lucu",
    "imut","gemas","bersyukur","terima kasih","makasih","love","suka",
    "sempurna","istimewa","luar biasa","recommended","rekomendasi",
    "wow","amazing","beautiful","great","awesome","fantastic",
    "terbaik","terkeren","terindah","terlucu","kreatif","inovatif",
    "menginspirasi","inspiratif","motivasi","semangat","keren abis",
    "cakep","kece","sip","top","nice","good","perfect",
    "inspiring","wonderful","excellent","brilliant","stunning",
    "murah","hemat","untung","berkah","sehat","segar","cerah",
]);

const NEGATIVE_WORDS = new Set([
    "buruk","jelek","parah","payah","mengerikan","menyedihkan",
    "kecewa","gagal","rugi","susah","sulit","sedih","marah",
    "benci","muak","jijik","bosan","membosankan","capek","lelah",
    "gak enak","ga enak","nggak enak","tidak enak","sampah",
    "mengecewakan","menjijikkan","horor","mengerikan","ngeri",
    "jahat","kejam","kasar","buruk banget","jelek banget",
    "worst","bad","terrible","awful","hate","ugly","boring",
    "horrible","disappointed","disappointing","fail","failed",
    "sakit","pusing","stress","frustrasi","kalut","kacau",
    "mahal","boros","menyesal","nyesel","zonk","gagal total",
    "tidak suka","ga suka","gak suka","nggak suka","ga mood",
    "berantakan","amburadul","sembarangan","asalan",
]);

function getPostSentiment(text) {
    let cleaned = (text || '').toLowerCase()
        .replace(/[#@]\w+/g, '')
        .replace(/https?:\/\/\S+/g, '')
        .trim();
    const words = new Set(cleaned.split(/\s+/));

    let pos_count = 0;
    let neg_count = 0;

    words.forEach(w => {
        if (POSITIVE_WORDS.has(w)) pos_count++;
        if (NEGATIVE_WORDS.has(w)) neg_count++;
    });

    POSITIVE_WORDS.forEach(phrase => {
        if (phrase.includes(' ') && cleaned.includes(phrase)) pos_count++;
    });
    NEGATIVE_WORDS.forEach(phrase => {
        if (phrase.includes(' ') && cleaned.includes(phrase)) neg_count++;
    });

    const net = pos_count - neg_count;
    let label = 'neutral';
    if (net > 0) label = 'positive';
    else if (net < 0) label = 'negative';

    return { sentiment: label, score: net };
}

// --- Event Listeners ---
document.getElementById('searchInput').addEventListener('input', debounceSearch);
document.getElementById('sortSelect').addEventListener('change', () => { currentPage = 1; loadPosts(); });

// Keyboard navigation for modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') navigateMedia(-1);
    if (e.key === 'ArrowRight') navigateMedia(1);
    if (e.key === 'Escape') {
        const modal = bootstrap.Modal.getInstance(document.getElementById('postModal'));
        if (modal) modal.hide();
    }
});

// --- Sentiment Words ---
async function openSentimentWordsModal() {
    const container = document.getElementById('sentimentWordsContent');
    container.innerHTML = '<div class="text-center py-4 text-muted small">Memuat...</div>';
    const modal = new bootstrap.Modal(document.getElementById('sentimentWordsModal'));
    modal.show();

    try {
        const res = await fetch('/api/config/sentiment-words');
        const data = await res.json();

        if (data.error) {
            container.innerHTML = `<div class="text-danger text-center py-3">${escapeHtml(data.error)}</div>`;
            return;
        }

        function renderBadges(words, label, badgeClass) {
            if (!words.length) return '<small class="text-muted">Tidak ada kata</small>';
            return words.map(w => `<span class="badge ${badgeClass} me-1 mb-1">${escapeHtml(w)}</span>`).join('');
        }

        container.innerHTML = `
            <div class="col-md-6">
                <div class="card h-100">
                    <div class="card-header py-1 bg-success text-white">
                        <i class="bi bi-emoji-smile"></i> Positif (${data.positive.length})
                    </div>
                    <div class="card-body small" style="max-height:300px;overflow-y:auto">
                        ${renderBadges(data.positive, 'Positif', 'bg-success')}
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card h-100">
                    <div class="card-header py-1 bg-danger text-white">
                        <i class="bi bi-emoji-frown"></i> Negatif (${data.negative.length})
                    </div>
                    <div class="card-body small" style="max-height:300px;overflow-y:auto">
                        ${renderBadges(data.negative, 'Negatif', 'bg-danger')}
                    </div>
                </div>
            </div>
        `;
    } catch (e) {
        container.innerHTML = `<div class="text-danger text-center py-3">Error: ${escapeHtml(e.message)}</div>`;
    }
}

// --- Settings / Token ---
async function openSettingsModal() {
    document.getElementById('tokenStatus').innerHTML = '';
    document.getElementById('btnUpdateToken').disabled = false;
    document.getElementById('btnUpdateToken').innerHTML = '<i class="bi bi-check-circle"></i> Update & Test';
    document.getElementById('tokenInput').value = '';

    const infoEl = document.getElementById('settingsAccountInfo');
    infoEl.innerHTML = '<em class="text-muted">Memuat info akun...</em>';

    const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
    modal.show();

    try {
        const res = await fetch('/api/config/account');
        const data = await res.json();
        if (data.ok && data.account) {
            const a = data.account;
            infoEl.innerHTML = `
                <div class="d-flex align-items-center gap-2 mb-1">
                    <strong>@${a.username || '?'}</strong>
                    <span class="badge bg-secondary">${a.name || ''}</span>
                </div>
                <div class="text-muted">${a.followers_count || 0} followers &middot; ${a.media_count || 0} posts</div>
            `;
            document.getElementById('navAccount').innerHTML = `
                <i class="bi bi-instagram"></i> @${a.username || '?'}
            `;
        } else {
            infoEl.innerHTML = `<span class="text-danger">Token error: ${escapeHtml(data.error || '?')}</span>`;
        }
    } catch (e) {
        infoEl.innerHTML = `<span class="text-danger">Gagal memuat info akun</span>`;
    }
}

async function updateToken() {
    const token = document.getElementById('tokenInput').value.trim();
    const btn = document.getElementById('btnUpdateToken');
    const status = document.getElementById('tokenStatus');

    if (!token) {
        status.innerHTML = '<span class="text-danger">Token tidak boleh kosong</span>';
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Updating...';
    status.innerHTML = '';

    try {
        const res = await fetch('/api/config/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ access_token: token }),
        });
        const data = await res.json();

        if (data.error) {
            status.innerHTML = `<span class="text-danger">${escapeHtml(data.error)}</span>`;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-check-circle"></i> Update & Test';
            return;
        }

        status.innerHTML = '<span class="text-success">Token tersimpan. Menguji...</span>';

        // Test the new token
        const testRes = await fetch('/api/config/ig-test');
        const testData = await testRes.json();

        if (testData.ok) {
            status.innerHTML = `<span class="text-success">${escapeHtml(testData.message)}</span>`;
            document.getElementById('settingsAccountInfo').innerHTML = `
                <div class="d-flex align-items-center gap-2 mb-1">
                    <strong>@${testData.username || '?'}</strong>
                </div>
                <div class="text-muted">${testData.followers || 0} followers</div>
            `;
            document.getElementById('navAccount').innerHTML = `
                <i class="bi bi-instagram"></i> @${testData.username || '?'}
            `;
        } else {
            status.innerHTML = `<span class="text-warning">Token tersimpan, tapi gagal verifikasi: ${escapeHtml(testData.error || '?')}</span>`;
        }
    } catch (e) {
        status.innerHTML = `<span class="text-danger">Error: ${escapeHtml(e.message)}</span>`;
    }

    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-check-circle"></i> Update & Test';
}

// --- Init ---
checkWpStatus();
loadSessions();

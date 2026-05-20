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
            <div class="session-item${activeSession === s.session_id ? ' active' : ''}"
                 onclick="switchSession('${s.session_id}')">
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
        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-5 text-muted">Tidak ada hasil</td></tr>';
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
            <td class="text-muted small" style="cursor:pointer" onclick="openPostDetail('${p.id}')">${offset + i + 1}</td>
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
            body: JSON.stringify({ date_from, date_to, media_types }),
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
        `<tr><td colspan="8" class="text-center py-5 text-danger">${escapeHtml(msg)}</td></tr>`;
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

// --- Settings / Token ---
async function openSettingsModal() {
    document.getElementById('tokenStatus').innerHTML = '';
    document.getElementById('btnUpdateToken').disabled = false;
    document.getElementById('btnUpdateToken').innerHTML = '<i class="bi bi-check-circle"></i> Update & Test';

    const infoEl = document.getElementById('settingsAccountInfo');
    infoEl.innerHTML = '<em class="text-muted">Memuat info akun...</em>';

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

    // Load current token from .env — we show placeholder
    document.getElementById('tokenInput').value = '';

    const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
    modal.show();
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

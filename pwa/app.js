const API_BASE = '/api';
let autoRefreshInterval = null;
const REFRESH_INTERVAL = 800; // faster sync so deletes disappear quickly
let lastMessages = []; // Track previous messages for diffing
let shouldStickOnNextRender = true;
let hasAnchoredInitialView = false;

// DOM Elements
const messagesContainer = document.getElementById('messagesContainer');
const clearBtn = document.getElementById('clearBtn');
const fabBtn = document.getElementById('fabBtn');
const toast = document.getElementById('toast');
const requestsBadge = document.getElementById('requestsBadge'); // new

let clipboardInstance = null;

// filter criteria persisted in-memory; empty = show all
let filterCriteria = {
    date: '',
    time: '',
    from: '',
    to: '',
    people: ''
};

// modal + controls
const filterBtn = document.getElementById('filterBtn');
const filterModal = document.getElementById('filterModal');
const filterBackdrop = document.getElementById('filterBackdrop');
const filterForm = document.getElementById('filterForm');
const filterDate = document.getElementById('filterDate');
const filterTime = document.getElementById('filterTime');
const filterFrom = document.getElementById('filterFrom');
const filterTo = document.getElementById('filterTo');
const filterPeople = document.getElementById('filterPeople');
const applyFilterBtn = document.getElementById('applyFilter');
const clearFilterBtn = document.getElementById('clearFilter');
const closeFilterBtn = document.getElementById('closeFilter');

function openFilterModal() {
    // populate inputs from current criteria
    filterDate.value = filterCriteria.date || '';
    filterTime.value = filterCriteria.time || '';
    filterFrom.value = filterCriteria.from || '';
    filterTo.value = filterCriteria.to || '';
    filterPeople.value = filterCriteria.people || '';
    filterModal.setAttribute('aria-hidden', 'false');
}
function closeFilterModal() {
    filterModal.setAttribute('aria-hidden', 'true');
}

filterBtn && filterBtn.addEventListener('click', openFilterModal);
filterBackdrop && filterBackdrop.addEventListener('click', closeFilterModal);
closeFilterBtn && closeFilterBtn.addEventListener('click', closeFilterModal);

applyFilterBtn && applyFilterBtn.addEventListener('click', () => {
    filterCriteria = {
        date: (filterDate.value || '').trim().toLowerCase(),
        time: (filterTime.value || '').trim().toLowerCase(),
        from: (filterFrom.value || '').trim().toLowerCase(),
        to: (filterTo.value || '').trim().toLowerCase(),
        people: (filterPeople.value || '').trim()
    };
    lastMessages = []; // force re-render
    closeFilterModal();
    loadMessages();
});

clearFilterBtn && clearFilterBtn.addEventListener('click', () => {
    filterCriteria = { date: '', time: '', from: '', to: '', people: '' };
    filterDate.value = filterTime.value = filterFrom.value = filterTo.value = filterPeople.value = '';
    lastMessages = [];
    closeFilterModal();
    loadMessages();
});

// wire core buttons safely
if (clearBtn) clearBtn.addEventListener('click', clearAllMessages);
if (fabBtn) fabBtn.addEventListener('click', toggleAutoRefresh);

// Initial load
console.log('🚀 Initializing GoDrive...');
loadMessages();
startAutoRefresh();

function showToast(message, type = 'success') {
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function isFeedNearBottom(threshold = 120) {
    if (!messagesContainer) return true;
    const remaining = messagesContainer.scrollHeight - (messagesContainer.scrollTop + messagesContainer.clientHeight);
    return remaining <= threshold;
}

function stickFeedToBottom() {
    if (!messagesContainer) return;

    const pin = () => {
        const maxScrollTop = Math.max(0, messagesContainer.scrollHeight - messagesContainer.clientHeight);
        messagesContainer.scrollTop = maxScrollTop;
    };

    requestAnimationFrame(pin);
    setTimeout(pin, 60);
    setTimeout(pin, 180);
}

async function loadMessages() {
    try {
        const wasNearBottom = isFeedNearBottom();
        console.log('📡 Fetching messages...');
        const res = await fetch(`${API_BASE}/messages`);
        const data = await res.json();

        if (data.status === 'ok') {
            let messages = data.messages || [];
            // apply form filter
            messages = applyFormFilter(messages);
            // Chat flow: old requests at top, newest at bottom.
            messages.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
            if (messages.length > 0) {
                console.log(`✅ Loaded ${messages.length} messages`);
                renderMessagesWithDiff(messages, { wasNearBottom });
            } else {
                messagesContainer.innerHTML = `
                    <div class="loading-state">
                        <div style="font-size: 48px; opacity: 0.5;">🚗</div>
                        <p>${(filterCriteria.date || filterCriteria.time || filterCriteria.from || filterCriteria.to || filterCriteria.people) ? 'No requests match your filter' : 'No requests yet. Waiting for rides...'}</p>
                    </div>
                `;
                lastMessages = [];
            }
        } else {
            messagesContainer.innerHTML = '<div class="loading-state"><p>⚠️ Error loading requests</p></div>';
        }
    } catch (err) {
        console.error('Failed to load messages:', err);
        messagesContainer.innerHTML = '<div class="loading-state"><p>⚠️ Connection error</p></div>';
    }
}

// New: apply form-based filter to messages array
function applyFormFilter(messages) {
    // if all empty -> no filter
    const any = filterCriteria.date || filterCriteria.time || filterCriteria.from || filterCriteria.to || filterCriteria.people;
    if (!any) return messages;

    return messages.filter(msg => {
        // date/time match: look inside message_text (simple substring match)
        const text = (msg.message_text || '').toLowerCase();
        if (filterCriteria.date && !text.includes(filterCriteria.date)) return false;
        if (filterCriteria.time && !text.includes(filterCriteria.time)) return false;

        // from -> pickup
        if (filterCriteria.from) {
            const pick = (msg.pickup || '').toLowerCase();
            if (!pick.includes(filterCriteria.from)) return false;
        }

        // to -> dropoff
        if (filterCriteria.to) {
            const drop = (msg.dropoff || '').toLowerCase();
            if (!drop.includes(filterCriteria.to)) return false;
        }

        // people -> use extractor to get number from message_text
        if (filterCriteria.people) {
            const fields = extractSummaryFields(msg.message_text || '');
            if (!fields.people) return false;
            if (String(fields.people) !== String(filterCriteria.people)) return false;
        }
        return true;
    });
}

function renderMessagesWithDiff(newMessages, options = {}) {
    // Check if messages have changed (including content changes)
    const hasChanges = checkForChanges(lastMessages, newMessages);
    const wasNearBottom = options.wasNearBottom ?? isFeedNearBottom();
    const hadNoPreviousMessages = lastMessages.length === 0;
    const previousTailId = lastMessages[lastMessages.length - 1]?.tg_message_id;
    const nextTailId = newMessages[newMessages.length - 1]?.tg_message_id;
    const hasNewTailMessage = !hadNoPreviousMessages && nextTailId && previousTailId !== nextTailId;
    
    if (!hasChanges && lastMessages.length > 0) {
        // No changes, skip rendering
        console.log('📌 Messages unchanged');
        return;
    }

    // Stick only when opening first time or when user was already near bottom and new tail message arrived.
    shouldStickOnNextRender = hadNoPreviousMessages || (wasNearBottom && hasNewTailMessage);
    
    // Changes detected, re-render
    console.log('🔄 Re-rendering messages (changes detected)');
    lastMessages = JSON.parse(JSON.stringify(newMessages));
    renderMessages(newMessages);
}

function checkForChanges(oldMessages, newMessages) {
    // Check if number of messages changed
    if (oldMessages.length !== newMessages.length) {
        return true;
    }
    
    // Check if any message content changed (including edits)
    for (let i = 0; i < oldMessages.length; i++) {
        const oldMsg = oldMessages[i];
        const newMsg = newMessages[i];
        
        // Check for message deletions or additions
        if (oldMsg.tg_message_id !== newMsg.tg_message_id) {
            return true;
        }
        
        // Check for content changes (edits)
        if (oldMsg.message_text !== newMsg.message_text ||
            oldMsg.pickup !== newMsg.pickup ||
            oldMsg.dropoff !== newMsg.dropoff ||
            oldMsg.edited_at !== newMsg.edited_at) {
            console.log(`✏️ Message ${oldMsg.tg_message_id} was edited`);
            return true;
        }
        
        // Check for deletion flag changes
        if (oldMsg.is_deleted !== newMsg.is_deleted) {
            return true;
        }
    }
    
    return false;
}

function generatePrefillMessage(messageText) {
    // Remove "looking for driver" phrase
    const cleanedMsg = messageText.replace(/looking for driver/gi, '').trim();
    
    // Generate prefill message
    const prefillMsg = `Hai. Dah ada driver ke?\n\n${cleanedMsg}\n\n~ RM`;
    
    return prefillMsg;
}

// new: extract simple summary fields from message body
function extractSummaryFields(text) {
	if (!text) return {};
	const out = {};
	// tolerant patterns: Date / Today / Tomorrow / Tanggal
	const dateMatch = text.match(/(?:Date|Tanggal|Hari)\s*[:\-]\s*([^\n\r]+)/i)
		|| text.match(/\b(Today|Tomorrow|Hari ini|Esok|Now)\b/i && []);
	if (dateMatch && dateMatch[1]) out.date = dateMatch[1].trim();
	// time patterns
	const timeMatch = text.match(/(?:Time|Waktu|Jam)\s*[:\-]\s*([^\n\r]+)/i)
		|| text.match(/\b(?:now|now\W|\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\b/i && []);
	if (timeMatch && timeMatch[1]) out.time = timeMatch[1].trim();
	// people / passengers / jumlah
	const peopleMatch = text.match(/(?:People|Passengers|Jumlah|Pax|Orang)\s*[:\-]\s*(\d+)/i)
		|| text.match(/\b(\d+)\s*(?:pax|people|orang|penumpang)\b/i);
	if (peopleMatch) out.people = (peopleMatch[1] || peopleMatch[0]).trim();
	return out;
}

// replace buildSummaryHTML + locations usage with combined badges builder
function buildCombinedBadges(msg) {
	// msg: contains message_text, pickup, dropoff
	const fields = extractSummaryFields(msg.message_text || '');
	const badges = [];

	// Date first
	if (fields.date) badges.push(`<span class="summary-badge date">🗓️ ${escapeHtml(fields.date)}</span>`);

	// Time next
	if (fields.time) badges.push(`<span class="summary-badge time">🕒 ${escapeHtml(fields.time)}</span>`);

	// Pickup (use pickup from parsed msg)
	if (msg.pickup) badges.push(`<span class="summary-badge pickup-badge">📍 ${escapeHtml(msg.pickup)}</span>`);

	// Dropoff
	if (msg.dropoff) badges.push(`<span class="summary-badge dropoff-badge">📍 ${escapeHtml(msg.dropoff)}</span>`);

	// Number of people last
	if (fields.people) badges.push(`<span class="summary-badge people">👥 ${escapeHtml(fields.people)}</span>`);

	if (badges.length === 0) return '';
	return `<div class="summary-badges">${badges.join('')}</div>`;
}

function renderMessages(messages) {
	messagesContainer.innerHTML = '';

	messages.forEach((msg, index) => {
		const isRide = msg.pickup || msg.dropoff;
		const cardClass = isRide ? 'message-card ride' : 'message-card';
		
		const timeStr = new Date(msg.created_at).toLocaleTimeString('en-US', {
			hour: '2-digit',
			minute: '2-digit'
		});

		const senderInitials = (msg.sender_name || `User ${msg.sender_id}`)
			.split(' ')
			.map(n => n[0])
			.join('')
			.substring(0, 2)
			.toUpperCase();

		// avatar markup: image if available, else fallback initials
		const avatarAttr = msg.avatar_url ? escapeHtml(msg.avatar_url) : '';
		const avatarHTML = msg.avatar_url
			? `<div class="sender-avatar avatar-clickable" data-avatar="${avatarAttr}" data-name="${escapeHtml(getDisplayName(msg))}"><img src="${escapeHtml(msg.avatar_url)}" alt="avatar" onerror="this.style.display='none'; this.parentElement.classList.add('no-img')"><span class="avatar-fallback" style="display:none">${senderInitials}</span></div>`
			: `<div class="sender-avatar avatar-clickable" data-avatar="" data-name="${escapeHtml(getDisplayName(msg))}"><span class="avatar-fallback">${senderInitials}</span></div>`;

		// Generate prefill message
		const prefillMsg = generatePrefillMessage(msg.message_text || '');
		const encodedMsg = encodeURIComponent(prefillMsg);

		// Reply preview placeholder (shows only if this message is a reply)
		// use composite id "chat_id:reply_to_msg_id" so server can find the stored row
		const replyComposite = (msg.reply_to_msg_id && msg.chat_id) ? `${msg.chat_id}:${msg.reply_to_msg_id}` : '';
		const replyPlaceholder = replyComposite
			? `<div class="reply-preview" data-reply-id="${replyComposite}">Loading reply…</div>`
			: '';

		// Determine contact URL and button layout
		let contactUrl = msg.contact_url || '#';
		let buttonHTML = '';
		
		if (contactUrl && contactUrl !== '#') {
			if (contactUrl.includes('t.me/')) {
				// User HAS username - single Chat button
				const chatLink = `${contactUrl}?text=${encodedMsg}`;
				buttonHTML = `<a href="${chatLink}" class="action-btn btn-primary" target="_blank" style="flex: 1;">💬 Contact</a>`;
			} else if (contactUrl.includes('tg://user')) {
				// User NO username - Copy + Contact buttons (copy-btn used by ClipboardJS)
				buttonHTML = `
					<button class="action-btn btn-secondary copy-btn" type="button" style="flex: 1;">📋 Copy Message</button>
					<a href="${contactUrl}" class="action-btn btn-primary" target="_blank" style="flex: 1;">💬 Contact</a>
				`;
			} else {
				buttonHTML = `<a href="${contactUrl}" class="action-btn btn-primary" target="_blank" style="flex: 1;">💬 Contact</a>`;
			}
		} else {
			// No contact URL - disabled button
			buttonHTML = `<button class="action-btn btn-primary" disabled style="flex: 1;">💬 No Contact</button>`;
		}
		
		// Remove combinedBadgesHTML and location-badges from card body
		const card = document.createElement('div');
        card.className = cardClass;
        card.style.animationDelay = `${index * 0.03}s`;
        card.style.animation = `slideUp 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) forwards`;
        
        card.innerHTML = `
            <div class="card-header">
                <div class="sender-info" style="display: flex; align-items: flex-start; gap: 12px; flex: 1;">
                    ${avatarHTML}
                    <div style="flex: 1; min-width: 0;">
                        <div class="sender-name">${escapeHtml(getDisplayName(msg))}</div>
                        <div class="sender-meta">${escapeHtml(msg.group_name)}</div>
                    </div>
                </div>
            </div>
            <div class="card-body">
                ${replyPlaceholder}
                <div class="message-text">${escapeHtml(msg.message_text || '').replace(/\n/g, '<br>')}</div>
            </div>
            <div class="card-meta-row">
                <div class="card-time">${timeStr}</div>
            </div>
            <div class="card-footer">
                ${buttonHTML}
            </div>
        `;
        
        // Attach telegram composite id for quick lookup & anchor behavior
        // API now returns tg_message_id as composite "chat_id:message_id"
        card.setAttribute('data-tg-id', msg.tg_message_id);
        messagesContainer.appendChild(card);

        // initialize copy button data attr if present
		const copyBtn = card.querySelector('.copy-btn');
		if (copyBtn) copyBtn.dataset.clipboardText = prefillMsg;

		// If this message is a reply, fetch preview asynchronously using composite id
		if (replyComposite) {
			const previewEl = card.querySelector('.reply-preview');
			if (previewEl) loadReplyPreview(replyComposite, previewEl);
		}
	});

	// Initialize ClipboardJS once (destroy previous instance to avoid duplicates)
    if (window.ClipboardJS) {
        if (clipboardInstance) {
            clipboardInstance.destroy();
        }
        clipboardInstance = new ClipboardJS('.copy-btn');

        clipboardInstance.on('success', (e) => {
            showToast('✅ Message copied to clipboard', 'success');
            try { e.clearSelection(); } catch (err) {}
        });

        clipboardInstance.on('error', (e) => {
            console.error('ClipboardJS error', e);
            showToast('❌ Failed to copy message', 'error');
        });
    } else {
        console.warn('ClipboardJS not loaded');
    }

    // update requests counter after DOM is rendered
    updateRequestsBadge();

    if (shouldStickOnNextRender) {
        stickFeedToBottom();
    }
    shouldStickOnNextRender = false;
}

// New helper: fetch original message and render a small clickable preview
async function loadReplyPreview(replyId, el) {
	try {
		const res = await fetch(`${API_BASE}/messages/${encodeURIComponent(replyId)}`);
		const data = await res.json();

		// If not found or marked deleted -> show deleted state
		if (data.status !== 'ok' || !data.message || data.message.is_deleted) {
			el.innerHTML = `<div class="reply-preview-inner">
				<div class="reply-sender">↳ Original</div>
				<div class="reply-snippet" style="color:var(--danger);">Original request deleted</div>
			</div>`;
			return;
		}

		const orig = data.message;
		const sender = escapeHtml(sanitizeName(orig.sender_name) || `User ${orig.sender_id}`);
		const snippet = escapeHtml((orig.message_text || '').substring(0, 120));
		el.innerHTML = `
			<div class="reply-preview-inner">
				<div class="reply-sender">↳ ${sender}</div>
				<div class="reply-snippet">${snippet}${(orig.message_text || '').length > 120 ? '…' : ''}</div>
				<button class="reply-open action-btn btn-secondary" type="button">Open original</button>
			</div>
		`;
		const openBtn = el.querySelector('.reply-open');
		if (openBtn) openBtn.addEventListener('click', () => scrollToMessage(replyId));
	} catch (err) {
		console.error('Failed to load reply preview', err);
		el.textContent = 'Failed to load reply';
	}
}

// Scroll to original card and highlight, fallback shows toast (no modal)
function scrollToMessage(tgMsgId) {
	const selector = `[data-tg-id="${tgMsgId}"]`;
	const el = messagesContainer.querySelector(selector);
	if (!el) {
		// Don't open modal; inform user original not available (deleted / outside list)
		showToast('Original request not available (deleted or out of view)', 'error');
		return;
	}

	const containerRect = messagesContainer.getBoundingClientRect();
	const elRect = el.getBoundingClientRect();
	const containerScrollTop = messagesContainer.scrollTop;
	const offset = (elRect.top + elRect.bottom) / 2 - (containerRect.top + containerRect.bottom) / 2;

	messagesContainer.scrollTo({
		top: containerScrollTop + offset,
		behavior: 'smooth'
	});

	el.classList.add('glow-highlight');
	setTimeout(() => el.classList.remove('glow-highlight'), 2200);
}

async function deleteMessage(tgMsgId) {
    if (!confirm('Delete this request?')) return;

    try {
        // always encode the composite id
        const res = await fetch(`${API_BASE}/messages/${encodeURIComponent(tgMsgId)}`, { method: 'DELETE' });
        if (res.ok) {
            console.log(`✅ Message ${tgMsgId} deleted`);
            showToast('✅ Request deleted', 'success');
            setTimeout(() => loadMessages(), 300);
        } else {
            showToast('Failed to delete request', 'error');
        }
    } catch (err) {
        console.error('Failed to delete message:', err);
        showToast('Connection error', 'error');
    }
}

// Clear all: use returned tg_message_id (composite) when deleting
async function clearAllMessages() {
    if (!confirm('🚨 Delete ALL requests? This cannot be undone!')) return;

    try {
        if (clearBtn) clearBtn.classList.add('loading');
        console.log('🗑️ Clearing all messages...');

        const res = await fetch(`${API_BASE}/messages`, { method: 'DELETE' });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            const deleted = Number(data.deleted || 0);
            showToast(deleted > 0 ? `✅ Deleted ${deleted} requests` : 'No requests to clear', 'success');
            console.log(`🗑️ Cleared ${deleted} messages`);
            setTimeout(() => loadMessages(), 300);
        } else {
            showToast('Failed to clear requests', 'error');
        }
    } catch (err) {
        console.error('Failed to clear messages:', err);
        showToast('Failed to clear requests', 'error');
    } finally {
        if (clearBtn) clearBtn.classList.remove('loading');
    }
}

function toggleAutoRefresh() {
    if (autoRefreshInterval) {
        stopAutoRefresh();
        showToast('🔴 Real-time updates disabled', 'success');
    } else {
        startAutoRefresh();
        showToast('🟢 Real-time updates enabled', 'success');
    }
}

function startAutoRefresh() {
    if (autoRefreshInterval) return;
    console.log('🔄 Real-time updates enabled');
    
    // Fast polling for messages
    autoRefreshInterval = setInterval(() => {
        loadMessages();
    }, REFRESH_INTERVAL);
    
    if (fabBtn) {
        fabBtn.classList.add('active');
        fabBtn.title = 'Real-time updates ON';
    }
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    console.log('⏸️ Real-time updates disabled');
    if (fabBtn) {
        fabBtn.classList.remove('active');
        fabBtn.title = 'Real-time updates OFF';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function copyPrefillMessage(message) {
    // Decode the escaped HTML entities first
    const decodedMessage = document.createElement('textarea');
    decodedMessage.innerHTML = message;
    const actualMessage = decodedMessage.value;
    
    // Try Clipboard API first (modern browsers)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(actualMessage)
            .then(() => {
                showToast('✅ Message copied to clipboard', 'success');
                console.log('📋 Message copied using Clipboard API');
            })
            .catch(err => {
                console.warn('Clipboard API failed, trying fallback...', err);
                copyFallback(actualMessage);
            });
    } else {
        // Fallback for older browsers
        copyFallback(actualMessage);
    }
}

function copyFallback(message) {
    try {
        // Create a temporary textarea
        const textarea = document.createElement('textarea');
        textarea.value = message;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        textarea.style.pointerEvents = 'none';
        document.body.appendChild(textarea);
        
        // Select and copy
        textarea.focus();
        textarea.select();
        
        const successful = document.execCommand('copy');
        
        if (successful) {
            showToast('✅ Message copied to clipboard', 'success');
            console.log('📋 Message copied using fallback method');
        } else {
            showToast('❌ Failed to copy message', 'error');
            console.error('execCommand copy failed');
        }
        
        // Clean up
        document.body.removeChild(textarea);
    } catch (err) {
        showToast('❌ Failed to copy message', 'error');
        console.error('Copy fallback error:', err);
    }
}

// add helpers to sanitize and compute display name
function sanitizeName(name) {
	// remove literal "None" and collapse whitespace
	if (!name) return '';
	return String(name).replace(/\bNone\b/g, '').replace(/\s+/g, ' ').trim();
}

function getDisplayName(msg) {
	// prefer sanitized sender_name, fall back to generic User {id}
	const raw = sanitizeName(msg.sender_name);
	if (raw) return raw;
	// try to use separate first/last if available
	const first = (msg.sender_first_name || '').trim();
	const last = (msg.sender_last_name || '').trim();
	if (first || last) return `${first}${last ? ' ' + last : ''}`.trim();
	return `User ${msg.sender_id}`;
}

// Debug helper: clears service workers + caches and reloads
function clearPwaCache() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations()
            .then(regs => regs.map(r => r.unregister()))
            .catch(()=>{});
    }
    if (window.caches && caches.keys) {
        caches.keys()
            .then(keys => Promise.all(keys.map(k => caches.delete(k))))
            .catch(()=>{});
    }
    console.log('PWA caches and service workers cleared — reloading');
    setTimeout(() => location.reload(), 250);
}
// Expose for quick console use
window.clearPwaCache = clearPwaCache;

// Cleanup
window.addEventListener('beforeunload', stopAutoRefresh);

// Disable browser scroll restore so we control first paint position.
if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
}
window.addEventListener('load', () => {
    if (hasAnchoredInitialView) return;
    hasAnchoredInitialView = true;
    stickFeedToBottom();
});

// -- add profile modal handlers --
const profileModal = document.getElementById('profileModal');
const profileBackdrop = document.getElementById('profileBackdrop');
const profileImage = document.getElementById('profileImage');
const profileName = document.getElementById('profileName');
const profileClose = document.getElementById('profileClose');
const profilePanel = profileModal ? profileModal.querySelector('.modal-panel') : null;
const profileFallback = document.getElementById('profileFallback');

function openProfileModal(src, name) {
	if (!profileModal) return;
	if (profilePanel) profilePanel.classList.remove('no-img');
	if (profileFallback) profileFallback.style.display = 'none';

	if (src) {
		profileImage.src = src;
		profileImage.onload = () => {
			if (profilePanel) profilePanel.classList.remove('no-img');
			if (profileFallback) profileFallback.style.display = 'none';
		};
		profileImage.onerror = () => {
			if (profilePanel) profilePanel.classList.add('no-img');
			if (profileFallback) {
				profileFallback.textContent = (name || '').split(' ').map(n => n[0]||'').slice(0,2).join('').toUpperCase();
				profileFallback.style.display = 'flex';
			}
			profileImage.src = '';
		};
	} else {
		if (profilePanel) profilePanel.classList.add('no-img');
		if (profileFallback) {
			profileFallback.textContent = (name || '').split(' ').map(n => n[0]||'').slice(0,2).join('').toUpperCase();
			profileFallback.style.display = 'flex';
		}
		profileImage.src = '';
	}

	if (profileName) profileName.textContent = name || '';
	profileModal.setAttribute('aria-hidden', 'false');
}

function closeProfileModal() {
	if (!profileModal) return;
	profileModal.setAttribute('aria-hidden', 'true');
	if (profileImage) profileImage.src = '';
	if (profileFallback) profileFallback.style.display = 'none';
	if (profilePanel) profilePanel.classList.remove('no-img');
}

// delegated click handler for avatars
if (messagesContainer) {
	messagesContainer.addEventListener('click', (ev) => {
		const el = ev.target.closest && ev.target.closest('.avatar-clickable');
		if (!el) return;
		const src = el.dataset.avatar || '';
		const name = el.dataset.name || '';
		openProfileModal(src, name);
	});
}

// close handlers
if (profileBackdrop) profileBackdrop.addEventListener('click', closeProfileModal);
if (profileClose) profileClose.addEventListener('click', closeProfileModal);
document.addEventListener('keydown', (e) => {
	if (e.key === 'Escape') closeProfileModal();
});

// Delegated handler: capture "Contact" clicks and store to history before navigating
messagesContainer && messagesContainer.addEventListener('click', async (ev) => {
    const a = ev.target.closest && ev.target.closest('a.action-btn');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    // only capture external contact links (t.me or tg://user)
    if (href.startsWith('https://t.me/') || href.startsWith('tg://user') || href.startsWith('https://t.me/share/')) {
        // find the message card to extract metadata
        const card = a.closest('[data-tg-id]');
        const tg_id = card ? card.getAttribute('data-tg-id') : null;
        // try to extract sender name and message text from DOM
        const senderEl = card ? card.querySelector('.sender-name') : null;
        const textEl = card ? card.querySelector('.message-text') : null;
        const data = {
            tg_message_id: tg_id,
            chat_id: tg_id && tg_id.includes(':') ? tg_id.split(':')[0] : null,
            sender_name: senderEl ? senderEl.textContent.trim() : null,
            contact_url: href,
            message_text: textEl ? textEl.textContent.trim() : ''
        };
        // non-blocking POST but attempt to complete before navigation
        try {
            await fetch(`${API_BASE}/history`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        } catch (err) {
            console.warn('Failed to record history', err);
        }
        // allow navigation (open in new tab if anchor has target)
        // if anchor has target="_blank", let default happen; otherwise open
        if (!a.target || a.target === '') {
            ev.preventDefault();
            window.open(href, '_blank');
        }
    }
});

function updateRequestsBadge() {
    if (!requestsBadge) return;
    const count = document.querySelectorAll('#messagesContainer .message-card').length;
    requestsBadge.textContent = String(count);
    requestsBadge.style.display = count > 0 ? 'inline-block' : 'none';
}
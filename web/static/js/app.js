// Alpine.js global store and components for BOSS招聘助手

// ============================================================================
// Toast Notification System (must be defined early)
// ============================================================================

/**
 * Toast notification helper
 * Displays temporary notification messages in the top-right corner
 */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    const colors = {
        info: 'bg-blue-600',
        success: 'bg-green-600',
        error: 'bg-red-600',
        warning: 'bg-yellow-600'
    };
    toast.className = `${colors[type] || colors.info} text-white px-6 py-3 rounded-lg shadow-lg mb-2 animate-fade-in`;
    toast.textContent = message;
    
    const container = document.getElementById('toast-container');
    if (container) {
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('animate-fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 8000);
    }
}

// Expose showToast globally
window.showToast = showToast;

/**
 * Browser notification helper using Chrome's Web Notifications API
 * Shows system-level notifications to alert HR when messages are sent
 */
async function showBrowserNotification(title, body, icon = null) {
    // Request permission if not already granted
    if (Notification.permission === 'default') {
        await Notification.requestPermission();
    }
    
    // Only show notification if permission is granted
    if (Notification.permission === 'granted') {
        const notification = new Notification(title, {
            body: body,
            icon: icon || 'https://www.zhipin.com/favicon.ico',
            badge: icon || 'https://www.zhipin.com/favicon.ico',
            tag: 'bosszhipin-message', // Use tag to replace previous notifications
            requireInteraction: false, // Auto-close after a few seconds
        });
        
        // Auto-close after 5 seconds
        setTimeout(() => {
            notification.close();
        }, 5000);
        
        // Handle click to focus window
        notification.onclick = () => {
            window.focus();
            notification.close();
        };
        
        return true;
    }
    
    return false;
}

// Expose showBrowserNotification globally
window.showBrowserNotification = showBrowserNotification;

/**
 * Generate a simple hash from a string
 * Used to track notification content changes
 */
function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    return Math.abs(hash).toString(36);
}

/**
 * Check if a notification should be shown based on content hash
 * @param {string} contentKey - Unique key for this notification (e.g., 'homepage-warning', 'candidates-troubleshooting')
 * @param {string} content - The notification content text
 * @returns {boolean} - True if notification should be shown (content is new or changed)
 */
function shouldShowNotification(contentKey, content) {
    const currentHash = simpleHash(content);
    const storedHash = localStorage.getItem(`${contentKey}_hash`);
    
    // Show if hash is different (new or changed content)
    return storedHash !== currentHash;
}

/**
 * Mark a notification as acknowledged
 * @param {string} contentKey - Unique key for this notification
 * @param {string} content - The notification content text
 */
function acknowledgeNotification(contentKey, content) {
    const currentHash = simpleHash(content);
    localStorage.setItem(`${contentKey}_hash`, currentHash);
}

// Expose notification functions globally
window.simpleHash = simpleHash;
window.shouldShowNotification = shouldShowNotification;
window.acknowledgeNotification = acknowledgeNotification;

/**
 * Confirm modal helper using Alpine.js store (minimal JS, matching index.html pattern)
 * Returns a Promise that resolves to true/false
 */
function showConfirm(message, title = '确认') {
    return new Promise((resolve) => {
        // Use Alpine store to manage modal state
        if (!window.Alpine) {
            console.error('Alpine.js not loaded');
            resolve(false);
            return;
        }
        
        const store = Alpine.store('confirmModal');
        if (!store) {
            // Initialize store if it doesn't exist
            Alpine.store('confirmModal', {
                show: false,
                message: '',
                title: '',
                resolve: null
            });
        }
        
        const modalStore = Alpine.store('confirmModal');
        modalStore.message = message;
        modalStore.title = title;
        modalStore.resolve = resolve;
        modalStore.show = true;
    });
}

// Expose showConfirm globally
window.showConfirm = showConfirm;

/**
 * Special confirm for deleting the last version (green cancel, red confirm)
 * Returns a Promise that resolves to true/false
 */
function showDeleteJobConfirm(message, title = '删除岗位') {
    return new Promise((resolve) => {
        if (!window.Alpine) {
            console.error('Alpine.js not loaded');
            resolve(false);
            return;
        }
        
        const store = Alpine.store('deleteJobModal');
        if (!store) {
            Alpine.store('deleteJobModal', {
                show: false,
                message: '',
                title: '',
                resolve: null
            });
        }
        
        const modalStore = Alpine.store('deleteJobModal');
        modalStore.message = message;
        modalStore.title = title;
        modalStore.resolve = resolve;
        modalStore.show = true;
    });
}

// Expose showDeleteJobConfirm globally
window.showDeleteJobConfirm = showDeleteJobConfirm;

/**
 * Show loading indicator
 */
function showLoading(message = '处理中...') {
    const indicator = document.getElementById('global-loading');
    if (indicator) {
        const textEl = indicator.querySelector('span');
        if (textEl) {
            textEl.textContent = message;
        } else {
            const span = document.createElement('span');
            span.className = 'font-medium';
            span.textContent = message;
            indicator.appendChild(span);
        }
        indicator.classList.add('htmx-request');
        indicator.style.display = 'flex';
    }
}

/**
 * Hide loading indicator
 */
function hideLoading() {
    const indicator = document.getElementById('global-loading');
    if (indicator) {
        indicator.classList.remove('htmx-request');
    }
}

// Expose loading functions globally
window.showLoading = showLoading;
window.hideLoading = hideLoading;

document.addEventListener('alpine:init', () => {
    // Global application state
    Alpine.store('app', {
        currentJob: null,
        currentAssistant: null,
        jobs: [],
        assistants: [],
        
        setJob(job) {
            this.currentJob = job;
            localStorage.setItem('currentJob', JSON.stringify(job));
        },
        
        setAssistant(assistant) {
            this.currentAssistant = assistant;
            localStorage.setItem('currentAssistant', JSON.stringify(assistant));
        },
        
        loadFromStorage() {
            const job = localStorage.getItem('currentJob');
            const assistant = localStorage.getItem('currentAssistant');
            if (job) this.currentJob = JSON.parse(job);
            if (assistant) this.currentAssistant = JSON.parse(assistant);
        }
    });
    
    // Confirm modal store (matching index.html pattern)
    Alpine.store('confirmModal', {
        show: false,
        message: '',
        title: '确认',
        resolve: null,
        
        confirm() {
            if (this.resolve) {
                this.resolve(true);
                this.resolve = null;
            }
            this.show = false;
        },
        
        cancel() {
            if (this.resolve) {
                this.resolve(false);
                this.resolve = null;
            }
            this.show = false;
        }
    });
    
    // Delete job modal store (for deleting last version - green cancel, red confirm)
    Alpine.store('deleteJobModal', {
        show: false,
        message: '',
        title: '删除岗位',
        resolve: null,
        
        confirm() {
            if (this.resolve) {
                this.resolve(true);
                this.resolve = null;
            }
            this.show = false;
        },
        
        cancel() {
            if (this.resolve) {
                this.resolve(false);
                this.resolve = null;
            }
            this.show = false;
        }
    });
    
    // Version update modal store
    Alpine.store('versionUpdateModal', {
        show: false,
        title: '新版本可用',
        message: '',
        currentCommit: null,
        remoteCommit: null,
        currentBranch: null,
        repoUrl: null,
        
        dismiss() {
            // Store dismissed version in localStorage
            if (this.remoteCommit) {
                localStorage.setItem('dismissedVersion', this.remoteCommit);
            }
            this.show = false;
        },
        
        update() {
            // Open repository URL in new tab
            if (this.repoUrl) {
                window.open(this.repoUrl, '_blank');
            } else {
                // Fallback: show message
                showToast('请手动运行 git pull 更新代码', 'info');
            }
            this.dismiss();
        }
    });
    
    // Load state on init
    Alpine.store('app').loadFromStorage();
});

// Automation control component
function automationControl() {
    return {
        events: [],
        eventSource: null,
        isRunning: false,
        isPaused: false,
        
        initSSE() {
            this.connectSSE();
        },

        connectSSE() {
            if (this.eventSource) {
                this.eventSource.close();
            }
            
            this.eventSource = new EventSource('/automation/stream');
            
            this.eventSource.onmessage = (e) => {
                const event = JSON.parse(e.data);
                this.events.push(event);
                
                // Auto-scroll to bottom
                this.$nextTick(() => {
                    const log = document.getElementById('event-log');
                    if (log) {
                        log.scrollTop = log.scrollHeight;
                    }
                });
                
                // Keep only last 1000 events
                if (this.events.length > 1000) {
                    this.events = this.events.slice(-1000);
                }
            };
            
            this.eventSource.onerror = (e) => {
                console.error('SSE Error:', e);
                this.isRunning = false;
            };
        },
        
        closeSSE() {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
        },
        
        clearEvents() {
            this.events = [];
        },
        
        getEventClass(level) {
            const classes = {
                'info': 'event-info',
                'warning': 'event-warning',
                'error': 'event-error',
                'success': 'event-success'
            };
            return classes[level] || 'event-info';
        }
    };
}

// Candidate tabs component
function candidateTabs() {
    return {
        activeTab: 'recommend',
        loading: false,
        
        init() {
            // Read URL parameters on page load
            this.restoreFromURL();
            
            // Listen for browser back/forward buttons
            window.addEventListener('popstate', () => {
                this.restoreFromURL();
            });
        },
        
        restoreFromURL() {
            const urlParams = new URLSearchParams(window.location.search);
            
            // Set active tab from URL
            const tab = urlParams.get('tab');
            if (tab && ['recommend', 'greet', 'chat', 'followup'].includes(tab)) {
                this.activeTab = tab;
            }
            
            // Set thresholds from URL
            const thresholdChat = urlParams.get('threshold_chat');
            if (thresholdChat) {
                const chatInput = document.getElementById('threshold-chat');
                if (chatInput) chatInput.value = thresholdChat;
            }
            
            const thresholdBorderline = urlParams.get('threshold_borderline');
            if (thresholdBorderline) {
                const borderlineInput = document.getElementById('threshold-borderline');
                if (borderlineInput) borderlineInput.value = thresholdBorderline;
            }
            
            const thresholdSeek = urlParams.get('threshold_seek');
            if (thresholdSeek) {
                const seekInput = document.getElementById('threshold-seek');
                if (seekInput) seekInput.value = thresholdSeek;
            }
            
            // Set job selector from URL (after jobs are loaded)
            const jobId = urlParams.get('job_id');
            if (jobId) {
                // Wait for job selector to be populated
                const checkJobSelector = setInterval(() => {
                    const jobSelector = document.getElementById('job-selector');
                    if (jobSelector && jobSelector.options.length > 1) {
                        // Check if the job_id exists in options
                        for (let option of jobSelector.options) {
                            if (option.value === jobId) {
                                jobSelector.value = jobId;
                                clearInterval(checkJobSelector);
                                break;
                            }
                        }
                        clearInterval(checkJobSelector);
                    }
                }, 100);
                
                // Stop checking after 5 seconds
                setTimeout(() => clearInterval(checkJobSelector), 5000);
            }
            
            // Set limit from URL
            const limit = urlParams.get('limit');
            if (limit) {
                const limitInput = document.getElementById('limit-input');
                if (limitInput) limitInput.value = limit;
            }
        },
        
        updateURL() {
            const params = new URLSearchParams();
            
            // Add tab
            params.set('tab', this.activeTab);
            
            // Add thresholds
            const thresholdChat = document.getElementById('threshold-chat')?.value;
            if (thresholdChat) params.set('threshold_chat', thresholdChat);
            
            const thresholdBorderline = document.getElementById('threshold-borderline')?.value;
            if (thresholdBorderline) params.set('threshold_borderline', thresholdBorderline);
            
            const thresholdSeek = document.getElementById('threshold-seek')?.value;
            if (thresholdSeek) params.set('threshold_seek', thresholdSeek);
            
            // Add job_id
            const jobSelector = document.getElementById('job-selector');
            const jobId = jobSelector?.value;
            if (jobId && jobId !== '加载中...') {
                params.set('job_id', jobId);
            }
            
            // Add limit
            const limitInput = document.getElementById('limit-input');
            const limit = limitInput?.value;
            if (limit) {
                params.set('limit', limit);
            }
            
            // Update URL without page reload
            const newURL = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
            window.history.pushState({}, '', newURL);
        },
        
        switchTab(tab) {
            this.activeTab = tab;
            // Reset selected candidate
            // Clear list when switching tabs
            const list = document.getElementById('candidate-list');
            if (list) {
                list.innerHTML = '';
                // Re-add initial message
                const initialMsg = document.createElement('div');
                initialMsg.id = 'initial-message';
                initialMsg.className = 'text-center text-gray-500 py-12';
                initialMsg.textContent = '点击下方"查询候选人"按钮加载数据';
                list.appendChild(initialMsg);
            }
            // Hide batch analyze button when switching tabs
            const batchBtn = document.getElementById('batch-analyze-btn');
            if (batchBtn) {
                batchBtn.classList.add('hidden');
            }
            // Update URL
            this.updateURL();
        },
        
        loadCandidates() {
            
            this.loading = true;
            
            const jobSelector = document.getElementById('job-selector');
            const job_id = jobSelector?.value || jobSelector?.options[0]?.value;
            const job_title = jobSelector?.selectedOptions[0]?.getAttribute("data-title");
            
            // Check if job title is valid
            if (!job_title || job_title === '加载中...') {
                console.error('Job title not loaded yet');
                this.loading = false;
                showToast('请等待岗位列表加载完成后再查询', 'warning');
                return;
            }
            
            let mode, chat_type;
            if (this.activeTab === 'recommend') {
                mode = 'recommend';
                chat_type = '';
            } else {
                mode = this.activeTab; // Use the tab name directly as mode
                const tabMap = {
                    'greet': '新招呼',
                    'chat': '沟通中',
                    'followup': '牛人已读未回'
                };
                chat_type = tabMap[this.activeTab] || '新招呼';
            }
            
            // Get limit from input
            const limitInput = document.getElementById('limit-input');
            const limit = limitInput?.value || '50';

            const params = new URLSearchParams({
                mode: mode,
                chat_type: chat_type,
                job_applied: job_title,
                job_id: job_id,
                limit: limit
            });
            
            console.log('Loading candidates, activeTab:', this.activeTab, 'params:', params);
            const url = `/candidates/list?${params.toString()}`;
            console.log('Fetching:', url);
            
            const candidateList = document.getElementById('candidate-list');
            
            // Clear all non-candidate content (error messages, initial messages, empty messages)
            // Keep only candidate cards if we're appending
            const initialMsg = document.getElementById('initial-message');
            if (initialMsg) {
                initialMsg.remove();
            }
            const emptyMsg = document.getElementById('empty-message');
            if (emptyMsg) {
                emptyMsg.remove();
            }
            
            // Remove any error messages (divs with text-red-500 or containing error indicators)
            const errorMessages = candidateList.querySelectorAll('.text-red-500, [class*="error"], [class*="失败"]');
            errorMessages.forEach(msg => {
                // Only remove if it's not a candidate card
                if (!msg.closest('.candidate-card')) {
                    msg.remove();
                }
            });
            
            // Use a custom handler to detect errors and handle swap accordingly
            fetch(url)
                .then(async (response) => {
                    const html = await response.text();
                    const candidateList = document.getElementById('candidate-list');
                    
                    // Check if response is an error message
                    if (!response.ok) {
                        debugger;
                        // Error: replace list content with error message
                        candidateList.innerHTML = html;
                        this.loading = false;
                        showToast('获取候选人列表失败，请重试', 'error');
                        return;
                    }
                    
                    // Success: replace the entire list with new candidate cards
                    // Use the HTML response directly
                    candidateList.innerHTML = html;
                    
                    // Tell HTMX to process the new content
                    htmx.process(candidateList);
                    
                    const loadedCount = candidateList.querySelectorAll('.candidate-card').length;
                    console.log(`Loaded ${loadedCount} candidate cards`);
                    
                    this.loading = false;
                    
                    // Count how many candidates are in the list now - use a fresh query after all updates
                    // Use requestAnimationFrame to ensure DOM is updated before counting
                    const self = this;
                    requestAnimationFrame(() => {
                        const count = candidateList.querySelectorAll('.candidate-card').length;
                        // Show/hide batch analyze button
                        const batchBtn = document.getElementById('batch-analyze-btn');
                        if (batchBtn) {
                            if (count > 0) {
                                batchBtn.classList.remove('hidden');
                                batchBtn.disabled = false;
                            } else {
                                batchBtn.classList.add('hidden');
                            }
                        }
                        
                        if (count === 0) {
                            // Show empty state message
                            const emptyMsg = document.createElement('div');
                            emptyMsg.id = 'empty-message';
                            emptyMsg.className = 'text-center text-gray-500 py-12';
                            emptyMsg.innerHTML = `
                                <div class="space-y-2">
                                    <p class="text-lg">😔 未找到符合条件的候选人</p>
                                    <p class="text-sm">请尝试切换标签或岗位</p>
                                </div>
                            `;
                            candidateList.appendChild(emptyMsg);
                            showToast('未找到候选人', 'warning');
                        } else {
                            // Remove empty message if it exists
                            const emptyMsg = document.getElementById('empty-message');
                            if (emptyMsg) {
                                emptyMsg.remove();
                            }
                            
                            // Show toast with count
                            showToast(`加载完成，共 ${count} 个候选人`, 'success');
                        }
                    });
                })
                .catch((err) => {
                    console.error('Failed:', err);
                    this.loading = false;
                    const candidateList = document.getElementById('candidate-list');
                    candidateList.innerHTML = `
                        <div class="text-center text-red-500 py-12">
                            <p class="text-lg">❌ 请求失败</p>
                            <p class="text-sm mt-2">${err.message}</p>
                        </div>
                    `;
                    showToast('加载失败: ' + err.message, 'error');
                });
        }
    };
}

// Global function for HTMX events to call updateURL
window.updateCandidateURL = function() {
    // First, restore job selector value from URL if it exists
    const urlParams = new URLSearchParams(window.location.search);
    const jobId = urlParams.get('job_id');
    if (jobId) {
        const jobSelector = document.getElementById('job-selector');
        if (jobSelector && jobSelector.options.length > 1) {
            // Check if the job_id exists in options
            for (let option of jobSelector.options) {
                if (option.value === jobId) {
                    jobSelector.value = jobId;
                    break;
                }
            }
        }
    }
    
    // Find the Alpine component instance
    const candidateTabsElement = document.querySelector('[x-data*="candidateTabs"]');
    if (candidateTabsElement && candidateTabsElement._x_dataStack) {
        const component = candidateTabsElement._x_dataStack[0];
        if (component && component.updateURL) {
            component.updateURL();
        }
    }
};

// ============================================================================
// Global HTMX Loading & Error Handling
// ============================================================================

// Show loading indicator before any HTMX request
// Track active fetch requests for loading indicator
let activeFetchRequests = 0;

// Intercept fetch to show loading indicator
const originalFetch = window.fetch;
window.fetch = function(...args) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        activeFetchRequests++;
        loadingIndicator.classList.add('htmx-request');
        loadingIndicator.style.display = 'flex';
    }
    
    return originalFetch.apply(this, args)
        .then(response => {
            activeFetchRequests--;
            if (activeFetchRequests <= 0) {
                activeFetchRequests = 0;
                if (loadingIndicator) {
                    loadingIndicator.classList.remove('htmx-request');
                }
            }
            return response;
        })
        .catch(error => {
            activeFetchRequests--;
            if (activeFetchRequests <= 0) {
                activeFetchRequests = 0;
                if (loadingIndicator) {
                    loadingIndicator.classList.remove('htmx-request');
                }
            }
            throw error;
        });
};

// HTMX request handlers (for HTMX-specific requests)
document.body.addEventListener('htmx:beforeRequest', function(event) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.add('htmx-request');
        loadingIndicator.style.display = 'flex';
    }
});

// Hide loading indicator after any HTMX request completes
document.body.addEventListener('htmx:afterRequest', function(event) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator && activeFetchRequests === 0) {
        loadingIndicator.classList.remove('htmx-request');
    }
});

// Global HTMX error handler to catch swap errors
// Global HTMX error handler to catch swap errors
// Only handle errors that weren't already handled by local listeners (e.g., in processAllCandidates)
document.body.addEventListener('htmx:responseError', function(evt) {
    // Skip if event propagation was stopped (already handled by local listener)
    if (evt.cancelBubble) {
        return;
    }
    
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.remove('htmx-request');
    }
    console.error('HTMX response error:', evt.detail);
    const errorMsg = evt.detail?.error || evt.detail?.message || '请求失败';
    showToast(errorMsg, 'error');
});

// Catch HTMX swap errors (like insertBefore on null)
document.body.addEventListener('htmx:swapError', function(evt) {
    console.error('HTMX swap error:', evt.detail);
    const target = evt.detail?.target;
    if (target) {
        console.error('Target element:', target, 'isConnected:', target.isConnected);
    }
    // Don't show toast for swap errors as they're often handled by htmxAjaxPromise
});

// Catch general HTMX errors
document.body.addEventListener('htmx:sendError', function(evt) {
    console.error('HTMX send error:', evt.detail);
    // Only show toast if not already handled by htmxAjaxPromise
    if (!evt.detail?.handled) {
        showToast('网络请求失败，请重试', 'error');
    }
});

// Handle custom HX-Trigger events for toast notifications
document.body.addEventListener('showToast', function(evt) {
    if (evt.detail && evt.detail.message) {
        showToast(evt.detail.message, evt.detail.type || 'info');
    }
});

// ============================================================================
// Candidate Selection Management
// ============================================================================

// Visual state management for candidate cards
document.body.addEventListener('htmx:beforeRequest', function(event) {
    // Check if this is a candidate card click
    if (!event.detail.elt.classList.contains('candidate-card')) {
        return;  // Not a candidate card, allow request normally
    }
    
    // Remove selected state from all cards
    document.querySelectorAll('.candidate-card').forEach(card => {
        card.classList.remove('bg-blue-50', 'border-blue-500', 'ring-2', 'ring-blue-300');
        card.classList.add('border-gray-200');
    });
    
    // Add selected state to clicked card
    event.detail.elt.classList.remove('border-gray-200');
    event.detail.elt.classList.add('bg-blue-50', 'border-blue-500', 'ring-2', 'ring-blue-300');
    
    // Scroll card into view in the left panel
    event.detail.elt.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
});

// ============================================================================
// Unified API Error Handler
// ============================================================================

/**
 * Unified error handler for fetch() calls to FastAPI
 * 
 * Handles FastAPI validation errors (422) and other server errors,
 * providing consistent error messages across the application.
 * 
 * @param {Response} response - Fetch Response object
 * @returns {Promise<any>} Parsed JSON response data
 * @throws {Error} Error with descriptive message
 * 
 * @example
 * fetch('/api/endpoint', { method: 'POST', body: formData })
 *     .then(handleApiResponse)
 *     .then(data => console.log('Success:', data))
 *     .catch(err => showToast(`Error: ${err.message}`, 'error'));
 */
window.handleApiResponse = async function handleApiResponse(response) {
    if (response.ok) {
        return await response.json();
    }
    
    // Try to parse JSON error body, fallback to status text if parsing fails
    const errorData = await response.json().catch(() => null);
    
    // 422: ValidationError or custom detail structure
    if (response.status === 422 && errorData?.detail) {
        const errors = errorData.detail
            .map(e => `${e.loc.join('.')}: ${e.msg}`)
            .join(', ');
        throw new Error(`Validation failed: ${errors}`);
    }
    
    // Other server errors
    const message = errorData?.error || errorData?.detail || response.statusText;
    throw new Error(`Server error (${response.status}): ${message}`);
}

/**
 * Wrap htmx.ajax to return a Promise that resolves when swap completes
 * 
 * @param {string} method - HTTP method (GET, POST, etc.)
 * @param {string} url - URL to request
 * @param {object} options - HTMX options (must include 'target' selector)
 * @returns {Promise<string>} Promise that resolves with target element's text content
 * 
 * @example
 * await htmxAjaxPromise('POST', '/candidates/fetch-online-resume', {
 *     target: '#resume-online-container',
 *     swap: 'innerHTML',
 *     values: { candidate_id: '123' }
 * });
 */
window.htmxAjaxPromise = function htmxAjaxPromise(method, url, options) {
    return new Promise((resolve, reject) => {
        const target = document.querySelector(options.target);
        if (!target) {
            reject(new Error(`Target should be provided to use htmxAjaxPromise: ${options} or use fetch instead`));
            return;
        }
        
        // Listen for swap completion
        const afterSwap = (evt) => {
            target.removeEventListener('htmx:afterSwap', afterSwap);
            target.removeEventListener('htmx:responseError', onError);
            resolve(target.textContent.trim());
        };
        
        const onError = (evt) => {
            target.removeEventListener('htmx:afterSwap', afterSwap);
            target.removeEventListener('htmx:responseError', onError);
            const errorMsg = evt.detail?.error || evt.detail?.message || 'HTMX request failed';
            reject(new Error(errorMsg));
        };
        
        target.addEventListener('htmx:afterSwap', afterSwap, { once: true });
        target.addEventListener('htmx:responseError', onError, { once: true });
        
        // Trigger the ajax call
        htmx.ajax(method, url, options);
    });
};

// ============================================================================
// Helper functions to disable/enable candidate cards
// ============================================================================

function disableAllCards() {
    const cards = document.querySelectorAll('.candidate-card');
    cards.forEach(card => {
        card.style.pointerEvents = 'none';
        card.style.opacity = '0.6';
    });
    console.log('disabled All Cards');
}

function enableAllCards() {
    const cards = document.querySelectorAll('.candidate-card');
    cards.forEach(card => {
        card.style.pointerEvents = '';
        card.style.opacity = '';
    });
    console.log('enabled All Cards');
}
// 将函数暴露到 window 对象
window.disableAllCards = disableAllCards;
window.enableAllCards = enableAllCards;

// ============================================================================
// Batch Processing Functions
// ============================================================================

// Global flags for batch processing control
window.batchProcessingActive = false;
window.stopBatchProcessing = false;

/**
 * Check if currently on the candidate page
 */
function isOnCandidatePage() {
    return window.location.pathname.includes('/candidates') || 
           window.location.pathname === '/candidates';
}

/**
 * Check if batch processing should be cancelled
 * Returns true if we should stop processing
 * Only checks page navigation, not tab visibility
 */
function shouldCancelBatchProcessing() {
    // Check if not on candidate page
    if (!isOnCandidatePage()) {
        return true;
    }
    
    // Don't cancel based on tab visibility - allow switching tabs
    return false;
}

/**
 * Process all candidate cards sequentially
 */
window.processAllCandidates = async function processAllCandidates() {
    const cards = document.querySelectorAll('.candidate-card');
    if (cards.length === 0) {
        showToast('没有找到候选人', 'warning');
        return;
    }
    
    // Find the currently selected card (has blue selection classes)
    // If found, start from next; otherwise start from beginning
    let startIndex = 0;
    const selectedCard = Array.from(cards).find(card => 
        card.classList.contains('bg-blue-50') || 
        card.classList.contains('border-blue-500')
    );
    if (selectedCard) {
        const selectedIndex = Array.from(cards).indexOf(selectedCard);
        startIndex = selectedIndex + 1; // Start from next card
        if (startIndex >= cards.length) {
            showToast('当前已是最后一个候选人，将从第一个开始', 'info');
            startIndex = 0;
        }
    }
    
    const total = cards.length;
    const remaining = total - startIndex;
    let processed = 0;
    let failed = 0;
    
    // Set batch processing flag
    window.batchProcessingActive = true;
    window.stopBatchProcessing = false;
    
    // Disable all candidate cards
    disableAllCards();
    
    // Update button to stop button
    const batchBtn = document.getElementById('batch-analyze-btn');
    if (batchBtn) {
        batchBtn.disabled = false;
        batchBtn.textContent = '⏸ 停止处理';
        batchBtn.onclick = stopBatchProcessingHandler;
        batchBtn.classList.remove('bg-purple-600', 'hover:bg-purple-700');
        batchBtn.classList.add('bg-red-600', 'hover:bg-red-700');
    }
    
    if (startIndex > 0) {
        showToast(`开始批量处理 ${remaining} 个候选人 (从第 ${startIndex + 1} 个开始)`, 'info');
    } else {
        showToast(`开始批量处理 ${total} 个候选人`, 'info');
    }
    
    for (let i = startIndex; i < cards.length; i++) {
        // Check if user requested stop
        if (window.stopBatchProcessing) {
            showToast(`批量处理已停止 (${processed}/${total} 完成)`, 'warning');
            break;
        }
        
        // Check if we should cancel due to page/tab change
        if (shouldCancelBatchProcessing()) {
            // Only show toast if it's a page navigation, not tab visibility change
            if (!isOnCandidatePage()) {
                showToast(`批量处理已取消 (已离开候选人页面)`, 'warning');
            }
            window.stopBatchProcessing = true;
            break;
        }
        
        const card = cards[i];
        const cardData = JSON.parse(card.getAttribute('hx-vals'));
        const name = cardData.name || `候选人 ${i + 1}`;
        const currentPosition = i + 1;
        
        showToast(`正在处理候选人 ${currentPosition}/${total}: ${name}`, 'info');
        
        try {
            const detailPane = document.getElementById('detail-pane');
            if (!detailPane) {
                throw new Error('Detail pane not found');
            }
            
            // Set up event listeners BEFORE triggering HTMX click
            // This ensures we catch the event even if process_candidate() completes quickly
            const processingPromise = new Promise((resolve, reject) => {
                const timeout = setTimeout(() => {
                    document.removeEventListener('candidate:processing-complete', onComplete);
                    document.removeEventListener('candidate:processing-error', onError);
                    reject(new Error('Processing timeout (180s)'));
                }, 180000); // 180 second timeout
                
                const onComplete = (event) => {
                    clearTimeout(timeout);
                    document.removeEventListener('candidate:processing-complete', onComplete);
                    document.removeEventListener('candidate:processing-error', onError);
                    resolve(event.detail);
                };
                
                const onError = (event) => {
                    clearTimeout(timeout);
                    document.removeEventListener('candidate:processing-complete', onComplete);
                    document.removeEventListener('candidate:processing-error', onError);
                    // Stop batch processing on processing error
                    window.stopBatchProcessing = true;
                    reject(new Error(event.detail.error || 'Processing failed'));
                };
                
                document.addEventListener('candidate:processing-complete', onComplete, { once: true });
                document.addEventListener('candidate:processing-error', onError, { once: true });
            });
            
            // Wait for HTMX swap to complete
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => {
                    detailPane.removeEventListener('htmx:afterSwap', onSwap);
                    detailPane.removeEventListener('htmx:responseError', onError);
                    reject(new Error('HTMX swap timeout'));
                }, 10000); // 10 second timeout for swap
                
                const onSwap = () => {
                    clearTimeout(timeout);
                    detailPane.removeEventListener('htmx:afterSwap', onSwap);
                    detailPane.removeEventListener('htmx:responseError', onError);
                    // Wait a bit for DOM to be ready
                    setTimeout(resolve, 200);
                };
                
                const onError = (evt) => {
                    clearTimeout(timeout);
                    detailPane.removeEventListener('htmx:afterSwap', onSwap);
                    detailPane.removeEventListener('htmx:responseError', onError);
                    // Stop event propagation to prevent global handler from catching it
                    evt.stopPropagation();
                    reject(new Error(evt.detail.error || 'HTMX request failed'));
                };
                
                detailPane.addEventListener('htmx:afterSwap', onSwap, { once: true });
                detailPane.addEventListener('htmx:responseError', onError, { once: true });
                
                // Scroll card into view before triggering click
                card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
                
                // Trigger HTMX click
                htmx.trigger(card, 'click');
            });
            
            // Wait for process_candidate() to complete
            await processingPromise;
            
            // Check again after processing completes
            if (shouldCancelBatchProcessing()) {
                // Only show toast if it's a page navigation, not tab visibility change
                if (!isOnCandidatePage()) {
                    showToast(`批量处理已取消 (已离开候选人页面)`, 'warning');
                }
                window.stopBatchProcessing = true;
                break;
            }
            
            processed++;
            showToast(`✅ ${name} 处理完成 (${processed}/${total})`, 'success');
        } catch (error) {
            failed++;
            console.error(`Failed to process candidate ${i + 1}:`, error);
            showToast(`❌ ${name} 处理失败: ${error.message}`, 'error');
            
            // Stop batch processing if processing error occurred
            if (window.stopBatchProcessing) {
                showToast(`批量处理已停止 (${processed}/${total} 完成, ${failed} 失败)`, 'warning');
                break;
            }
            // Otherwise continue to next candidate
        }
    }
    
    // Re-enable candidate cards
    enableAllCards();
    
    // Reset batch processing flag
    window.batchProcessingActive = false;
    window.stopBatchProcessing = false;
    
    // Reset buttons
    if (batchBtn) {
        batchBtn.disabled = false;
        batchBtn.textContent = '全部分析';
        batchBtn.onclick = processAllCandidates;
        batchBtn.classList.remove('bg-red-600', 'hover:bg-red-700');
        batchBtn.classList.add('bg-purple-600', 'hover:bg-purple-700');
    }
    
    // Final summary
    const summary = `批量处理完成: 成功 ${processed}/${total}, 失败 ${failed}`;
    showToast(summary, processed === total ? 'success' : 'warning');
}

function stopBatchProcessingHandler() {
    window.stopBatchProcessing = true;
    const batchBtn = document.getElementById('batch-analyze-btn');
    if (batchBtn) {
        batchBtn.disabled = true;
        batchBtn.textContent = '正在停止...';
    }
    showToast('正在停止批量处理...', 'info');
}

// ============================================================================
// Batch Processing Cancellation Listeners
// ============================================================================

// Don't cancel batch processing when tab becomes hidden - allow switching tabs
// Batch processing will continue in the background

// Cancel batch processing when navigating away from candidate page
// Check after HTMX swaps complete
document.body.addEventListener('htmx:afterSwap', () => {
    if (window.batchProcessingActive && !isOnCandidatePage()) {
        window.stopBatchProcessing = true;
        showToast('批量处理已取消 (已离开候选人页面)', 'warning');
    }
});

// Cancel batch processing on browser navigation (back/forward)
window.addEventListener('popstate', () => {
    if (window.batchProcessingActive && !isOnCandidatePage()) {
        window.stopBatchProcessing = true;
        showToast('批量处理已取消 (已离开候选人页面)', 'warning');
    }
});

// Cancel batch processing on page unload
window.addEventListener('beforeunload', () => {
    if (window.batchProcessingActive) {
        window.stopBatchProcessing = true;
    }
});

// Note: htmx:responseError is already handled above in the Global HTMX Error Handling section

// ============================================================================
// Centralized Candidate Card Update Handler
// ============================================================================

/**
 * Check if a card matches the given identifiers
 */
function idMatched(cardData, identifiers) {
    // Return true if any key from identifiers matches in cardData (both values must be truthy and equal)
    for (const [k, v] of Object.entries(identifiers)) {
        if (
            v !== undefined && v !== null && v !== "" &&
            cardData[k] !== undefined && cardData[k] !== null && cardData[k] !== "" &&
            cardData[k] === v
        ) {
            return true;
        }
    }
    return false;
}

/**
 * Update a candidate card with the given updates
 */
function applyCardUpdate(card, updates, identifiers) {
    // Parse hx-vals which has structure: {"candidate": {...}}
    const hxValsData = JSON.parse(card.getAttribute('hx-vals') || '{"candidate": {}}');
    const cardData = hxValsData.candidate || {};
    
    // Update the card's candidate data
    Object.assign(cardData, updates);
    Object.assign(cardData, identifiers);
    
    // Apply updates - maintain the {"candidate": {...}} structure
    card.setAttribute('hx-vals', JSON.stringify({ candidate: cardData }));
    
    // Update viewed state (opacity of entire card)
    if ('viewed' in updates) {
        if (updates.viewed) {
            card.classList.add('opacity-60');
        } else {
            card.classList.remove('opacity-60');
        }
    }
    
    // Update stage badge
    if ('stage' in updates) {
        const stageBadge = card.querySelector('[data-badge="stage"]');
        if (stageBadge) {
            // Set base classes if not already set
            if (!stageBadge.className.includes('inline-flex')) {
                stageBadge.className = 'inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full shrink-0';
            }
            
            let stageEmoji = '';
            let stageClasses = '';
            
            switch (updates.stage) {
                case 'CHAT':
                    stageEmoji = '💬';
                    stageClasses = 'bg-blue-100 text-blue-700';
                    break;
                case 'SEEK':
                    stageEmoji = '✅';
                    stageClasses = 'bg-yellow-100 text-yellow-700';
                    break;
                case 'CONTACT':
                    stageEmoji = '⭐';
                    stageClasses = 'bg-emerald-100 text-emerald-700';
                    break;
                case 'PASS':
                    stageEmoji = '❌';
                    stageClasses = 'bg-red-100 text-red-700';
                    break;
                default:
                    stageEmoji = '';
                    stageClasses = 'bg-gray-100 text-gray-700';
            }
            
            // Remove old stage color classes and add new one
            stageBadge.className = stageBadge.className.replace(/\b(bg-(blue|yellow|emerald|green|red|gray)-100 text-(blue|yellow|emerald|green|red|gray)-700)\b/g, '');
            stageBadge.className += ' ' + stageClasses;
            stageBadge.textContent = stageEmoji;
            
            if (updates.stage) {
                stageBadge.classList.remove('hidden');
            } else {
                stageBadge.classList.add('hidden');
            }
        }
        // If stageBadge doesn't exist, silently skip the update
    }
    
    // Update tags (greeted, saved, and notified - viewed is handled by card opacity)
    const tagsContainer = card.querySelector('#candidate-tags');
    // Update greeted tag
    if ('greeted' in updates) {
        const greetedTag = tagsContainer.querySelector('[data-tag="greeted"]');
        if (greetedTag) {
            if (updates.greeted) {
                greetedTag.classList.remove('hidden');
            } else {
                greetedTag.classList.add('hidden');
            }
        }
    }
    
    // Update saved tag
    if ('saved' in updates) {
        const savedTag = tagsContainer.querySelector('[data-tag="saved"]');
        if (savedTag) {
            if (updates.saved) {
                savedTag.classList.remove('hidden');
            } else {
                savedTag.classList.add('hidden');
            }
        }
    }
    
    // Update notified tag
    if ('notified' in updates) {
        const notifiedTag = tagsContainer.querySelector('[data-tag="notified"]');
        if (notifiedTag) {
            if (updates.notified) {
                notifiedTag.classList.remove('hidden');
            } else {
                notifiedTag.classList.add('hidden');
            }
        }
    }
    
    // Update score badge
    if ('score' in updates) {
        const cardContainer = card.querySelector('.flex.items-start.space-x-3');
        const scoreBadge = cardContainer?.querySelector('[data-badge="score"]');
        if (updates.score !== null && updates.score !== undefined) {
            scoreBadge.textContent = updates.score.toString();
            scoreBadge.classList.remove('hidden');
        } else {
            scoreBadge.classList.add('hidden');
        }
    }
}

// Centralized event listener for candidate updates
document.addEventListener('candidate:update', function(event) {
    const { identifiers, updates } = event.detail;
    const candidateCards = document.querySelectorAll('.candidate-card');
    
    // If index is provided, use it to directly locate the card (most efficient)
    const index = parseInt(identifiers.index);
    const card = candidateCards[index];
    const hxValsData = JSON.parse(card.getAttribute('hx-vals') || '{"candidate": {}}');
    const cardData = hxValsData.candidate || {};
    
    // Additional validation: check candidate_id, chat_id, and name if both have them
    let isValid = true;
    // Check candidate_id if both have it
    if (identifiers.candidate_id && cardData.candidate_id) {
        isValid = isValid && (cardData.candidate_id === identifiers.candidate_id);
    }
    // Check chat_id if both have it
    if (identifiers.chat_id && cardData.chat_id) {
        isValid = isValid && (cardData.chat_id === identifiers.chat_id);
    }
    // Check name if both have it
    if (identifiers.name && cardData.name) {
        isValid = isValid && (cardData.name === identifiers.name);
    }
    
    if (isValid) {
        applyCardUpdate(card, updates, identifiers);
        return;
    } else {
        console.warn('candidate:update: index matched but identifiers validation failed', {
            identifiers,
            cardData,
            index
        });
    }
});

// ============================================================================
// Runtime Check (Service Status + Version Update)
// ============================================================================

/**
 * Fetch with timeout and error handling
 * @param {string} url - URL to fetch
 * @param {number} timeoutMs - Timeout in milliseconds (default: 30000)
 * @returns {Promise<Response>} Fetch response
 */
async function fetchWithTimeout(url, timeoutMs = 30000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    
    const response = await fetch(url, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    return response;
}

/**
 * Combined runtime check: service status and version updates
 * Runs every 30 seconds
 */
function initRuntimeCheck() {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const versionTag = document.getElementById('version-tag');
    
    let runtimeCheckInterval = null;
    let lastVersionCheck = 0;
    const VERSION_CHECK_INTERVAL = 300000; // Check version every 5 minutes (300s)
    
    async function runtimeCheck() {
        // Always check service status
        if (statusDot && statusText) {
            const response = await fetchWithTimeout('/status').catch(error => {
                // Handle fetch errors (network, timeout, etc.)
                if (error.name === 'AbortError') {
                    statusDot.className = 'w-2 h-2 bg-yellow-500 rounded-full animate-pulse';
                    statusText.textContent = '服务响应超时';
                    statusText.className = 'text-sm text-yellow-600';
                } else {
                    statusDot.className = 'w-2 h-2 bg-red-500 rounded-full';
                    statusText.textContent = '服务离线';
                    statusText.className = 'text-sm text-red-600';
                }
                return null;
            });
            
            if (response?.ok) {
                const data = await response.json();
                // Check Zilliz connection status
                if (data.zilliz_connected === false) {
                    // Zilliz connection failed - show error
                    statusDot.className = 'w-2 h-2 bg-red-500 rounded-full animate-pulse';
                    statusText.textContent = 'Zilliz 连接失败';
                    statusText.className = 'text-sm text-red-600 font-semibold';
                    
                    // Show error toast (only once per session)
                    if (!sessionStorage.getItem('zilliz_error_shown')) {
                        const errorMsg = data.zilliz_error 
                            ? `Zilliz 数据库连接失败: ${data.zilliz_error}` 
                            : 'Zilliz 数据库连接失败，请检查配置';
                        showToast(errorMsg, 'error');
                        sessionStorage.setItem('zilliz_error_shown', 'true');
                    }
                } else {
                    // Service is running normally
                    statusDot.className = 'w-2 h-2 bg-green-500 rounded-full animate-pulse';
                    statusText.textContent = '服务运行中';
                    statusText.className = 'text-sm text-gray-600';
                    // Clear error flag if connection is restored
                    sessionStorage.removeItem('zilliz_error_shown');
                }
                
                // Update version tag - always update, even if version is null/undefined
                console.log('Status response data:', data); // Debug log
                if (versionTag) {
                    versionTag.textContent = data.version;
                }
            } else if (response) {
                // Service returned error
                statusDot.className = 'w-2 h-2 bg-yellow-500 rounded-full animate-pulse';
                statusText.textContent = '服务异常';
                statusText.className = 'text-sm text-yellow-600';
            }
        }
        
        // Check version update less frequently (every 5 minutes)
        const now = Date.now();
        if (now - lastVersionCheck >= VERSION_CHECK_INTERVAL) {
            lastVersionCheck = now;
            
            const response = await fetchWithTimeout('/version/check').catch(() => null);
            
            if (!response?.ok) {
                return; // Silently fail
            }
            
            const data = await response.json();
            
            // If merge was successful, show success message (don't show modal, just log)
            if (data.merge_success === true) {
                console.log('✅ Code updated successfully:', data.message);
                // Clear dismissed version so user sees the success
                if (data.remote_commit) {
                    localStorage.removeItem('dismissedVersion');
                }
                return; // Don't show modal for successful auto-updates
            }
            
            // If merge failed or update available, show modal
            if (data.has_update && data.remote_commit) {
                // Check if this version was already dismissed
                const dismissedVersion = localStorage.getItem('dismissedVersion');
                if (dismissedVersion === data.remote_commit) {
                    return; // User already dismissed this version
                }
                
                // Show modal
                if (window.Alpine && Alpine.store('versionUpdateModal')) {
                    const modal = Alpine.store('versionUpdateModal');
                    
                    // Set title and message based on merge status
                    if (data.merge_success === false) {
                        modal.title = '⚠️ 自动更新失败';
                        modal.message = data.message || `检测到新版本但自动合并失败。\n\n错误: ${data.merge_error || '未知错误'}\n\n请手动运行 start.command 更新代码。`;
                    } else {
                        modal.title = '新版本可用';
                        modal.message = data.message || '检测到新的 Git 版本可用，建议更新以获取最新功能。';
                    }
                    
                    modal.currentCommit = data.current_commit;
                    modal.remoteCommit = data.remote_commit;
                    modal.currentBranch = data.current_branch;
                    modal.repoUrl = data.repo_url;
                    modal.show = true;
                }
            }
        }
    }
    
    // Check immediately on page load
    runtimeCheck();
    
    // Also update version tag immediately if element exists (in case status check hasn't run yet)
    if (versionTag) {
        fetchWithTimeout('/status')
            .then(response => response?.ok ? response.json() : null)
            .then(data => {
                versionTag.textContent = data?.version || 'v-...';
            })
            .catch(() => {
                // Silently fail - version will be updated on next status check
                versionTag.textContent = 'v-...';
            });
    }
    
    // Then check every 30 seconds
    runtimeCheckInterval = setInterval(runtimeCheck, 30000);
    
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (runtimeCheckInterval) {
            clearInterval(runtimeCheckInterval);
        }
    });
}

// ============================================================================
// Daily Chart Component (Bar Chart for 7-day new/SEEK stats using Chart.js)
// ============================================================================

// Store chart instances to allow proper cleanup (shared across all chart functions)
if (typeof window.chartInstances === 'undefined') {
    window.chartInstances = new Map();
}
const chartInstances = window.chartInstances;

/**
 * Format date string to MM-DD format
 * @param {string} dateStr - Date string to format
 * @returns {string} Formatted date string (MM-DD)
 */
function formatDate(dateStr) {
    const date = new Date(dateStr);
    // Check if date is valid
    if (isNaN(date.getTime())) {
        // Fallback: try to extract date from string
        return dateStr.split('T')[0].slice(5) || dateStr.slice(-5);
    }
    return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/**
 * Render bar chart for daily stats using Chart.js
 * @param {HTMLElement} container - Container element with data-daily attribute
 */
function renderDailyChart(container) {
    const dailyDataStr = container.getAttribute('data-daily');
    if (!dailyDataStr) return;
    
    const dailyData = JSON.parse(dailyDataStr);
    if (!dailyData || dailyData.length === 0) return;
    
    // Check if Chart.js is available
    if (typeof Chart === 'undefined') {
        console.error('Chart.js is not loaded');
        return;
    }
    
    // Find or create canvas element
    let canvas = container.querySelector('canvas');
    if (!canvas) {
        // Remove old HTML chart if exists
        const oldChart = container.querySelector('.flex.items-end');
        if (oldChart) {
            oldChart.remove();
        }
        
        // Create canvas element
        canvas = document.createElement('canvas');
        canvas.style.maxHeight = '250px';
        container.insertBefore(canvas, container.firstChild);
    }
    
    // Destroy existing chart if it exists
    const chartId = container.getAttribute('data-chart-id') || `chart-${Date.now()}-${Math.random()}`;
    container.setAttribute('data-chart-id', chartId);
    
    if (chartInstances.has(chartId)) {
        chartInstances.get(chartId).destroy();
        chartInstances.delete(chartId);
    }
    
    // Prepare data
    const labels = dailyData.map(d => formatDate(d.date));
    const newData = dailyData.map(d => d.new || 0);
    const seekData = dailyData.map(d => d.seek || 0);
    
    // Create Chart.js bar chart
    const chart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '新增',
                    data: newData,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)', // blue-500 with opacity
                    borderColor: 'rgba(59, 130, 246, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                },
                {
                    label: 'SEEK',
                    data: seekData,
                    backgroundColor: 'rgba(99, 102, 241, 0.6)', // indigo-500 with opacity
                    borderColor: 'rgba(99, 102, 241, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: false,
                    grid: {
                        display: false
                    },
                    ticks: {
                        font: {
                            size: 11
                        }
                    }
                },
                y: {
                    beginAtZero: true,
                    stacked: false,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        stepSize: 1,
                        font: {
                            size: 11
                        }
                    }
                }
            },
            interaction: {
                mode: 'index',
                intersect: false
            }
        }
    });
    
    // Store chart instance (use window.chartInstances directly)
    if (window.chartInstances) {
        window.chartInstances.set(chartId, chart);
    }
    
    // Also store reference on canvas for quick lookup
    canvas.chart = chart;
}

// Initialize charts when DOM is ready or after HTMX swap
function initDailyCharts() {
    document.querySelectorAll('.daily-chart-container').forEach(container => {
        renderDailyChart(container);
    });
}

// Initialize charts on page load
document.addEventListener('DOMContentLoaded', initDailyCharts);

// Re-initialize charts after HTMX swaps
document.body.addEventListener('htmx:afterSwap', function(event) {
    const target = event.detail.target;
    if (!target) return;
    
    // Check if the swapped element itself is a chart container
    if (target.classList && target.classList.contains('daily-chart-container')) {
        renderDailyChart(target);
        return;
    }
    
    // Check if the swapped content contains chart containers
    const swappedCharts = target.querySelectorAll('.daily-chart-container');
    if (swappedCharts.length > 0) {
        initDailyCharts();
    }
});

// ============================================================================
// Daily Chart Component (Bar Chart for daily new/SEEK stats using Chart.js)
// ============================================================================

// Use the shared chartInstances map (already defined above - don't redeclare)

/**
 * Render daily candidate count mixed chart (bar for daily new, line for cumulative)
 */
function renderDailyCandidateChart() {
    const container = document.querySelector('.daily-candidate-chart-container');
    if (!container) return;
    
    const dailyDataStr = container.getAttribute('data-daily');
    if (!dailyDataStr) return;
    
    const dailyData = JSON.parse(dailyDataStr);
    if (!dailyData || dailyData.length === 0) return;
    
    if (typeof Chart === 'undefined') {
        throw new Error('Chart.js is not loaded');
    }
    
    // Destroy existing chart if it exists
    const existingChartId = container.getAttribute('data-chart-id');
    if (existingChartId && window.chartInstances && window.chartInstances.has(existingChartId)) {
        window.chartInstances.get(existingChartId).destroy();
        window.chartInstances.delete(existingChartId);
    }
    
    // Create canvas element
    const canvas = document.createElement('canvas');
    canvas.style.maxHeight = '250px';
    container.innerHTML = '';
    container.appendChild(canvas);
    
    const chartId = `candidate-chart-${Date.now()}`;
    container.setAttribute('data-chart-id', chartId);
    
    // Prepare data
    const labels = dailyData.map(d => formatDate(d.date));
    const cumulativeData = dailyData.map(d => d.count || 0);
    const newData = dailyData.map(d => d.new || 0);
    
    // Create Chart.js mixed chart (bar + line)
    const chart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '当日新增',
                    data: newData,
                    type: 'bar',
                    backgroundColor: 'rgba(16, 185, 129, 0.6)', // green-500 with opacity
                    borderColor: 'rgba(16, 185, 129, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                    yAxisID: 'y',
                },
                {
                    label: '累计总数',
                    data: cumulativeData,
                    type: 'line',
                    borderColor: 'rgba(59, 130, 246, 1)', // blue-500
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    yAxisID: 'y1',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        font: {
                            size: 11
                        },
                        maxRotation: 45,
                        minRotation: 45
                    }
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: '当日新增',
                        font: {
                            size: 12
                        }
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        font: {
                            size: 11
                        }
                    }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: '累计总数',
                        font: {
                            size: 12
                        }
                    },
                    grid: {
                        drawOnChartArea: false, // Only draw grid for left axis
                    },
                    ticks: {
                        font: {
                            size: 11
                        }
                    }
                }
            },
            interaction: {
                mode: 'index',
                intersect: false
            }
        }
    });
    
    // Store chart instance (use window.chartInstances directly)
    if (window.chartInstances) {
        window.chartInstances.set(chartId, chart);
    }
    
    // Also store reference on canvas for quick lookup
    canvas.chart = chart;
}

// ============================================================================
// Stats Page Component (Renders stats from JSON API)
// ============================================================================

/**
 * Render quick stats cards
 */
function renderQuickStats(data) {
    const container = document.getElementById('quick-stats');
    if (!container) {
        return;
    }
    
    const stats = data.quick_stats || {};
    const dailyData = stats.daily_candidate_counts || [];
    
    container.innerHTML = `
        <div class="bg-white rounded-lg shadow p-6 col-span-1 md:col-span-2">
            <h3 class="text-sm text-gray-600 mb-2">已筛选候选人总数</h3>
            <p class="text-3xl font-bold text-blue-600 mb-4">${stats.total_candidates || 0}</p>
            <div class="daily-candidate-chart-container" data-daily='${JSON.stringify(dailyData)}' style="min-height: 250px;">
                <!-- Chart.js canvas will be inserted here -->
        </div>
        </div>
    `;
    
    // Initialize the chart after rendering
    setTimeout(() => {
        renderDailyCandidateChart();
    }, 100);
}

/**
 * Format conversion rate badge
 */
function formatRateBadge(rate) {
    let color = 'text-amber-600';
    if (rate >= 0.6) {
        color = 'text-green-600';
    } else if (rate < 0.3) {
        color = 'text-red-600';
    }
    return `<span class="font-semibold ${color}">${(rate * 100).toFixed(0)}%</span>`;
}

/**
 * Render job statistics
 */
function renderJobStats(data) {
    const container = document.getElementById('job-stats');
    if (!container) return;
    
    let jobs = data.jobs || [];
    const best = data.best;
    
    if (jobs.length === 0) {
        container.innerHTML = '<div class="text-gray-600">暂无数据，先去处理候选人吧。</div>';
        return;
    }
    
    // 按进展分倒序排列（从高到低）
    jobs = jobs.sort((a, b) => {
        const metricA = (a.today && a.today.metric) || 0;
        const metricB = (b.today && b.today.metric) || 0;
        return metricB - metricA; // 倒序：高进展分在前
    });
    
    let html = '';
    
    // Render best job card
    if (best) {
        const ss = best.score_summary;
        html += `
            <div class="bg-gradient-to-r from-indigo-600 to-blue-500 text-white rounded-lg shadow p-6">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-sm opacity-80">今日最优秀战绩</p>
                        <h3 class="text-2xl font-bold">${best.job}</h3>
                        <p class="mt-2 text-lg">进展分 ${best.today.metric.toFixed(1)} = (近7日 ${best.today.count} 人 + SEEK ${best.today.seek} 人) × 肖像得分 ${ss.quality_score} ÷ 10</p>
                        <p class="text-sm opacity-80">高分占比 ${(ss.high_share * 100).toFixed(1)}% · 平均分 ${ss.average}</p>
                    </div>
                    <div class="text-right">
                        <p class="text-sm opacity-80">肖像得分</p>
                        <p class="text-4xl font-extrabold">${ss.quality_score}</p>
                        <p class="text-xs opacity-70 mt-1">分布均匀度40% + 高分占比30% + 中心分数30%</p>
                        <p class="text-sm opacity-80 mt-2">${ss.comment}</p>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Render job cards (已按进展分倒序排列)
    jobs.forEach(job => {
        const ss = job.score_summary;
        const dailyData = job.daily || [];
        
        // Generate conversion rows
        const convRows = (job.conversions || []).map(c => `
            <tr>
                <td class="py-1">${c.stage}</td>
                <td class="py-1">${c.count}</td>
                <td class="py-1 text-sm text-gray-500">${c.previous}</td>
                <td class="py-1">${formatRateBadge(c.rate)}</td>
            </tr>
        `).join('');
        
        html += `
            <div class="bg-white rounded-lg shadow p-6">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h3 class="text-xl font-bold text-gray-800">${job.job}</h3>
                        <p class="text-sm text-gray-500">总候选人 ${job.total} · 高分占比 ${(ss.high_share * 100).toFixed(1)}% · 画像质量 ${ss.quality_score}/10</p>
                        <p class="text-sm text-gray-500">评语：${ss.comment}</p>
                        ${job.today ? `
                        <p class="text-sm text-gray-600 mt-2">
                            <span class="font-semibold">进展分 ${job.today.metric.toFixed(1)}</span> = 
                            (近7日 ${job.today.count} 人 + SEEK ${job.today.seek} 人) × 肖像得分 ${ss.quality_score} ÷ 10
                        </p>
                        ` : ''}
                    </div>
                    <div class="text-right">
                        <p class="text-sm text-gray-500">肖像得分</p>
                        <p class="text-3xl font-extrabold text-indigo-600">${ss.quality_score}</p>
                    </div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <h4 class="text-sm font-semibold text-gray-700 mb-2">近7日新增/SEEK</h4>
                        <div class="daily-chart-container p-4 bg-gray-50 rounded-lg" data-daily='${JSON.stringify(dailyData)}' style="min-height: 250px;">
                            <!-- Chart.js canvas will be inserted here -->
                        </div>
                    </div>
                    <div>
                        <h4 class="text-sm font-semibold text-gray-700 mb-2">阶段转化率</h4>
                        <table class="min-w-full text-left text-sm">
                            <thead>
                                <tr class="text-gray-500">
                                    <th class="py-1">阶段</th>
                                    <th class="py-1">人数</th>
                                    <th class="py-1">上阶段</th>
                                    <th class="py-1">转化</th>
                                </tr>
                            </thead>
                            <tbody>${convRows}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    
    // Initialize charts after rendering
    initDailyCharts();
}

/**
 * Load and render stats page
 */
async function loadStatsPage() {
    const quickStatsContainer = document.getElementById('quick-stats');
    const jobStatsContainer = document.getElementById('job-stats');
    
    if (!quickStatsContainer && !jobStatsContainer) {
        return; // Not on stats page
    }
    
        const response = await fetch('/stats', {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        });
        
        if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
    if (!data.success) {
        throw new Error(data.error || 'Stats API returned success=false');
    }
    
            if (quickStatsContainer) {
                renderQuickStats(data);
            }
            if (jobStatsContainer) {
                renderJobStats(data);
            }
}

// Load stats on page load (for index page)
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('quick-stats') || document.getElementById('job-stats')) {
        loadStatsPage().catch(error => {
        console.error('Failed to load stats:', error);
            const quickStatsContainer = document.getElementById('quick-stats');
            const jobStatsContainer = document.getElementById('job-stats');
        if (quickStatsContainer) {
                quickStatsContainer.innerHTML = '<div class="text-red-600 p-4">加载统计数据失败: ' + error.message + '</div>';
        }
        if (jobStatsContainer) {
                jobStatsContainer.innerHTML = '<div class="text-red-600 p-4">加载统计数据失败: ' + error.message + '</div>';
        }
        });
    }
});

// Initialize runtime check when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRuntimeCheck);
} else {
    initRuntimeCheck();
}

// ============================================================================
// Note: All candidate-specific functions moved to candidate_detail.html
// ============================================================================
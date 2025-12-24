// Alpine.js global store and components for BOSS招聘助手

// ============================================================================
// Toast Notification System (must be defined early)
// ============================================================================

/**
 * Toast notification helper
 * Displays temporary notification messages in the top-right corner
 */
function showToast(message, type = 'info') {
    // Also output to console based on type
    switch (type) {
        case 'error':
            console.error(message);
            break;
        case 'warning':
            console.warn(message);
            break;
        case 'success':
        case 'info':
        default:
            console.log(message);
            break;
    }
    
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
        // Expire all *previous* toasts in 3 seconds to prevent stacking/flashing
        expireAllToasts(3000);

        container.appendChild(toast);
        
        // Timeout 180s (3 minutes) for the new toast
        const timeoutId = setTimeout(() => {
            removeToast(toast);
        }, 180000); 

        // Allow manual removal to clear timeout
        toast.dataset.timeoutId = timeoutId;
    }
}

function removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    
    // Clear timeout if it exists
    if (toast.dataset.timeoutId) {
        clearTimeout(parseInt(toast.dataset.timeoutId));
    }

    toast.classList.add('animate-fade-out');
    setTimeout(() => toast.remove(), 300);
}

// Expire all toasts with a custom timeout (default 3000ms)
// Used to gently clear toasts when a new one comes or when operations finish
function expireAllToasts(timeoutMs = 3000) {
    const container = document.getElementById('toast-container');
    if (container) {
        const toasts = container.querySelectorAll('div');
        toasts.forEach(t => {
            // If already fading out, ignore
            if (t.classList.contains('animate-fade-out')) return;

            // Clear existing long timeout
            if (t.dataset.timeoutId) {
                clearTimeout(parseInt(t.dataset.timeoutId));
            }
            
            // Set new short timeout
            const newId = setTimeout(() => {
                removeToast(t);
            }, timeoutMs);
            t.dataset.timeoutId = newId;
        });
    }
}

// Clear all toasts immediately (compatibility)
function clearAllToasts() {
    expireAllToasts(0);
}

// Gently dismiss toasts when HTMX request finishes or errors (3s delay)
document.body.addEventListener('htmx:afterRequest', () => expireAllToasts(3000));
document.body.addEventListener('htmx:responseError', () => expireAllToasts(3000));

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
        // Ensure body is a string and not truncated
        const fullBody = String(body || '');
        
        const notification = new Notification(title, {
            body: fullBody,
            icon: icon || 'https://www.zhipin.com/favicon.ico',
            badge: icon || 'https://www.zhipin.com/favicon.ico',
            tag: 'bosszhipin-message', // Use tag to replace previous notifications
            requireInteraction: true, // Keep notification visible until user interacts
            silent: false, // Play notification sound
        });
        
        // Don't auto-close - let user dismiss manually or click to close
        // Removed setTimeout auto-close to make notification sticky
        
        // Handle click to focus window and close notification
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

// Note: candidateTabs() and updateCandidateURL() moved to candidates.html

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
                loadingIndicator.classList.remove('htmx-request');
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
// Only handle errors that weren't already handled by local listeners (e.g., in process All Candidates)
document.body.addEventListener('htmx:responseError', function(evt) {
    // Skip if event propagation was stopped (already handled by local listenesr)
    if (evt.cancelBubble) {
        return;
    }
    
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.remove('htmx-request');
    }
    // console.error('HTMX response error:', evt.detail);
    const errorMsg = evt.detail?.error || evt.detail?.message || '请求失败';
    // showToast(errorMsg, 'error');
});



// Catch general HTMX errors
document.body.addEventListener('htmx:sendError', function(evt) {
    console.error('HTMX send error:', evt.detail);
    // Only show toast if not already handled by htmxAjaxPromise
    if (!evt.detail.handled) {
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
    
    // Try to parse JSON error body
    const errorData = await response.json();
    
    // 422: ValidationError or custom detail structure
    if (response.status === 422 && errorData.detail) {
        const errors = errorData.detail
            .map(e => `${e.loc.join('.')}: ${e.msg}`)
            .join(', ');
        throw new Error(`Validation failed: ${errors}`);
    }
    
    // Other server errors
    const message = errorData.error || errorData.detail || response.statusText;
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

// Note: htmx:responseError is already handled above in the Global HTMX Error Handling section

// ============================================================================
// Cycle Reply Automation (auto-rotates candidate modes)
// ============================================================================

const CYCLE_MODES = ['recommend', 'greet', 'chat', 'followup'];

const cycleReplyState = {
    // Control flags
    running: false,              // Whether candidate processing is running
    stopRequested: false,         // Whether stop has been requested (graceful shutdown)
    
    // Progress tracking
    modeIndex: 0,                 // Current mode index in cycle (0-3)
    lastProcessedTime: null,      // Last time a candidate was processed (for idle timeout)
    
    // Error tracking
    errorStreak: 0               // Consecutive errors (stops at 10)
};

const CycleReplyHelpers = {
    getButton() {
        return document.getElementById('cycle-reply-btn');
    },
    
    setButton(isRunning, label = null) {
        const btn = this.getButton();
        btn.disabled = false;
        btn.textContent = label || (isRunning ? '⏹️ 停止自动处理' : '▶ 自动处理');
        btn.classList.toggle('opacity-60', isRunning && cycleReplyState.stopRequested);
    },
    
    async requestStop(message = '处理即将停止...') {
        cycleReplyState.stopRequested = true;
        this.setButton(true, '⏹️ 正在停止...');
        showToast(message, 'info');
    },
    
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    },
    
    async waitUntil(predicate, { timeoutMs = 15000, stepMs = 300, ignoreStopRequest = false } = {}) {
        const start = performance.now();
        while (true) {
            // Only check stopRequested if ignoreStopRequest is false
            if (!ignoreStopRequest && cycleReplyState.stopRequested) {
                return { success: false, stopped: true };
            }
            if (predicate()) {
                return { success: true };
            }
            if (performance.now() - start >= timeoutMs) {
                return { success: false, timeout: true };
            }
            await this.sleep(stepMs);
        }
    },
    
    getCandidateTabs() {
        const element = document.querySelector('[x-data*="candidateTabs"]');
        if (element.__x?.$data) {
            return element.__x.$data;
        }
        return element._x_dataStack[0];
    },
    
    async ensureCandidatesLoaded(mode, candidateTabs) {
        const candidateList = document.getElementById('candidate-list');
        if (!candidateList) {
            throw new Error('无法找到候选人列表容器');
        }
        
        let candidateCards = candidateList.querySelectorAll('.candidate-card');
        
        if (candidateCards.length === 0) {
            // Use the activeTab from candidateTabs component, fallback to mode
            const activeTab = candidateTabs?.activeTab || mode;
            
            // load candidates list
            try {
                await window.loadCandidatesList(activeTab);
                // await this.waitUntil(
                //     () => candidateList.querySelectorAll('.candidate-card').length > 0 || candidateList.querySelector('#empty-message'),
                //     { timeoutMs: 5000 }
                // );
            } catch (error) {
                return { success: false, error: error };
            }
            
            candidateCards = candidateList.querySelectorAll('.candidate-card');
        } else {
            console.log(`列表已有 ${candidateCards.length} 人，跳过查询`);
        }
        
        return { success: true, candidateCards };
    },
    
    
    async processMode(mode, candidateTabs) {
        const isCurrentTab = candidateTabs.activeTab === mode;
        
        if (!isCurrentTab) {
            showToast(`处理: 切换到 ${mode}`, 'info');
            candidateTabs.switchTab(mode);
            await this.sleep(350);
        } else {
            // If already on this tab, preserve the existing candidate list
            showToast(`处理: 当前模式 ${mode}`, 'info');
        }
        
        const loadResult = await this.ensureCandidatesLoaded(mode, candidateTabs);
        if (!loadResult.success) {
            const error = loadResult.error;
            const errorMessage = error.message || error.toString() || JSON.stringify(error);
            const errorStatus = error.status || error.statusCode || loadResult.status;
            const isServerError = errorStatus >= 500 ||
                                errorMessage.includes('500') || 
                                errorMessage.includes('Server error (500)') ||
                                errorMessage.includes('Internal Server Error') ||
                                errorMessage.includes('ERR_CONNECTION_REFUSED') ||
                                errorMessage.includes('Connection refused') ||
                                errorMessage.includes('HTMX') ||
                                errorMessage.includes('network') ||
                                errorMessage.includes('NetworkError') ||
                                errorMessage.includes('Failed to fetch');
            
            return {
                success: false,
                error: error,
                isServerError: isServerError,
                errorMessage: errorMessage
            };
        }
        
        return { success: true, candidateCards: loadResult.candidateCards };
    },
    
    resetState() {
        cycleReplyState.running = false;
        cycleReplyState.stopRequested = false;
        // Start from current tab instead of always starting from index 0
        const candidateTabs = this.getCandidateTabs();
        const currentTab = candidateTabs.activeTab || 'recommend';
        cycleReplyState.modeIndex = CYCLE_MODES.indexOf(currentTab);
        if (cycleReplyState.modeIndex === -1) {
            cycleReplyState.modeIndex = 0;
        }
        cycleReplyState.errorStreak = 0;
        cycleReplyState.lastProcessedTime = Date.now(); // Initialize to current time when starting
    }
};

/**
 * Start processing candidates
 */
async function startProcessCandidate() {
    if (cycleReplyState.running) {
        await stopProcessCandidate();
        return;
    }
    
    // Check if "process all modes" checkbox is checked
    const processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
    
    CycleReplyHelpers.resetState();
    cycleReplyState.running = true;
    CycleReplyHelpers.setButton(true);
    
    // Disable all candidate cards via event
    document.dispatchEvent(new CustomEvent('candidates:disable-cards'));
    let total_processed = 0;
    let total_failed = 0;
    let total_skipped = 0;
    try {
        while (cycleReplyState.running && !cycleReplyState.stopRequested) {
            // Check if 5 minutes have passed without processing any candidate
            const idleTime = Date.now() - cycleReplyState.lastProcessedTime;
            const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
            if (idleTime >= IDLE_TIMEOUT_MS) {
                showToast('5分钟没有处理任何候选人，处理已停止', 'warning');
                break;
            }
            
            // Determine current mode
            const candidateTabs = CycleReplyHelpers.getCandidateTabs();
            const mode = processAllModes 
                ? CYCLE_MODES[cycleReplyState.modeIndex]
                : (candidateTabs.activeTab || 'recommend');
            
            // Process mode (switch tab if needed)
            const result = await CycleReplyHelpers.processMode(mode, candidateTabs);
            
            if (result.stopped) {
                break;
            }
            
            // Handle errors
            if (result.success === false) {
                cycleReplyState.errorStreak += 1;
                showToast(`处理模式 ${mode} 出错 (${cycleReplyState.errorStreak}/10): ${result.errorMessage}`, 'error');
                if (cycleReplyState.errorStreak >= 10) {
                    showToast('连续错误超过 10 次，处理已停止', 'error');
                    break;
                }
                // Move to next mode if processing all modes
                if (processAllModes) {
                    cycleReplyState.modeIndex = (cycleReplyState.modeIndex + 1) % CYCLE_MODES.length;
                    await CycleReplyHelpers.sleep(1000);
                }
                continue;
            }
            
            // Process candidates in current mode
            // Convert to Array immediately to avoid NodeList mutation issues when cards are removed
            let cards = Array.from(result.candidateCards || document.querySelectorAll('.candidate-card'));
            let processed = 0;
            let failed = 0;
            let skipped = 0;
            
            // Process each candidate
            console.log(`[${mode}] 开始处理 ${cards.length} 个候选人`);
            for (const card of cards) {
                if (!cycleReplyState.running || cycleReplyState.stopRequested) {
                    break;
                }
                // 处理每个候选人
                try {
                    const result = await window.processCandidateCard(card);
                    if (result.skipped) {
                        skipped++;
                        total_skipped += 1;
                        console.log(`[处理] 跳过已查看的候选人: ${result.name} (${skipped} 已跳过)`);
                    } else if (result.success) {
                        processed++;
                        total_processed++;
                        cycleReplyState.lastProcessedTime = Date.now();
                        console.log(`✅ ${result.name} 处理完成 (${processed}/${cards.length})`);
                        total_processed++;
                    } else {
                        // this will never happen, because always return a success result
                        failed++;
                        cycleReplyState.errorStreak++;
                        console.error(`❌ ${result.name} 处理失败: ${result.error || '未知错误'}`);
                        if (cycleReplyState.errorStreak >= 10) {
                            showToast('连续错误超过 10 次，处理已停止', 'error');
                            break;
                        }
                    }
                } catch (error) {
                    failed++;
                    cycleReplyState.errorStreak++;
                    console.error(`❌ ${card.name} 处理失败: ${error || '未知错误'}`);
                    if (cycleReplyState.errorStreak >= 10) {
                        showToast('连续错误超过 10 次，处理已停止', 'error');
                        break;
                    }
                } 
            }
            
            // Check if error limit reached after processing candidates
            if (cycleReplyState.errorStreak >= 10) {
                break; // Stop outer loop
            }
            
            // Show summary for current mode
            const summary = `模式 ${mode} 完成: 成功 ${processed}/${cards.length}, 失败 ${failed}${skipped > 0 ? `, 跳过 ${skipped}` : ''}`;
            showToast(summary, failed ? 'success' : 'warning');
            
            // Move to next mode if processing all modes
            if (processAllModes) {
                cycleReplyState.modeIndex = (cycleReplyState.modeIndex + 1) % CYCLE_MODES.length;
                await CycleReplyHelpers.sleep(1000);
            } else {
                break;
            }
        }
    } finally {
        // Re-enable candidate cards via event
        document.dispatchEvent(new CustomEvent('candidates:enable-cards'));
        CycleReplyHelpers.resetState();
        CycleReplyHelpers.setButton(false);
        const processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
        showToast(processAllModes ? '循环处理已完成' : `批量处理已完成: 成功 ${total_processed}, 失败 ${total_failed}, 跳过 ${total_skipped}`, total_failed > 0 ? 'error' : 'success');
    }
}

/**
 * Stop processing candidates
 */
async function stopProcessCandidate() {
    await CycleReplyHelpers.requestStop('处理即将停止...');
}

// Expose to window for inline handlers
window.startProcessCandidate = startProcessCandidate;
window.stopProcessCandidate = stopProcessCandidate;
window.CycleReplyHelpers = CycleReplyHelpers;
window.cycleReplyState = cycleReplyState; // Expose for candidates.html to update lastProcessedTime

// ============================================================================
// Centralized Candidate Card Update Handler
// ============================================================================
// Note: All candidate-specific functions moved to candidate_detail.html
// Candidate UI code moved to candidates.html
// Runtime check moved to base.html
// ============================================================================

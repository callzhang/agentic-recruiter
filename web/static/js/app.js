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
    console.error('HTMX response error:', evt.detail);
    const errorMsg = evt.detail?.error || evt.detail?.message || '请求失败';
    showToast(errorMsg, 'error');
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

// Note: htmx:responseError is already handled above in the Global HTMX Error Handling section

// ============================================================================
// Cycle Reply Automation (auto-rotates candidate modes)
// ============================================================================

const CYCLE_MODES = ['recommend', 'greet', 'chat', 'followup'];

const cycleReplyState = {
    running: false,
    stopRequested: false,
    modeIndex: 0,
    errorStreak: 0,
    serverErrorStreak: 0,  // Separate counter for 500 server errors
    lastProcessedTime: null  // Track last time a candidate was processed (for idle timeout)
};

const CycleReplyHelpers = {
    getButton() {
        return document.getElementById('cycle-reply-btn');
    },
    
    setButton(isRunning, label = null) {
        const btn = this.getButton();
        if (!btn) return;
        
        btn.disabled = false;
        btn.textContent = label || (isRunning ? '⏸️ 停止循环' : '🔄 循环回复');
        btn.classList.toggle('opacity-60', isRunning && cycleReplyState.stopRequested);
    },
    
    async requestStop(message = '循环回复即将停止...') {
        cycleReplyState.stopRequested = true;
        this.setButton(true, '⏹️ 正在停止...');
        
        // If batch processing is active, stop it first
        if (window.batchProcessingActive) {
            showToast('正在停止批处理，然后停止循环处理', 'info');
            
            // Call stop batch processing handler
            stopBatchProcessingHandler();
            
            // Wait for batch processing to complete (up to 5 minutes)
            // Use ignoreStopRequest=true to ensure we actually wait for batch processing to finish
            const waitResult = await this.waitUntil(
                () => !window.batchProcessingActive,
                { timeoutMs: 300000, stepMs: 500, ignoreStopRequest: true } // Wait up to 5 minutes, ignore stop request
            );
            
            if (waitResult.timeout) {
                showToast('等待批处理停止超时，循环处理已停止', 'warning');
            } else if (waitResult.stopped) {
                showToast('循环处理已停止（批处理仍在运行）', 'warning');
            } else {
                showToast('批处理已停止，循环处理已停止', 'info');
            }
        } else {
        showToast(message, 'info');
        }
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
        if (element?.__x?.$data) {
            return element.__x.$data;
        }
        if (element?._x_dataStack?.[0]) {
            return element._x_dataStack[0];
        }
        throw new Error('无法访问 candidateTabs 实例');
    },
    
    async ensureCandidatesLoaded(mode, candidateTabs) {
        const candidateList = document.getElementById('candidate-list');
        if (!candidateList) {
            throw new Error('无法找到候选人列表容器');
        }
        
        let candidateCards = candidateList.querySelectorAll('.candidate-card');
        
        if (!candidateCards || candidateCards.length === 0) {
            showToast(`查询候选人: ${mode}`, 'info');
            
            candidateTabs.loadCandidates();
            const loadResult = await this.waitUntil(() => !candidateTabs.loading, { timeoutMs: 20000 });
            if (!loadResult.success) {
                return loadResult;
            }
            
            await this.waitUntil(
                () => candidateList.querySelectorAll('.candidate-card').length > 0 || candidateList.querySelector('#empty-message'),
                { timeoutMs: 5000 }
            );
            
            candidateCards = candidateList.querySelectorAll('.candidate-card');
        } else {
            showToast(`列表已有 ${candidateCards.length} 人，跳过查询`, 'info');
        }
        
        return { success: true, candidateCards };
    },
    
    // waitForBatchButton removed - no longer needed as we call processAllCandidates directly
    
    async waitForBatchProcessingComplete(numberOfCandidates = 1) {
        // Calculate timeout as number of candidates * 180 seconds (in milliseconds)
        const timeoutMs = numberOfCandidates * 180000;
        const start = performance.now();
        let lastActiveCheck = start;
        
        while (window.batchProcessingActive && !cycleReplyState.stopRequested) {
            if (performance.now() - start >= timeoutMs) {
                return { success: false, timeout: true };
            }
            await this.sleep(600);
        }
        
        if (cycleReplyState.stopRequested) {
            return { success: false, stopped: true };
        }
        
        // Let UI settle
        await this.sleep(400);
        return { success: true };
    },
    
    async processAllCandidatesForMode(mode, candidateCards) {
        if (!candidateCards || candidateCards.length === 0) {
            showToast(`没有找到候选人: ${mode}`, 'info');
            return { success: true, skipped: true };
        }
        
        if (cycleReplyState.stopRequested) {
            return { success: false, stopped: true };
        }
        
        // Directly start batch processing without needing the batch button
        // processAllCandidates() is async and will wait for all candidates to complete
        await processAllCandidates();
        
        // processAllCandidates() sets batchProcessingActive = false when done
        return { success: true };
    },
    
    async processMode(mode, candidateTabs) {
        const isCurrentTab = candidateTabs.activeTab === mode;
        
        if (!isCurrentTab) {
        showToast(`循环回复: 切换到 ${mode}`, 'info');
        candidateTabs.switchTab(mode);
        await this.sleep(350);
        } else {
            // If already on this tab, preserve the existing candidate list
            showToast(`循环回复: 处理当前模式 ${mode}`, 'info');
        }
        
        const loadResult = await this.ensureCandidatesLoaded(mode, candidateTabs);
        if (!loadResult.success) {
            return loadResult;
        }
        
        return this.processAllCandidatesForMode(mode, loadResult.candidateCards);
    },
    
    resetState() {
        cycleReplyState.running = false;
        cycleReplyState.stopRequested = false;
        // Start from current tab instead of always starting from index 0
        try {
            const candidateTabs = this.getCandidateTabs();
            const currentTab = candidateTabs.activeTab || 'recommend';
            cycleReplyState.modeIndex = CYCLE_MODES.indexOf(currentTab);
            if (cycleReplyState.modeIndex === -1) {
                cycleReplyState.modeIndex = 0; // Fallback to first mode if current tab not found
            }
        } catch (error) {
            cycleReplyState.modeIndex = 0; // Fallback to first mode on error
        }
        cycleReplyState.errorStreak = 0;
        cycleReplyState.serverErrorStreak = 0;
        cycleReplyState.lastProcessedTime = Date.now(); // Initialize to current time when starting
    }
};

async function startCycleReply() {
    if (!isOnCandidatePage()) {
        showToast('请在候选人页面使用循环回复', 'warning');
        return;
    }
    
    if (cycleReplyState.running) {
        await CycleReplyHelpers.requestStop();
        return;
    }
    
    // If batch processing is active, stop it and wait for it to complete
    if (window.batchProcessingActive) {
        CycleReplyHelpers.setButton(true, '⏹️ 正在停止...');
        showToast('正在停止批处理，然后停止循环处理', 'info');
        
        // Mark batch processing to stop
        window.stopBatchProcessing = true;
        
        // Wait for batch processing to complete
        const waitResult = await CycleReplyHelpers.waitUntil(
            () => !window.batchProcessingActive,
            { timeoutMs: 300000, stepMs: 500 } // Wait up to 5 minutes
        );
        
        if (!waitResult.success) {
            showToast('等待批处理停止超时，循环处理已取消', 'warning');
            CycleReplyHelpers.setButton(false);
        return;
    }
    
        // Now stop the cycle reply
        CycleReplyHelpers.resetState();
        CycleReplyHelpers.setButton(false);
        showToast('循环处理已停止', 'info');
        return;
    }
    
    // Check if "process all modes" checkbox is checked
    const processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
    
    CycleReplyHelpers.resetState();
    cycleReplyState.running = true;
    CycleReplyHelpers.setButton(true);
    
    try {
        if (processAllModes) {
            // Process all modes in cycle
        while (!cycleReplyState.stopRequested) {
            // Check if 5 minutes have passed without processing any candidate
            if (cycleReplyState.lastProcessedTime !== null) {
                const idleTime = Date.now() - cycleReplyState.lastProcessedTime;
                const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
                if (idleTime >= IDLE_TIMEOUT_MS) {
                    showToast('5分钟没有处理任何候选人，循环回复已停止', 'warning');
                    break;
                }
            }
            
            const mode = CYCLE_MODES[cycleReplyState.modeIndex];
            let result;
            
            try {
                const candidateTabs = CycleReplyHelpers.getCandidateTabs();
                result = await CycleReplyHelpers.processMode(mode, candidateTabs);
            } catch (error) {
                result = { success: false, error };
            }
            
            if (result.stopped) {
                break;
            }
                // handle timeout and other errors
            if (result.success === false) {
                    // Handle timeout as transient error - batch processing may have completed but flag not reset
                if (result.timeout) {
                        cycleReplyState.serverErrorStreak += 1;
                        console.warn(`[循环回复] 批处理超时 (${cycleReplyState.serverErrorStreak}/5): 可能已完成，继续下一模式`, result);
                        showToast(`批处理超时 (${cycleReplyState.serverErrorStreak}/5): 继续下一模式`, 'warning');
                        
                        // Only stop after 5 consecutive timeouts
                        if (cycleReplyState.serverErrorStreak >= 5) {
                            showToast('连续批处理超时超过 5 次，循环回复已停止', 'error');
                    break;
                }
                        
                        // Reset regular error streak on timeout (they're different issues)
                        cycleReplyState.errorStreak = 0;
                        // Don't reset serverErrorStreak - let it accumulate
                    } else {
                        const errorMessage = result.error?.message || result.error?.toString() || JSON.stringify(result.error) || '未知错误';
                        const errorStatus = result.error?.status || result.error?.statusCode || result.status;
                        const isServerError = errorStatus === 500 ||
                                            errorMessage.includes('500') || 
                                            errorMessage.includes('Server error (500)') ||
                                            errorMessage.includes('Internal Server Error') ||
                                            errorMessage.includes('ERR_CONNECTION_REFUSED') ||
                                            errorMessage.includes('Connection refused') ||
                                            errorMessage.includes('HTMX') ||
                                            errorMessage.includes('network') ||
                                            errorMessage.includes('NetworkError') ||
                                            errorMessage.includes('Failed to fetch');
                        
                        if (isServerError) {
                            // Handle 500 server errors separately - they're transient and shouldn't stop the loop
                            cycleReplyState.serverErrorStreak += 1;
                            console.warn(`[循环回复] 服务器错误 (${cycleReplyState.serverErrorStreak}/10): ${errorMessage}`);
                            showToast(`服务器错误 (${cycleReplyState.serverErrorStreak}/10): 跳过当前模式，继续处理`, 'warning');
                            
                            // Only stop after 10 consecutive 500 errors
                            if (cycleReplyState.serverErrorStreak >= 10) {
                                showToast('连续服务器错误超过 10 次，循环回复已停止', 'error');
                                break;
                            }
                            
                            // Reset regular error streak on server error (they're different issues)
                            // Don't reset serverErrorStreak - let it accumulate
                        } else {
                            // Handle non-500 errors normally
                            cycleReplyState.errorStreak += 1;
                            cycleReplyState.serverErrorStreak = 0; // Reset server error streak on non-server error
                            console.error(`[循环回复] 处理模式 ${mode} 出错:`, result.error || result);
                            showToast(`循环回复错误(${cycleReplyState.errorStreak}/2): ${errorMessage}`, 'error');
                
                if (cycleReplyState.errorStreak >= 2) {
                    showToast('连续错误超过 2 次，循环回复已停止', 'error');
                    break;
                            }
                        }
                }
            } else {
                    // Success - reset both error counters
                cycleReplyState.errorStreak = 0;
                    cycleReplyState.serverErrorStreak = 0;
            }
            cycleReplyState.modeIndex = (cycleReplyState.modeIndex + 1) % CYCLE_MODES.length;
            await CycleReplyHelpers.sleep(900);
            }
        } else {
            // Process only current mode
            const candidateTabs = CycleReplyHelpers.getCandidateTabs();
            const currentMode = candidateTabs.activeTab || 'recommend';
            
            showToast(`开始处理当前模式: ${currentMode}`, 'info');
            
            let result;
            try {
                result = await CycleReplyHelpers.processMode(currentMode, candidateTabs);
            } catch (error) {
                result = { success: false, error };
            }
            
            if (result.success === false) {
                const errorMessage = result.error?.message || result.error?.toString() || '未知错误';
                showToast(`处理失败: ${errorMessage}`, 'error');
            } else {
                showToast('处理完成', 'success');
            }
        }
    } finally {
        CycleReplyHelpers.resetState();
        CycleReplyHelpers.setButton(false);
        const processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
        showToast(processAllModes ? '循环回复已停止' : '处理已停止', 'info');
    }
}

// Expose to window for inline handlers
window.startCycleReply = startCycleReply;
window.CycleReplyHelpers = CycleReplyHelpers;
window.cycleReplyState = cycleReplyState; // Expose for candidates.html to update lastProcessedTime

// ============================================================================
// Centralized Candidate Card Update Handler
// ============================================================================
// Note: All candidate-specific functions moved to candidate_detail.html
// Candidate UI code moved to candidates.html
// Runtime check moved to base.html
// ============================================================================

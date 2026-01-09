// Alpine.js global store and components for BOSS招聘助手

// ============================================================================
// Toast Notification System (must be defined early)
// ============================================================================

/**
 * Toast notification helper
 * Displays temporary notification messages in the top-right corner
 */
const default_duration = 180_000;
function showToast(message, type = 'info', duration = default_duration) {
    // Also output to console based on type
    switch (type) {
        case 'error':
            console.error(message);
            break;
        case 'warning':
            console.warn(message);
            break;
        case 'success':
            break;
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
    
    // Toast styling with flexbox layout
    toast.className = `${colors[type] || colors.info} text-white px-4 py-3 rounded-lg shadow-lg mb-2 animate-fade-in flex items-center justify-between pointer-events-auto`;
    toast.dataset.type = type;
    
    // Content container (icon + text)
    const content = document.createElement('div');
    content.className = 'flex items-center gap-3';
    const msgSpan = document.createElement('span');
    msgSpan.textContent = message;
    content.appendChild(msgSpan);
    toast.appendChild(content);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'text-white hover:text-gray-200 focus:outline-none ml-4 p-1';
    closeBtn.innerHTML = `
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
    `;
    closeBtn.onclick = (e) => {
        e.stopPropagation();
        removeToast(toast);
    };
    toast.appendChild(closeBtn);
    
    const container = document.getElementById('toast-container');
    if (container) {
        // Expire all *previous* non-loading toasts
        expireAllToasts();

        container.appendChild(toast);
        
        // Timeout if duration > 0
        if (duration <= 0) {
            duration = default_duration;
        }

        // Mark custom duration for expireAllToasts protection
        if (duration !== default_duration) {
            toast.dataset.customDuration = 'true';
        }

        const timeoutId = setTimeout(() => {
            removeToast(toast);
        }, duration); 
        toast.dataset.timeoutId = timeoutId;
    }
    
    return toast;
}

function removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    
    // Clear timeout if it exists
    if (toast.dataset.timeoutId) {
        clearTimeout(parseInt(toast.dataset.timeoutId));
    }

    toast.classList.remove('animate-fade-in');
    toast.classList.add('animate-fade-out');
    setTimeout(() => toast.remove(), 300);
}


// Expire all toasts with a custom timeout (default 3000ms)
// Used to gently clear toasts when a new one comes or when operations finish
function expireAllToasts(timeoutMs = 1000) {
    const container = document.getElementById('toast-container');
    if (container) {
        const toasts = container.querySelectorAll(':scope > div');
        toasts.forEach(t => {
            // If already fading out, ignore
            if (t.classList.contains('animate-fade-out')) return;

            // Protect custom duration toasts
            if (t.dataset.customDuration === 'true') {
                return;
            }

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

// Expose showToast globally
window.showToast = showToast;

// ============================================================================
// Override global fetch() to auto-expire toasts
// Global HTMX Loading & Error Handling
// ============================================================================
const originalFetch = window.fetch;
window.fetch = async function(...args) {
    try {
        appendSpinnerToToast();
        const response = await originalFetch(...args);
        // Expire toasts after successful fetch (even if response has error status)
        expireAllToasts(1000);
        return response;
    } catch (error) {
        // Expire toasts on network error
        expireAllToasts(1000);
        throw error;
    }
};

// Gently dismiss toasts when HTMX request finishes or errors (3s delay)
document.body.addEventListener('htmx:afterRequest', () => expireAllToasts(3000));
document.body.addEventListener('htmx:responseError', () => expireAllToasts(3000));
document.body.addEventListener('htmx:responseError', function(evt) {
    if (evt.cancelBubble) return;
    const errorMsg = evt.detail?.error || evt.detail?.message || '请求失败';
    showToast(errorMsg, 'error');
});


// Catch general HTMX errors
document.body.addEventListener('htmx:sendError', function(evt) {
    console.error('HTMX send error:', evt.detail);
    // Only show toast if not already handled by htmxAjaxPromise
    if (!evt.detail.handled) {
        showToast(`${evt.detail.error || evt.detail.message || '请求失败'}，请重试`, 'error');
    }
});

// Show loading toast before request
document.body.addEventListener('htmx:beforeRequest', function(evt) {
    appendSpinnerToToast();
});

// Handle custom HX-Trigger events for toast notifications
document.body.addEventListener('showToast', function(evt) {
    if (evt.detail && evt.detail.message) {
        showToast(evt.detail.message, evt.detail.type || 'info');
    }
});

async function appendSpinnerToToast() {
    const container = document.getElementById('toast-container');
    if (container && container.lastElementChild) {
        const toast = container.lastElementChild;
        toast.dataset.type = 'loading'; // Mark as loading for auto-cleanup
        
        // Add spinner if not already present
        const content = toast.querySelector('.flex.items-center.gap-3');
        if (content && !content.querySelector('svg.animate-spin')) {
            const spinner = document.createElement('div');
            spinner.innerHTML = `
                <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
            `;
            // Insert spinner before the text
            content.prepend(spinner.firstElementChild);
        }
    }
}

// ============================================================================
// Browser Notification Helper
// ============================================================================
async function showBrowserNotification(title, body, icon = null, url = null) {
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
        
        // Handle click to open URL or focus window
        notification.onclick = () => {
            if (url) {
                window.open(url, '_blank');
            } else {
                window.focus();
            }
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
        stage: 'initial',
        
        dismiss() {
            // Store dismissed version in localStorage
            if (this.remoteCommit) {
                localStorage.setItem('dismissedVersion', this.remoteCommit);
            }
            this.show = false;
        }
    });
    
    // Load state on init
    Alpine.store('app').loadFromStorage();
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
            reject(new Error(`Target element not found: ${options.target}`));
            return;
        }
        
        // Listen for swap completion
        const afterSwap = (evt) => {
            // Check if this swap is for our target element
            const swapTarget = evt.target;
            const isTargetSwap = swapTarget === target || swapTarget?.id === target.id;
            if (isTargetSwap) {
                cleanup();
                resolve(target.textContent.trim());
            }
        };
        
        const onError = (evt) => {
            cleanup();
            const errorMsg = evt.detail?.error || evt.detail?.message || 'HTMX request failed';
            reject(new Error(errorMsg));
        };
        
        const cleanup = () => {
            document.removeEventListener('htmx:afterSwap', afterSwap);
            document.removeEventListener('htmx:responseError', onError);
        };
    
        
        // Listen on document to catch both regular and OOB swaps
        document.addEventListener('htmx:afterSwap', afterSwap, {once: true});
        document.addEventListener('htmx:responseError', onError, {once: true});
        
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
        
        // Always load candidates list (removed the skip logic)
        // Use the activeTab from candidateTabs component, fallback to mode
        const activeTab = candidateTabs?.activeTab || mode;
        
        try {
            await window.loadCandidatesList(activeTab);
            // await this.waitUntil(
            //     () => candidateList.querySelectorAll('.candidate-card').length > 0 || candidateList.querySelector('#empty-message'),
            //     { timeoutMs: 5000 }
            // );
        } catch (error) {
            return { success: false, error: error };
        }
        
        const candidateCards = candidateList.querySelectorAll('.candidate-card');
        return { success: true, candidateCards };
    },
    
    
    async processMode(mode, candidateTabs) {
        const isCurrentTab = candidateTabs.activeTab === mode;
        
        if (!isCurrentTab) {
            showToast(`处理: 切换到 ${mode}`, 'info');
            candidateTabs.switchTab(mode);
            await this.sleep(350);
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
    
    CycleReplyHelpers.resetState();
    
    // Capture currently selected candidate to resume from (if any)
    let activeCard = document.querySelector('.candidate-card.bg-blue-50');
    cycleReplyState.running = true;
    CycleReplyHelpers.setButton(true);
    
    let total_processed = 0;
    let total_failed = 0;
    let total_skipped = 0;
    // Start idle watchdog
    const watchdogId = setInterval(() => {
        if (!cycleReplyState.running) {
            clearInterval(watchdogId);
            return;
        }
        const idleTime = Date.now() - cycleReplyState.lastProcessedTime;
        const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
        if (idleTime >= IDLE_TIMEOUT_MS) {
            showToast('5分钟没有处理任何候选人，处理已停止', 'warning');
            stopProcessCandidate();
            clearInterval(watchdogId);
        }
    }, 10000); // Check every 10 seconds

    let processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
    try {
        while (cycleReplyState.running && !cycleReplyState.stopRequested) {
            const candidateTabs = CycleReplyHelpers.getCandidateTabs();
            const mode = processAllModes ? CYCLE_MODES[cycleReplyState.modeIndex] : (candidateTabs.activeTab || 'recommend');
            let cards = Array.from(document.querySelectorAll('.candidate-card'));
            if (cards.length === 0) {
                const result = await CycleReplyHelpers.processMode(mode, candidateTabs);
                if (result.stopped) {
                    break;
                }
                if (result.success === false) {
                    cycleReplyState.errorStreak += 1;
                    console.error(`处理模式 ${mode} 出错 (${cycleReplyState.errorStreak}/10): ${result.errorMessage}`);
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
                cards = Array.from(result.candidateCards);
            }

            // Filter cards if we need to resume from a specific one
            if (activeCard) {
                const startIndex = cards.indexOf(activeCard);
                if (startIndex !== -1) {
                    console.log(`[${mode}] Resuming from candidate index ${startIndex} (Skipping ${startIndex} items)`);
                    cards = cards.slice(startIndex);
                }
            }
            
            // If no candidates found, stop processing (prevents infinite loop)
            if (cards.length === 0) {
                console.log(`[${mode}] 无候选人可处理，停止`);
                if (!processAllModes) break; // Stop if processing single mode
                cycleReplyState.modeIndex = (cycleReplyState.modeIndex + 1) % CYCLE_MODES.length;
                await CycleReplyHelpers.sleep(1000);
                continue;
            }
            
            let processed = 0;
            let failed = 0;
            let skipped = 0;
            
            // Process each candidate
            console.log(`[${mode}] 开始处理 ${cards.length} 个候选人`);
            for (const card of cards) {
                activeCard = null; // Reset active card once it starts processing
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
            processAllModes = document.getElementById('process-all-modes-checkbox')?.checked || false;
            if (processAllModes) {
                cycleReplyState.modeIndex = (cycleReplyState.modeIndex + 1) % CYCLE_MODES.length;
            } else {
                // If not processing all modes, refresh the current candidate list and continue
                console.log(`[${mode}] 准备刷新候选人列表以继续处理...`);
                // Scroll recommendation frame to load more candidates (only for recommend mode)
                if (mode === 'recommend') {
                    await fetch('/candidates/scroll-recommendations', { method: 'POST' });
                }
            }
            await CycleReplyHelpers.sleep(1000);
            // Clear the list so the next iteration forces a fetch
            if (!cycleReplyState.stopRequested) {
                const candidateList = document.getElementById('candidate-list');
                if (candidateList) {
                   candidateList.innerHTML = '';
                }
            }
        }
    } catch (error) {
        console.error('处理候选人时发生错误:', error);
        showToast('处理候选人时发生错误', 'error');
    } finally {
        // Re-enable candidate cards via event
        CycleReplyHelpers.resetState();
        CycleReplyHelpers.setButton(false);
        document.dispatchEvent(new CustomEvent('candidates:enable-cards'));
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

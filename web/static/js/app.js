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
            window.selectedCandidateId = null;
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
            
            // Also check for error divs that might not have those classes
            // Look for divs that contain error text but aren't candidate cards
            candidateList.querySelectorAll('div').forEach(div => {
                if (!div.closest('.candidate-card') && 
                    (div.textContent.includes('失败') || 
                     div.textContent.includes('错误') || 
                     div.textContent.includes('请求失败') ||
                     div.classList.contains('text-red-500'))) {
                    div.remove();
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
                    // Clear existing content
                    candidateList.innerHTML = '';
                    
                    // Parse the incoming HTML to extract candidate cards
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = html;
                    const newCards = tempDiv.querySelectorAll('.candidate-card');
                    
                    console.log(`Parsed ${newCards.length} candidate cards from response`);
                    
                    let skippedCount = 0;
                    
                    // Convert NodeList to Array and append all cards
                    const cardsArray = Array.from(newCards);
                    
                    cardsArray.forEach(newCard => {
                        let candidate_id = newCard.getAttribute('data-candidate-id');
                        
                        // If no data-candidate-id, try to generate a fallback identifier using name
                        if (!candidate_id || candidate_id.trim() === '') {
                            const nameElement = newCard.querySelector('h3');
                            const name = nameElement ? nameElement.textContent.trim() : '';
                            
                            if (name) {
                                // Use name as temporary identifier for unsaved candidates
                                candidate_id = `temp_${name}`.replace(/\s+/g, '_');
                                newCard.setAttribute('data-candidate-id', candidate_id);
                                console.log(`Generated temporary ID for unsaved candidate: ${candidate_id}`);
                            } else {
                                // Still no identifier, skip this card
                                console.warn('Skipping card without name:', newCard);
                                skippedCount++;
                                return;
                            }
                        }
                        
                        // Clone and append the card
                        const clonedCard = newCard.cloneNode(true);
                        candidateList.appendChild(clonedCard);
                    });
                    
                    const loadedCount = cardsArray.length - skippedCount;
                    console.log(`Loaded ${loadedCount} candidate cards (${skippedCount} skipped)`);
                    
                    // Tell HTMX to process the new content
                    htmx.process(candidateList);
                    
                    this.loading = false;
                    
                    // Count how many candidates are in the list now - use a fresh query after all updates
                    // Use requestAnimationFrame to ensure DOM is updated before counting
                    const self = this;
                    requestAnimationFrame(() => {
                        const candidateCards = candidateList.querySelectorAll('.candidate-card');
                        const count = candidateCards.length;
                        console.log(`Final count: ${count} candidate cards in the list`);
                        
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
document.body.addEventListener('htmx:responseError', function(evt) {
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

window.selectedCandidateId = null;

// Intercept candidate card clicks to prevent duplicate requests
document.body.addEventListener('htmx:beforeRequest', function(event) {
    // Check if this is a candidate card click
    if (!event.detail.elt.classList.contains('candidate-card')) {
        return;  // Not a candidate card, allow request normally
    }
    
    const candidate_id = event.detail.elt.getAttribute('data-candidate-id');
    
    // If clicking the same candidate, prevent redundant fetch
    if (window.selectedCandidateId === candidate_id) {
        console.log('Same candidate already selected, skipping fetch');
        event.preventDefault();  // This cancels the HTMX request
        
        // Hide loading indicator (since afterRequest won't fire for cancelled requests)
        const loadingIndicator = document.getElementById('global-loading');
        if (loadingIndicator) {
            loadingIndicator.classList.remove('htmx-request');
        }
        
        return;
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
    
    // Update selected ID
    window.selectedCandidateId = candidate_id;
    console.log('Selected candidate:', candidate_id);
    
    // Allow HTMX to proceed
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
        // FastAPI normal response
        return await response.json();
    }
    
    // Try parse the JSON error body
    let errorData;
    try {
        errorData = await response.json();
    } catch {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    
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

// ============================================================================
// Helper functions to disable/enable candidate cards
// ============================================================================

function disableAllCards() {
    const cards = document.querySelectorAll('.candidate-card');
    cards.forEach(card => {
        card.style.pointerEvents = 'none';
        card.style.opacity = '0.6';
    });
}

function enableAllCards() {
    const cards = document.querySelectorAll('.candidate-card');
    cards.forEach(card => {
        card.style.pointerEvents = '';
        card.style.opacity = '';
    });
}

// ============================================================================
// Batch Processing Functions
// ============================================================================

// Global flags for batch processing control
window.batchProcessingActive = false;
window.stopBatchProcessing = false;

/**
 * Process all candidate cards sequentially
 */
window.processAllCandidates = async function processAllCandidates() {
    const cards = document.querySelectorAll('.candidate-card');
    if (cards.length === 0) {
        showToast('没有找到候选人', 'warning');
        return;
    }
    
    const total = cards.length;
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
    
    showToast(`开始批量处理 ${total} 个候选人`, 'info');
    
    for (let i = 0; i < cards.length; i++) {
        // Check if user requested stop
        if (window.stopBatchProcessing) {
            showToast(`批量处理已停止 (${processed}/${total} 完成)`, 'warning');
            break;
        }
        
        const card = cards[i];
        const cardData = JSON.parse(card.getAttribute('hx-vals'));
        const name = cardData.name || `候选人 ${i + 1}`;
        
        showToast(`正在处理候选人 ${i + 1}/${total}: ${name}`, 'info');
        
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
                    reject(new Error(evt.detail.error || 'HTMX request failed'));
                };
                
                detailPane.addEventListener('htmx:afterSwap', onSwap, { once: true });
                detailPane.addEventListener('htmx:responseError', onError, { once: true });
                
                // Reset selectedCandidateId to force HTMX request even if card is already selected
                // This prevents timeout when batch processing starts with the first card already selected
                const cardCandidateId = card.getAttribute('data-candidate-id');
                if (window.selectedCandidateId === cardCandidateId) {
                    window.selectedCandidateId = null;
                }
                
                // Scroll card into view before triggering click
                card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
                
                // Trigger HTMX click
                htmx.trigger(card, 'click');
            });
            
            // Wait for process_candidate() to complete
            await processingPromise;
            
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
    
    // Reset button
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
// Global HTMX Event Listeners
// ============================================================================

// HTMX event listeners for global notifications
document.body.addEventListener('htmx:afterRequest', (event) => {
    if (event.detail.successful && event.detail.xhr.status === 200) {
        // Check for HX-Trigger header
        const trigger = event.detail.xhr.getResponseHeader('HX-Trigger');
        if (trigger) {
            try {
                const triggers = JSON.parse(trigger);
                if (triggers.showMessage) {
                    showToast(triggers.showMessage.message, triggers.showMessage.type);
                }
            } catch (e) {
                // Simple string trigger
                if (trigger === 'dataUpdated') {
                    showToast('数据已更新', 'success');
                }
            }
        }
    }
});

// Note: htmx:responseError is already handled above in the Global HTMX Error Handling section

// ============================================================================
// Centralized Candidate Card Update Handler
// ============================================================================

/**
 * Check if a card matches the given identifiers
 */
function cardMatches(cardData, identifiers) {
    const { chat_id, conversation_id, candidate_id, name, job_applied } = identifiers;
    
    // Match by multiple identifiers (check truthy values, not just existence):
    // 1. chat_id match (both must be truthy and equal)
    // 2. conversation_id match (both must be truthy and equal)
    // 3. candidate_id match (both must be truthy and equal)
    // 4. Fallback: name + job_applied match (both must be truthy and equal)
    const chatMatch = chat_id && cardData.chat_id && cardData.chat_id === chat_id;
    const conversationMatch = conversation_id && cardData.conversation_id && cardData.conversation_id === conversation_id;
    const candidateMatch = candidate_id && cardData.candidate_id && cardData.candidate_id === candidate_id;
    const nameMatch = name && job_applied && cardData.name && cardData.job_applied && 
                     cardData.name === name && cardData.job_applied === job_applied;
    
    return chatMatch || conversationMatch || candidateMatch || nameMatch;
}

/**
 * Update a candidate card with the given updates
 */
function applyCardUpdate(card, updates, identifiers) {
    const cardData = JSON.parse(card.getAttribute('hx-vals') || '{}');
    
    // Update the card's data attributes
    Object.assign(cardData, updates);
    Object.assign(cardData, identifiers);
    
    // Apply updates to candidateData
    card.setAttribute('hx-vals', JSON.stringify(cardData));
    
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
    
    // Update tags (greeted and saved only - viewed is handled by card opacity)
    const tagsContainer = card.querySelector('#candidate-tags');
    // Update greeted tag
    if ('greeted' in updates) {
        const greetedTag = tagsContainer.querySelector('[data-tag="greeted"]');
        if (updates.greeted) {
            greetedTag.classList.remove('hidden');
        } else {
            greetedTag.classList.add('hidden');
        }
    }
    
    // Update saved tag
    if ('saved' in updates) {
        const savedTag = tagsContainer.querySelector('[data-tag="saved"]');
        if (updates.saved) {
            savedTag.classList.remove('hidden');
        } else {
            savedTag.classList.add('hidden');
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
    let found = false;
    
    candidateCards.forEach(card => {
        const cardData = JSON.parse(card.getAttribute('hx-vals') || '{}');
        
        if (cardMatches(cardData, identifiers)) {
            applyCardUpdate(card, updates, identifiers);
            found = true;
        }
    });
    
    if (!found) {
        const identifier = identifiers.chat_id || identifiers.conversation_id || identifiers.candidate_id;
        console.warn('candidate:update: could not find matching card', {
            identifier,
            identifiers,
            totalCards: candidateCards.length
        });
    }
});

// ============================================================================
// Service Status Check
// ============================================================================

/**
 * Periodically check service status and update the status indicator
 */
function initServiceStatusCheck() {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    
    if (!statusDot || !statusText) {
        return; // Status indicator not found
    }
    
    let statusCheckInterval = null;
    
    async function checkServiceStatus() {
        try {
            // Create abort controller for timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout
            
            const response = await fetch('/status', {
                method: 'GET',
                headers: { 'Accept': 'application/json' },
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (response.ok) {
                const data = await response.json();
                // Service is running
                statusDot.className = 'w-2 h-2 bg-green-500 rounded-full animate-pulse';
                statusText.textContent = '服务运行中';
                statusText.className = 'text-sm text-gray-600';
            } else {
                // Service returned error
                statusDot.className = 'w-2 h-2 bg-yellow-500 rounded-full animate-pulse';
                statusText.textContent = '服务异常';
                statusText.className = 'text-sm text-yellow-600';
            }
        } catch (error) {
            // Service is down or unreachable (network error, timeout, etc.)
            if (error.name === 'AbortError') {
                statusDot.className = 'w-2 h-2 bg-yellow-500 rounded-full animate-pulse';
                statusText.textContent = '服务响应超时';
                statusText.className = 'text-sm text-yellow-600';
            } else {
                statusDot.className = 'w-2 h-2 bg-red-500 rounded-full';
                statusText.textContent = '服务离线';
                statusText.className = 'text-sm text-red-600';
            }
        }
    }
    
    // Check immediately on page load
    checkServiceStatus();
    
    // Then check every 30 seconds
    statusCheckInterval = setInterval(checkServiceStatus, 30000);
    
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
    });
}

// Initialize service status check when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initServiceStatusCheck);
} else {
    initServiceStatusCheck();
}

// ============================================================================
// Version Update Check
// ============================================================================

/**
 * Periodically check for new git versions and show modal if available
 */
function initVersionUpdateCheck() {
    let versionCheckInterval = null;
    
    async function checkVersionUpdate() {
        try {
            // Create abort controller for timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
            
            const response = await fetch('/version/check', {
                method: 'GET',
                headers: { 'Accept': 'application/json' },
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                return; // Silently fail
            }
            
            const data = await response.json();
            
            if (data.has_update && data.remote_commit) {
                // Check if this version was already dismissed
                const dismissedVersion = localStorage.getItem('dismissedVersion');
                if (dismissedVersion === data.remote_commit) {
                    return; // User already dismissed this version
                }
                
                // Show modal
                if (window.Alpine && Alpine.store('versionUpdateModal')) {
                    const modal = Alpine.store('versionUpdateModal');
                    modal.title = '新版本可用';
                    modal.message = data.message || '检测到新的 Git 版本可用，建议更新以获取最新功能。';
                    modal.currentCommit = data.current_commit;
                    modal.remoteCommit = data.remote_commit;
                    modal.currentBranch = data.current_branch;
                    modal.repoUrl = data.repo_url;
                    modal.show = true;
                }
            }
        } catch (error) {
            // Silently fail - don't show errors for version checks
            console.debug('Version check failed:', error);
        }
    }
    
    // Check immediately on page load (after a short delay to let page load)
    setTimeout(checkVersionUpdate, 3000);
    
    // Then check every 5 minutes
    versionCheckInterval = setInterval(checkVersionUpdate, 300000);
    
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (versionCheckInterval) {
            clearInterval(versionCheckInterval);
        }
    });
}

// Initialize version update check when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initVersionUpdateCheck);
} else {
    initVersionUpdateCheck();
}

// ============================================================================
// Note: All candidate-specific functions moved to candidate_detail.html
// ============================================================================
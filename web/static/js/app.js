// Alpine.js global store and components for BOSS招聘助手

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
            
            const params = new URLSearchParams({
                mode: mode,
                chat_type: chat_type,
                job_applied: job_title,
                job_id: job_id
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
                    if (!response.ok || html.includes('text-red-500') || html.includes('失败')) {
                        // Error: replace list content with error message
                        candidateList.innerHTML = html;
                        this.loading = false;
                        showToast('加载失败，请重试', 'error');
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
                    showToast('加载失败，请重试', 'error');
                });
        }
    };
}

// Global function for HTMX events to call updateURL
window.updateCandidateURL = function() {
    // Find the Alpine component instance
    const candidateTabsElement = document.querySelector('[x-data*="candidateTabs"]');
    if (candidateTabsElement && candidateTabsElement._x_dataStack) {
        const component = candidateTabsElement._x_dataStack[0];
        if (component && component.updateURL) {
            component.updateURL();
        }
    }
};

// Toast notification is defined in base.html and exposed as window.showToast
// No need to redefine it here

// ============================================================================
// Global HTMX Loading & Error Handling
// ============================================================================

// Show loading indicator before any HTMX request
document.body.addEventListener('htmx:beforeRequest', function(event) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.add('htmx-request');
    }
});

// Hide loading indicator after any HTMX request completes
document.body.addEventListener('htmx:afterRequest', function(event) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.remove('htmx-request');
    }
});

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', function(event) {
    const loadingIndicator = document.getElementById('global-loading');
    if (loadingIndicator) {
        loadingIndicator.classList.remove('htmx-request');
    }
    showToast('请求失败: ' + (event.detail.xhr.status || '网络错误'), 'error');
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
// Batch Processing (fallback - will be overridden by candidate_detail.html)
// ============================================================================

/**
 * Process all candidate cards sequentially
 * This is a fallback definition. The actual implementation is in candidate_detail.html
 * and will override this when that template loads.
 */
window.processAllCandidates = async function processAllCandidates() {
    showToast('请先点击一个候选人卡片以加载处理功能', 'warning');
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

document.body.addEventListener('htmx:responseError', (event) => {
    showToast('请求失败，请重试', 'error');
});

// ============================================================================
// Note: All candidate-specific functions moved to candidate_detail.html
// ============================================================================
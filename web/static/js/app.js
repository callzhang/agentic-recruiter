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
            
            this.eventSource = new EventSource('/web/automation/stream');
            
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
            },
        
        loadCandidates() {
            console.log('Loading candidates, activeTab:', this.activeTab);
            
            this.loading = true;
            
            const jobSelector = document.getElementById('job-selector');
            const jobId = jobSelector?.value || jobSelector?.options[0]?.value;
            const jobTitle = jobSelector?.selectedOptions[0]?.getAttribute("data-title");
            
            // Check if job title is valid
            if (!jobTitle || jobTitle === '加载中...') {
                console.error('Job title not loaded yet');
                this.loading = false;
                showToast('请等待岗位列表加载完成后再查询', 'warning');
                return;
            }
            
            let mode, chatType;
            if (this.activeTab === 'recommend') {
                mode = 'recommend';
                chatType = '';
            } else {
                mode = 'chat';
                const tabMap = {
                    'greet': '新招呼',
                    'reply': '沟通中',
                    'followup': '牛人已读未回'
                };
                chatType = tabMap[this.activeTab] || '新招呼';
            }
            
            const params = new URLSearchParams({
                mode: mode,
                chat_type: chatType,
                job_title: jobTitle,
                job_id: jobId
            });
            
            const url = `/web/candidates/list?${params.toString()}`;
            console.log('Fetching:', url);
            
            // Remove initial message and empty message if they exist
            const initialMsg = document.getElementById('initial-message');
            if (initialMsg) {
                initialMsg.remove();
            }
            const emptyMsg = document.getElementById('empty-message');
            if (emptyMsg) {
                emptyMsg.remove();
            }
            
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
                    
                    // Success: append candidate cards
                    candidateList.insertAdjacentHTML('beforeend', html);
                    
                    // Tell HTMX to process the new content
                    htmx.process(candidateList);
                    
                    this.loading = false;
                    
                    // Count how many candidates were actually loaded
                    const candidateCards = document.querySelectorAll('#candidate-list .candidate-card');
                    const count = candidateCards.length;
                    
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
                        showToast(`加载完成，共 ${count} 个候选人`, 'success');
                    }
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

// Form validation helper
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;
    
    const inputs = form.querySelectorAll('[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('border-red-500');
            isValid = false;
        } else {
            input.classList.remove('border-red-500');
        }
    });
    
    return isValid;
}

// Toast notification
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `alert px-6 py-4 rounded-lg shadow-lg mb-2 ${getToastClass(type)}`;
    toast.textContent = message;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('opacity-0', 'transition-opacity');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed top-4 right-4 z-50 flex flex-col';
    document.body.appendChild(container);
    return container;
}

function getToastClass(type) {
    const classes = {
        'info': 'bg-blue-500 text-white',
        'success': 'bg-green-500 text-white',
        'warning': 'bg-yellow-500 text-white',
        'error': 'bg-red-500 text-white'
    };
    return classes[type] || classes['info'];
}

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
    
    const candidateId = event.detail.elt.getAttribute('data-candidate-id');
    
    // If clicking the same candidate, prevent redundant fetch
    if (window.selectedCandidateId === candidateId) {
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
    window.selectedCandidateId = candidateId;
    console.log('Selected candidate:', candidateId);
    
    // Allow HTMX to proceed
});

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
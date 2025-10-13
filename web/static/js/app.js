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
            // Clear list when switching tabs
            const list = document.getElementById('candidate-list');
            if (list) {
                list.innerHTML = '';
            }
        },
        
        loadCandidates() {
            console.log('Loading candidates, activeTab:', this.activeTab);
            
            this.loading = true;
            
            const jobSelector = document.getElementById('job-selector');
            const jobTitle = jobSelector?.value || jobSelector?.options[0]?.value;
            
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
                    'chatting': '沟通中',
                    'noReply': '牛人已读未回'
                };
                chatType = tabMap[this.activeTab] || '新招呼';
            }
            
            const params = new URLSearchParams({
                mode: mode,
                chat_type: chatType,
                job_title: jobTitle
                // No limit - load all candidates from browser page
            });
            
            const url = `/web/candidates/list?${params.toString()}`;
            console.log('Fetching:', url);
            
            // Remove initial message if it exists
            const initialMsg = document.getElementById('initial-message');
            if (initialMsg) {
                initialMsg.remove();
            }
            
            htmx.ajax('GET', url, {
                target: '#candidate-list',
                swap: 'beforeend'  // Append instead of replace
            }).then((response) => {
                console.log('Loaded successfully');
                this.loading = false;
                
                // Count how many candidates were actually loaded
                const candidateCards = document.querySelectorAll('#candidate-list .candidate-card');
                showToast(`加载完成，共 ${candidateCards.length} 个候选人`, 'success');
            }).catch((err) => {
                console.error('Failed:', err);
                this.loading = false;
                showToast('加载失败，请重试', 'error');
            });
        }
    };
}

// Note: updateTabStyles is now handled by Alpine.js :class bindings
// This function is kept for backward compatibility but is no longer needed

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

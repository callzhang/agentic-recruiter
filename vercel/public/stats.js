// Stats Page JavaScript for Vercel Homepage
// Extracted from web/static/js/app.js

// ============================================================================
// Daily Chart Component (Bar Chart for 7-day new/SEEK stats using Chart.js)
// ============================================================================

// Store chart instances to allow proper cleanup
const chartInstances = new Map();

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
    
    // Format date (MM-DD)
    function formatDate(dateStr) {
        try {
            const date = new Date(dateStr);
            return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        } catch {
            return dateStr.split('T')[0].slice(5) || dateStr.slice(-5);
        }
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
    
    // Store chart instance
    chartInstances.set(chartId, chart);
}

// Initialize charts when DOM is ready
function initDailyCharts() {
    document.querySelectorAll('.daily-chart-container').forEach(container => {
        renderDailyChart(container);
    });
}

// Initialize charts on page load
document.addEventListener('DOMContentLoaded', initDailyCharts);

/**
 * Render daily candidate count line chart
 */
function renderDailyCandidateChart() {
    const container = document.querySelector('.daily-candidate-chart-container');
    if (!container) return;
    
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
        canvas = document.createElement('canvas');
        canvas.style.maxHeight = '250px';
        container.appendChild(canvas);
    }
    
    // Destroy existing chart if it exists
    const chartId = container.getAttribute('data-chart-id') || `candidate-chart-${Date.now()}`;
    container.setAttribute('data-chart-id', chartId);
    
    if (chartInstances.has(chartId)) {
        chartInstances.get(chartId).destroy();
        chartInstances.delete(chartId);
    }
    
    // Format date (MM-DD)
    function formatDate(dateStr) {
        try {
            const date = new Date(dateStr);
            return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        } catch {
            return dateStr.split('T')[0].slice(5) || dateStr.slice(-5);
        }
    }
    
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
    
    // Store chart instance
    chartInstances.set(chartId, chart);
}

// ============================================================================
// Stats Page Component (Renders stats from JSON API)
// ============================================================================

/**
 * Render quick stats cards
 */
function renderQuickStats(data) {
    const container = document.getElementById('quick-stats');
    if (!container) return;
    
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
 * Get color for a stage
 * @param {string} stage - Stage name (PASS, CHAT, SEEK, CONTACT)
 * @returns {string} Color in rgba format
 */
function getStageColor(stage) {
    const colors = {
        'PASS': 'rgba(156, 163, 175, 0.8)',      // gray-400
        'CHAT': 'rgba(59, 130, 246, 0.8)',       // blue-500
        'SEEK': 'rgba(251, 191, 36, 0.8)',       // amber-400
        'CONTACT': 'rgba(34, 197, 94, 0.8)',     // green-500
    };
    return colors[stage] || 'rgba(156, 163, 175, 0.8)';
}

/**
 * Get border color for a stage
 * @param {string} stage - Stage name (PASS, CHAT, SEEK, CONTACT)
 * @returns {string} Color in rgba format
 */
function getStageBorderColor(stage) {
    const colors = {
        'PASS': 'rgba(156, 163, 175, 1)',        // gray-400
        'CHAT': 'rgb(73, 107, 162)',         // blue-500
        'SEEK': 'rgb(251, 251, 36)',         // amber-400
        'CONTACT': 'rgb(78, 229, 28)',       // green-500
    };
    return colors[stage] || 'rgba(156, 163, 175, 1)';
}

/**
 * Render pie chart for conversion data using Chart.js
 * @param {HTMLElement} container - Container element with data-conversions attribute
 */
function renderConversionPieChart(container) {
    const conversionsDataStr = container.getAttribute('data-conversions');
    if (!conversionsDataStr) return;
    
    const conversionsData = JSON.parse(conversionsDataStr);
    if (!conversionsData || conversionsData.length === 0) return;
    
    // Check if Chart.js is available
    if (typeof Chart === 'undefined') {
        console.error('Chart.js is not loaded');
        return;
    }
    
    // Find or create canvas element
    let canvas = container.querySelector('canvas');
    if (!canvas) {
        // Create canvas element
        canvas = document.createElement('canvas');
        canvas.style.maxHeight = '250px';
        container.insertBefore(canvas, container.firstChild);
    }
    
    // Destroy existing chart if it exists
    const chartId = container.getAttribute('data-chart-id') || `pie-chart-${Date.now()}-${Math.random()}`;
    container.setAttribute('data-chart-id', chartId);
    
    if (chartInstances.has(chartId)) {
        chartInstances.get(chartId).destroy();
        chartInstances.delete(chartId);
    }
    
    // Filter and prepare data for pie chart
    // Include all items with valid stage (even if count is 0) to show all stages in legend
    const validData = conversionsData.filter(c => c && c.stage);
    
    if (validData.length === 0) {
        console.warn('No valid conversion data for pie chart');
        return;
    }
    
    const labels = validData.map(c => c.stage);
    const data = validData.map(c => c.count || 0);
    const backgroundColor = validData.map(c => getStageColor(c.stage));
    const borderColor = validData.map(c => getStageBorderColor(c.stage));
    
    // Calculate total for percentage display (only count > 0 for percentage calculation)
    const total = data.reduce((sum, val) => sum + val, 0);
    
    // Create Chart.js pie chart
    const chart = new Chart(canvas, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: backgroundColor,
                borderColor: borderColor,
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'right',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: {
                            size: 12
                        },
                        generateLabels: function(chart) {
                            // Manually generate labels for all stages, even if count is 0
                            const legendLabels = [];
                            for (let i = 0; i < labels.length; i++) {
                                const value = data[i] || 0;
                                const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                const stageName = labels[i] || 'Unknown';
                                const bgColor = backgroundColor[i];
                                const borderColorValue = borderColor[i];
                                
                                legendLabels.push({
                                    text: `${stageName}: ${value} (${percentage}%)`,
                                    fillStyle: bgColor,
                                    strokeStyle: borderColorValue,
                                    lineWidth: 2,
                                    hidden: false, // Always show, even if value is 0
                                    index: i
                                });
                            }
                            return legendLabels;
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            const conversion = validData[context.dataIndex];
                            const rate = conversion ? (conversion.rate * 100).toFixed(0) : '0';
                            return [
                                `${label}: ${value} (${percentage}%)`,
                                `转化率: ${rate}%`
                            ];
                        }
                    }
                }
            }
        }
    });
    
    // Store chart instance
    chartInstances.set(chartId, chart);
    
    // Also store reference on canvas for quick lookup
    canvas.chart = chart;
}

// Initialize conversion pie charts when DOM is ready or after rendering
function initConversionPieCharts() {
    document.querySelectorAll('.conversion-pie-chart-container').forEach(container => {
        renderConversionPieChart(container);
    });
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
        const conversionsData = job.conversions || [];
        
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
                        <div class="conversion-pie-chart-container p-4 bg-gray-50 rounded-lg" data-conversions='${JSON.stringify(conversionsData)}' style="min-height: 250px;">
                            <!-- Chart.js canvas will be inserted here -->
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    
    // Initialize charts after rendering
    initDailyCharts();
    initConversionPieCharts();
}

/**
 * Load and render stats page
 */
async function loadStatsPage() {
    const quickStatsContainer = document.getElementById('quick-stats');
    const jobStatsContainer = document.getElementById('job-stats');
    
    if (!quickStatsContainer && !jobStatsContainer) {
        console.log('Stats containers not found, skipping loadStatsPage');
        return; // Not on stats page
    }
    
    console.log('Loading stats page...');
    try {
        const response = await fetch('/api/stats', {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Stats data received:', data);
        
        if (data.success) {
            if (quickStatsContainer) {
                renderQuickStats(data);
            }
            if (jobStatsContainer) {
                renderJobStats(data);
            }
        } else {
            console.error('Stats API returned success=false:', data);
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
        if (quickStatsContainer) {
            quickStatsContainer.innerHTML = '<div class="text-red-600">加载统计数据失败: ' + error.message + '</div>';
        }
        if (jobStatsContainer) {
            jobStatsContainer.innerHTML = '<div class="text-red-600">加载统计数据失败: ' + error.message + '</div>';
        }
    }
}

// Load stats on page load (for index page)
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the index page
    if (document.getElementById('quick-stats') || document.getElementById('job-stats')) {
        loadStatsPage();
    }
});


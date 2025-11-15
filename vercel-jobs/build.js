#!/usr/bin/env node
/**
 * Build script to inject API_BASE_URL into index.html
 * This reads the Vercel environment variable and injects it as a meta tag
 */

const fs = require('fs');
const path = require('path');

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:5001';
const indexPath = path.join(__dirname, 'index.html');

console.log(`Injecting API_BASE_URL: ${API_BASE_URL}`);

let html = fs.readFileSync(indexPath, 'utf8');

// Inject meta tag in head if not present
if (!html.includes('name="api-base-url"')) {
    html = html.replace(
        '<head>',
        `<head>\n    <meta name="api-base-url" content="${API_BASE_URL}">`
    );
} else {
    // Update existing meta tag
    html = html.replace(
        /<meta name="api-base-url" content="[^"]*">/,
        `<meta name="api-base-url" content="${API_BASE_URL}">`
    );
}

fs.writeFileSync(indexPath, html, 'utf8');
console.log('✅ API_BASE_URL injected successfully');


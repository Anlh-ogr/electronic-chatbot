/* ============================================
   Simple Markdown Renderer
   ============================================ */

/**
 * Chuyển markdown text → HTML.
 * Hỗ trợ: bold, italic, code, links, lists, tables, headings.
 */
function renderMarkdown(text) {
    if (!text) return '';

    let html = text;

    // Escape HTML (trừ markdown)
    html = html.replace(/&/g, '&amp;')
               .replace(/</g, '&lt;')
               .replace(/>/g, '&gt;');

    // Code blocks ```
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(_, lang, code) {
        return '<pre><code class="lang-' + lang + '">' + code.trim() + '</code></pre>';
    });

    // Inline code `
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold **text**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic *text*
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Headers ## 
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Tables
    html = renderTables(html);

    // Lists
    html = renderLists(html);

    // Line breaks
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');

    // Wrap in paragraphs
    if (!html.startsWith('<')) {
        html = '<p>' + html + '</p>';
    }

    return html;
}

/**
 * Render LaTeX formulas inside an existing message element.
 * Supports inline: $...$, \(...\)
 * Supports block: $$...$$, \[...\]
 */
function renderLatexInElement(element) {
    if (!element || typeof window.renderMathInElement !== 'function') {
        return;
    }

    try {
        window.renderMathInElement(element, {
            delimiters: [
                { left: '$$', right: '$$', display: true },
                { left: '\\[', right: '\\]', display: true },
                { left: '$', right: '$', display: false },
                { left: '\\(', right: '\\)', display: false },
            ],
            ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
            throwOnError: false,
            strict: 'ignore',
        });
    } catch (err) {
        console.warn('LaTeX render skipped:', err);
    }
}

function renderTables(text) {
    const lines = text.split('\n');
    let result = [];
    let inTable = false;
    let tableLines = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith('|') && line.endsWith('|')) {
            if (!inTable) {
                inTable = true;
                tableLines = [];
            }
            tableLines.push(line);
        } else {
            if (inTable) {
                result.push(buildTable(tableLines));
                inTable = false;
                tableLines = [];
            }
            result.push(lines[i]);
        }
    }
    if (inTable) {
        result.push(buildTable(tableLines));
    }

    return result.join('\n');
}

function buildTable(lines) {
    if (lines.length < 2) return lines.join('\n');

    let html = '<table>';
    
    for (let i = 0; i < lines.length; i++) {
        // Skip separator row (|---|---|)
        if (/^\|[\s\-:|]+\|$/.test(lines[i])) continue;

        const cells = lines[i].split('|').filter(c => c.trim() !== '');
        const tag = i === 0 ? 'th' : 'td';
        
        html += '<tr>';
        for (const cell of cells) {
            html += `<${tag}>${cell.trim()}</${tag}>`;
        }
        html += '</tr>';
    }
    
    html += '</table>';
    return html;
}

function renderLists(text) {
    const lines = text.split('\n');
    let result = [];
    let inList = false;

    for (const line of lines) {
        const match = line.match(/^(\s*)[-*]\s+(.+)$/);
        if (match) {
            if (!inList) {
                result.push('<ul>');
                inList = true;
            }
            result.push(`<li>${match[2]}</li>`);
        } else {
            if (inList) {
                result.push('</ul>');
                inList = false;
            }
            result.push(line);
        }
    }
    if (inList) {
        result.push('</ul>');
    }

    return result.join('\n');
}

// Export for use
window.renderMarkdown = renderMarkdown;
window.renderLatexInElement = renderLatexInElement;

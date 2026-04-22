"""
Orchestra — Live Dashboard Server
HTTP server + SPA for real-time monitoring of Orchestra sessions.

Run: python dashboard_server.py
Open: http://localhost:8420

Features:
- Localhost-only binding (security)
- API endpoints for session data
- Single Page Application with auto-refresh
- Interleaved PM/Dev timeline
- Phase indicator with visual states
- No external dependencies (stdlib http.server + vanilla JS/CSS)
"""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import SESSIONS_DIR, DASHBOARD_PORT


# ─────────────────────────────────────────────
# SPA HTML — Complete inline (zero dependencies)
# ─────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎼 Orchestra Dashboard</title>
    <meta name="description" content="Real-time monitoring dashboard for Orchestra multi-agent system">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #07070d;
            --bg-secondary: #0e0e18;
            --bg-card: #141422;
            --bg-card-hover: #1a1a30;
            --bg-code: #0a0a14;
            --border: #1e1e3a;
            --border-hover: #2e2e50;
            --text-primary: #e4e4f0;
            --text-secondary: #7a7a9e;
            --text-dim: #50506e;

            --gemini-blue: #4a8af4;
            --gemini-glow: rgba(74, 138, 244, 0.08);
            --gemini-border: rgba(74, 138, 244, 0.25);
            --dev-purple: #a060f0;
            --dev-glow: rgba(160, 96, 240, 0.08);
            --dev-border: rgba(160, 96, 240, 0.25);

            --success: #2dd4a0;
            --success-bg: rgba(45, 212, 160, 0.08);
            --warning: #f0b040;
            --warning-bg: rgba(240, 176, 64, 0.08);
            --error: #f05050;
            --error-bg: rgba(240, 80, 80, 0.08);
            --info: #60a0f0;

            --radius: 10px;
            --radius-sm: 6px;
            --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);

            --gradient-header: linear-gradient(135deg, #4a8af4 0%, #8060e0 35%, #a060f0 65%, #e06080 100%);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Inter', -apple-system, system-ui, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow: hidden;
        }

        /* ── Header ── */
        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            padding: 0 1.5rem;
            height: 56px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            z-index: 100;
        }

        .header::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: var(--gradient-header);
            opacity: 0.4;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .header h1 {
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            background: var(--gradient-header);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.78rem;
            color: var(--text-dim);
        }

        .live-dot {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
            animation: livePulse 2s ease-in-out infinite;
        }

        @keyframes livePulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 8px var(--success); }
            50% { opacity: 0.5; box-shadow: 0 0 3px var(--success); }
        }

        /* ── Layout ── */
        .layout {
            display: grid;
            grid-template-columns: 280px 1fr;
            height: calc(100vh - 56px);
        }

        /* ── Sidebar ── */
        .sidebar {
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .sidebar-header {
            padding: 1rem 1rem 0.75rem;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-dim);
        }

        .session-list {
            flex: 1;
            overflow-y: auto;
            padding: 0 0.5rem 0.5rem;
        }

        .session-list::-webkit-scrollbar { width: 4px; }
        .session-list::-webkit-scrollbar-track { background: transparent; }
        .session-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

        .session-card {
            padding: 0.65rem 0.75rem;
            border-radius: var(--radius-sm);
            margin-bottom: 3px;
            cursor: pointer;
            border: 1px solid transparent;
            transition: all var(--transition);
            position: relative;
        }

        .session-card:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
        }

        .session-card.active {
            background: var(--bg-card);
            border-color: var(--gemini-blue);
            box-shadow: 0 0 16px rgba(74, 138, 244, 0.06);
        }

        .session-card .objective {
            font-size: 0.82rem;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 0.3rem;
            line-height: 1.3;
        }

        .session-card .meta {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            font-size: 0.68rem;
            color: var(--text-dim);
        }

        .status-pill {
            display: inline-flex;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 0.6rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .status-pill.completed { background: var(--success-bg); color: var(--success); }
        .status-pill.in_progress { background: var(--gemini-glow); color: var(--gemini-blue); }
        .status-pill.paused { background: var(--warning-bg); color: var(--warning); }
        .status-pill.error { background: var(--error-bg); color: var(--error); }
        .status-pill.started { background: var(--gemini-glow); color: var(--info); }

        .meta-sep { color: var(--border); }

        /* ── Main Panel ── */
        .main-panel {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* ── Phase Bar ── */
        .phase-bar {
            padding: 0.75rem 1.5rem;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 0;
            min-height: 52px;
        }

        .phase-node {
            display: flex;
            align-items: center;
            gap: 0;
        }

        .phase-circle {
            width: 30px; height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.72rem;
            font-weight: 700;
            border: 2px solid var(--border);
            color: var(--text-dim);
            background: var(--bg-primary);
            transition: all 0.4s ease;
            position: relative;
        }

        .phase-circle.done {
            background: var(--success);
            border-color: var(--success);
            color: #fff;
            box-shadow: 0 0 12px rgba(45, 212, 160, 0.2);
        }

        .phase-circle.active {
            background: var(--gemini-blue);
            border-color: var(--gemini-blue);
            color: #fff;
            box-shadow: 0 0 16px rgba(74, 138, 244, 0.3);
            animation: activePhase 2s ease-in-out infinite;
        }

        @keyframes activePhase {
            0%, 100% { box-shadow: 0 0 16px rgba(74, 138, 244, 0.3); }
            50% { box-shadow: 0 0 24px rgba(74, 138, 244, 0.5); }
        }

        .phase-line {
            width: 36px; height: 2px;
            background: var(--border);
            transition: background 0.4s ease;
        }

        .phase-line.done { background: var(--success); }

        .phase-label {
            font-size: 0.65rem;
            color: var(--text-dim);
            margin-left: 1rem;
            font-weight: 500;
        }

        .tasks-progress {
            margin-left: auto;
            font-size: 0.7rem;
            color: var(--text-dim);
            display: flex; align-items: center; gap: 0.5rem;
        }

        .tasks-bar {
            width: 80px; height: 4px;
            background: var(--border);
            border-radius: 2px;
            overflow: hidden;
        }

        .tasks-bar-fill {
            height: 100%;
            background: var(--gemini-blue);
            border-radius: 2px;
            transition: width 0.5s ease;
        }

        /* ── Timeline ── */
        .timeline {
            flex: 1;
            overflow-y: auto;
            padding: 1rem 1.5rem 2rem;
        }

        .timeline::-webkit-scrollbar { width: 5px; }
        .timeline::-webkit-scrollbar-track { background: transparent; }
        .timeline::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

        .log-entry {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1rem 1.25rem;
            margin-bottom: 0.6rem;
            animation: fadeSlideIn 0.3s ease;
            transition: border-color var(--transition);
        }

        .log-entry:hover { border-color: var(--border-hover); }

        @keyframes fadeSlideIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .log-entry.gemini {
            border-left: 3px solid var(--gemini-border);
            background: linear-gradient(135deg, var(--bg-card) 0%, var(--gemini-glow) 100%);
        }

        .log-entry.developer {
            border-left: 3px solid var(--dev-border);
            background: linear-gradient(135deg, var(--bg-card) 0%, var(--dev-glow) 100%);
        }

        .log-meta {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.4rem;
        }

        .badge {
            display: inline-flex;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 0.62rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        }

        .badge.pm { background: var(--gemini-blue); color: #fff; }
        .badge.dev { background: var(--dev-purple); color: #fff; }
        .badge.approved { background: var(--success); color: #fff; }
        .badge.changes { background: var(--warning); color: #111; }
        .badge.error-badge { background: var(--error); color: #fff; }

        .log-time {
            font-size: 0.68rem;
            color: var(--text-dim);
            font-family: 'JetBrains Mono', monospace;
        }

        .log-action {
            font-size: 0.68rem;
            color: var(--text-secondary);
            font-weight: 500;
        }

        .log-title {
            font-size: 0.92rem;
            font-weight: 600;
            margin-bottom: 0.4rem;
            line-height: 1.3;
        }

        .log-body {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            line-height: 1.65;
            color: var(--text-secondary);
            background: var(--bg-code);
            border-radius: var(--radius-sm);
            padding: 0.85rem 1rem;
            max-height: 350px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
            border: 1px solid var(--border);
        }

        .log-body::-webkit-scrollbar { width: 4px; }
        .log-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

        /* ── Empty State ── */
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-dim);
            text-align: center;
            gap: 0.75rem;
        }

        .empty-state .icon {
            font-size: 2.5rem;
            filter: grayscale(0.3);
        }

        .empty-state p {
            max-width: 280px;
            line-height: 1.6;
            font-size: 0.85rem;
        }

        .empty-state code {
            display: inline-block;
            margin-top: 0.5rem;
            padding: 0.3rem 0.6rem;
            border-radius: var(--radius-sm);
            background: var(--bg-card);
            color: var(--gemini-blue);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
        }

        /* ── New Session Button ── */
        .new-session-btn {
            margin: 0.5rem;
            padding: 0.6rem 1rem;
            background: linear-gradient(135deg, var(--gemini-blue) 0%, var(--dev-purple) 100%);
            color: #fff;
            border: none;
            border-radius: var(--radius-sm);
            font-family: 'Inter', sans-serif;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: all var(--transition);
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .new-session-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 16px rgba(74, 138, 244, 0.3);
        }

        /* ── Modal ── */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal-overlay.open { display: flex; }

        .modal {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            width: 520px;
            max-width: 90vw;
            padding: 1.5rem;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            animation: modalIn 0.2s ease;
        }

        @keyframes modalIn {
            from { opacity: 0; transform: scale(0.95) translateY(10px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }

        .modal h2 {
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 1rem;
            background: var(--gradient-header);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .modal textarea {
            width: 100%;
            min-height: 120px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            padding: 0.75rem;
            resize: vertical;
            outline: none;
            transition: border-color var(--transition);
        }

        .modal textarea:focus {
            border-color: var(--gemini-blue);
        }

        .modal textarea::placeholder {
            color: var(--text-dim);
        }

        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 0.5rem;
            margin-top: 1rem;
        }

        .modal-btn {
            padding: 0.5rem 1.2rem;
            border-radius: var(--radius-sm);
            font-family: 'Inter', sans-serif;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid var(--border);
            transition: all var(--transition);
        }

        .modal-btn.cancel {
            background: transparent;
            color: var(--text-secondary);
        }

        .modal-btn.cancel:hover {
            background: var(--bg-card);
        }

        .modal-btn.launch {
            background: linear-gradient(135deg, var(--gemini-blue) 0%, var(--dev-purple) 100%);
            color: #fff;
            border: none;
        }

        .modal-btn.launch:hover {
            box-shadow: 0 4px 16px rgba(74, 138, 244, 0.3);
        }

        .modal-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .modal-status {
            font-size: 0.75rem;
            margin-top: 0.5rem;
            color: var(--success);
            min-height: 1.2rem;
        }

        .modal-status.error { color: var(--error); }

        /* ── Session summary header ── */
        .session-header {
            padding: 0.75rem 1.5rem;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .session-header .title {
            font-size: 0.95rem;
            font-weight: 600;
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .session-header .detail {
            font-size: 0.72rem;
            color: var(--text-dim);
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <h1>🎼 Orchestra</h1>
        </div>
        <div class="header-right">
            <div class="live-dot"></div>
            <span>Live</span>
            <span id="lastUpdate" style="margin-left: 0.5rem;"></span>
        </div>
    </div>

    <div class="layout">
        <div class="sidebar">
            <button class="new-session-btn" onclick="openNewSession()">＋ New Session</button>
            <div class="sidebar-header">Sesiones</div>
            <div class="session-list" id="sessionList"></div>
        </div>

        <div class="main-panel" id="mainPanel">
            <div class="empty-state">
                <div class="icon">🎼</div>
                <p>Click <strong>＋ New Session</strong> or run:</p>
                <code>aid.bat "your goal"</code>
            </div>
        </div>
    </div>

    <!-- New Session Modal -->
    <div class="modal-overlay" id="newSessionModal">
        <div class="modal">
            <h2>🚀 New Session</h2>
            <textarea id="objectiveInput" placeholder="Describe what you want to build...
Example: Create a REST API with FastAPI, authentication, and unit tests.
Tip: Include the project path if it's not in the current workspace."></textarea>
            <div class="modal-status" id="launchStatus"></div>
            <div class="modal-actions">
                <button class="modal-btn cancel" onclick="closeNewSession()">Cancel</button>
                <button class="modal-btn launch" id="launchBtn" onclick="launchSession()">🚀 Launch</button>
            </div>
        </div>
    </div>

    <script>
        let currentSession = null;
        let lastContentHash = '';

        // ── API ──
        async function fetchSessions() {
            try {
                const r = await fetch('/api/sessions');
                return await r.json();
            } catch { return []; }
        }

        async function fetchSession(id) {
            try {
                const r = await fetch('/api/session/' + id);
                return await r.json();
            } catch { return null; }
        }

        // ── Helpers ──
        function esc(s) {
            return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        function statusClass(s) {
            if (!s) return '';
            const sl = s.toLowerCase();
            if (sl === 'completed') return 'completed';
            if (sl.includes('progress') || sl === 'started') return 'in_progress';
            if (sl.includes('error') || sl.includes('review_error')) return 'error';
            return 'paused';
        }

        function simpleHash(str) {
            let h = 0;
            for (let i = 0; i < str.length; i++) {
                h = ((h << 5) - h + str.charCodeAt(i)) | 0;
            }
            return h;
        }

        // ── Sidebar Render ──
        function renderSidebar(sessions) {
            const el = document.getElementById('sessionList');
            if (!sessions.length) {
                el.innerHTML = '<div style="padding:1rem;font-size:0.8rem;color:var(--text-dim)">Sin sesiones</div>';
                return;
            }

            el.innerHTML = sessions.map(s => {
                const sc = statusClass(s.status);
                const isActive = currentSession === s.session_id;
                return `<div class="session-card ${isActive ? 'active' : ''}"
                             onclick="selectSession('${s.session_id}')">
                    <div class="objective">${esc(s.objective || 'Sin objetivo')}</div>
                    <div class="meta">
                        <span class="status-pill ${sc}">${s.status || '?'}</span>
                        <span class="meta-sep">·</span>
                        <span>F${s.current_phase || 0}/${s.total_phases || 0}</span>
                        <span class="meta-sep">·</span>
                        <span>${(s.started_at || '').split(' ')[1] || ''}</span>
                    </div>
                </div>`;
            }).join('');
        }

        // ── Parse logs into timeline entries ──
        function parseLogEntries(rawLog, type) {
            if (!rawLog) return [];
            const entries = [];
            const sections = rawLog.split('---').filter(s => s.trim() && s.includes('##'));

            for (const section of sections) {
                const match = section.match(/##\s*\[(\d{2}:\d{2}:\d{2})\]\s*(.+)/);
                if (!match) continue;

                const time = match[1];
                const action = match[2].trim();
                const bodyStart = section.indexOf('\n', section.indexOf(match[0]));
                const body = bodyStart >= 0 ? section.substring(bodyStart).trim() : '';

                entries.push({ type, time, action, body });
            }
            return entries;
        }

        // ── Main Render ──
        async function renderMain(sessionId) {
            const panel = document.getElementById('mainPanel');
            const data = await fetchSession(sessionId);
            if (!data) return;

            const hash = simpleHash(JSON.stringify(data));
            if (hash === lastContentHash) return;
            lastContentHash = hash;

            const st = data.state || {};
            let html = '';

            // Session header
            html += `<div class="session-header">
                <span class="status-pill ${statusClass(st.status)}">${st.status || '?'}</span>
                <div class="title">${esc(st.objective || 'Sin objetivo')}</div>
                <div class="detail">${st.session_id || ''}</div>
            </div>`;

            // Phase bar
            const totalP = st.total_phases || 0;
            const curP = st.current_phase || 0;
            const done = st.phases_completed || [];
            const tasksCompleted = (st.tasks_completed || []).length;
            const totalTasks = (st.tasks || []).length;

            if (totalP > 0) {
                html += '<div class="phase-bar">';
                for (let i = 1; i <= totalP; i++) {
                    const isDone = done.includes(i);
                    const isActive = (i === curP) && !isDone;
                    html += `<div class="phase-node">
                        <div class="phase-circle ${isDone ? 'done' : isActive ? 'active' : ''}">${i}</div>
                        ${i < totalP ? `<div class="phase-line ${isDone ? 'done' : ''}"></div>` : ''}
                    </div>`;
                }
                if (totalTasks > 0) {
                    const pct = Math.round((tasksCompleted / totalTasks) * 100);
                    html += `<div class="tasks-progress">
                        <div class="tasks-bar"><div class="tasks-bar-fill" style="width:${pct}%"></div></div>
                        <span>${tasksCompleted}/${totalTasks} tareas</span>
                    </div>`;
                }
                html += '</div>';
            }

            // Timeline — merge PM + Dev entries chronologically
            const pmEntries = parseLogEntries(data.gemini_log, 'gemini');
            const devEntries = parseLogEntries(data.developer_log, 'developer');
            const all = [...pmEntries, ...devEntries].sort((a, b) => a.time.localeCompare(b.time));

            if (all.length > 0) {
                html += '<div class="timeline" id="timelineScroll">';
                for (const e of all) {
                    const badgeClass = e.type === 'gemini' ? 'pm' : 'dev';
                    const badgeLabel = e.type === 'gemini' ? 'PM' : 'Dev';

                    // Special badges for certain actions
                    let extraBadge = '';
                    const actionLower = e.action.toLowerCase();
                    if (actionLower.includes('aprobad') || actionLower.includes('approved')) {
                        extraBadge = '<span class="badge approved">✓</span>';
                    } else if (actionLower.includes('changes') || actionLower.includes('cambios')) {
                        extraBadge = '<span class="badge changes">⚠</span>';
                    } else if (actionLower.includes('error')) {
                        extraBadge = '<span class="badge error-badge">✗</span>';
                    }

                    // Truncate body for display
                    const bodyText = e.body.length > 3000 ? e.body.substring(0, 3000) + '\n... (truncado)' : e.body;

                    html += `<div class="log-entry ${e.type}">
                        <div class="log-meta">
                            <span class="badge ${badgeClass}">${badgeLabel}</span>
                            ${extraBadge}
                            <span class="log-time">${e.time}</span>
                            <span class="log-action">${esc(e.action)}</span>
                        </div>
                        ${bodyText ? `<div class="log-body">${esc(bodyText)}</div>` : ''}
                    </div>`;
                }
                html += '</div>';
            } else {
                html += `<div class="empty-state">
                    <div class="icon">⏳</div>
                    <p>Esperando actividad...</p>
                </div>`;
            }

            panel.innerHTML = html;

            // Auto-scroll to bottom
            const tl = document.getElementById('timelineScroll');
            if (tl) tl.scrollTop = tl.scrollHeight;
        }

        // ── Selection ──
        function selectSession(id) {
            currentSession = id;
            lastContentHash = '';
            refresh();
        }

        // ── New Session Modal ──
        function openNewSession() {
            document.getElementById('newSessionModal').classList.add('open');
            document.getElementById('objectiveInput').focus();
            document.getElementById('launchStatus').textContent = '';
        }

        function closeNewSession() {
            document.getElementById('newSessionModal').classList.remove('open');
            document.getElementById('objectiveInput').value = '';
            document.getElementById('launchStatus').textContent = '';
        }

        async function launchSession() {
            const input = document.getElementById('objectiveInput');
            const btn = document.getElementById('launchBtn');
            const status = document.getElementById('launchStatus');
            const objective = input.value.trim();

            if (!objective) {
                status.textContent = 'Write an objective first.';
                status.className = 'modal-status error';
                return;
            }

            btn.disabled = true;
            btn.textContent = 'Launching...';
            status.textContent = '';

            try {
                const r = await fetch('/api/launch', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({objective}),
                });
                const data = await r.json();

                if (data.ok) {
                    status.textContent = '✅ Session launched! Refreshing...';
                    status.className = 'modal-status';
                    setTimeout(() => {
                        closeNewSession();
                        refresh();
                    }, 1500);
                } else {
                    status.textContent = '❌ ' + (data.error || 'Launch failed');
                    status.className = 'modal-status error';
                }
            } catch (e) {
                status.textContent = '❌ Connection error';
                status.className = 'modal-status error';
            } finally {
                btn.disabled = false;
                btn.textContent = '🚀 Launch';
            }
        }

        // Close modal on Escape
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') closeNewSession();
        });

        // Launch on Ctrl+Enter in textarea
        document.getElementById('objectiveInput').addEventListener('keydown', e => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) launchSession();
        });

        // ── Refresh loop ──
        async function refresh() {
            const sessions = await fetchSessions();
            renderSidebar(sessions);

            if (!currentSession && sessions.length > 0) {
                currentSession = sessions[sessions.length - 1].session_id;
            }

            if (currentSession) {
                await renderMain(currentSession);
            }

            document.getElementById('lastUpdate').textContent =
                new Date().toLocaleTimeString('es-ES');
        }

        setInterval(refresh, 3000);
        refresh();
    </script>
</body>
</html>"""


# ─────────────────────────────────────────────
# HTTP Server
# ─────────────────────────────────────────────

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for the dashboard SPA and API endpoints."""

    def log_message(self, format, *args):
        pass  # Suppress default HTTP access logs

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/sessions":
            self._serve_sessions()
        elif self.path.startswith("/api/session/"):
            session_id = self.path.split("/api/session/", 1)[1]
            if all(c.isalnum() or c in ('_', '-') for c in session_id):
                self._serve_session(session_id)
            else:
                self._send_json({"error": "Invalid session ID"}, 400)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/launch":
            self._handle_launch()
        else:
            self.send_error(404)

    def _handle_launch(self):
        """POST /api/launch — Launch a new orchestrator session in background."""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            objective = body.get('objective', '').strip()

            if not objective:
                self._send_json({'ok': False, 'error': 'No objective provided'}, 400)
                return

            # Launch orchestrator.py as a detached subprocess
            orchestrator_path = Path(__file__).parent / 'orchestrator.py'
            subprocess.Popen(
                [sys.executable, str(orchestrator_path), objective],
                cwd=str(Path(__file__).parent),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self._send_json({'ok': True, 'message': f'Session launched for: {objective[:100]}'})

        except Exception as e:
            self._send_json({'ok': False, 'error': str(e)}, 500)

    def _serve_html(self):
        """Serve the SPA HTML page."""
        content = HTML_TEMPLATE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_sessions(self):
        """GET /api/sessions — list all sessions with state summary."""
        sessions = []
        if SESSIONS_DIR.exists():
            for d in sorted(SESSIONS_DIR.iterdir()):
                if not d.is_dir():
                    continue
                state_file = d / "state.json"
                if state_file.exists():
                    try:
                        with open(state_file, "r", encoding="utf-8") as f:
                            state = json.load(f)
                        # Return only summary fields for the list
                        sessions.append({
                            "session_id": state.get("session_id", d.name),
                            "objective": state.get("objective", ""),
                            "status": state.get("status", "UNKNOWN"),
                            "current_phase": state.get("current_phase", 0),
                            "total_phases": state.get("total_phases", 0),
                            "started_at": state.get("started_at", ""),
                            "last_update": state.get("last_update", ""),
                        })
                    except (json.JSONDecodeError, OSError):
                        # Skip corrupt state files
                        sessions.append({
                            "session_id": d.name,
                            "objective": "(state.json corrupto)",
                            "status": "ERROR",
                            "current_phase": 0,
                            "total_phases": 0,
                            "started_at": "",
                            "last_update": "",
                        })

        self._send_json(sessions)

    def _serve_session(self, session_id: str):
        """GET /api/session/{id} — full session data with logs."""
        session_dir = SESSIONS_DIR / session_id
        if not session_dir.exists():
            self._send_json({"error": "Session not found"}, 404)
            return

        data = {}

        # State
        state_file = session_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data["state"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                data["state"] = {"status": "ERROR", "error": "Corrupted state.json"}

        # PM log
        gemini_log = session_dir / "gemini_pm.md"
        if gemini_log.exists():
            try:
                data["gemini_log"] = gemini_log.read_text(encoding="utf-8")
            except OSError:
                data["gemini_log"] = ""

        # Dev log
        dev_log = session_dir / "developer.md"
        if dev_log.exists():
            try:
                data["developer_log"] = dev_log.read_text(encoding="utf-8")
            except OSError:
                data["developer_log"] = ""

        self._send_json(data)

    def _send_json(self, data, status: int = 200):
        """Send a JSON response with proper headers."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Bind to localhost ONLY (security)
    server = http.server.HTTPServer(("127.0.0.1", DASHBOARD_PORT), DashboardHandler)
    print(f"\n  Orchestra Dashboard")
    print(f"  -------------------")
    print(f"  URL:      http://localhost:{DASHBOARD_PORT}")
    print(f"  Sesiones: {SESSIONS_DIR}")
    print(f"  Ctrl+C para detener\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard detenido")


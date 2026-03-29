#!/usr/bin/env python3
"""
nb2report.py — Convert any Jupyter Notebook (.ipynb) into a premium interactive HTML report.

Usage:
    python nb2report.py notebook.ipynb                     # → notebook_report.html
    python nb2report.py notebook.ipynb -o my_report.html   # → my_report.html
    python nb2report.py notebook.ipynb --title "My Study"  # custom title
    python nb2report.py notebook.ipynb --author "Jane Doe" # custom author
    python nb2report.py notebook.ipynb --hide-all-code     # hide all code by default
    python nb2report.py notebook.ipynb --show-all-code     # show all code by default

Cell-level control (in notebook):
    - Add a cell tag "hide"    → code is hidden (collapsed) by default
    - Add a cell tag "show"    → code is visible by default
    - Add a cell tag "remove"  → cell is completely excluded from report
    - Start a code cell with `# HIDE` → same as tag "hide"
    - Start a code cell with `# REMOVE` → same as tag "remove"
    - Markdown cells become prose sections automatically
    - Markdown cells starting with `# ` become new named sections in the sidebar
"""

import json
import sys
import os
import re
import html as html_lib
import argparse
import base64
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# NOTEBOOK PARSER
# ─────────────────────────────────────────────────────────────

def parse_notebook(path: str) -> dict:
    """Parse a .ipynb file and return structured data."""
    with open(path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    kernel = nb.get("metadata", {}).get("kernelspec", {})
    lang_info = nb.get("metadata", {}).get("language_info", {})
    language = lang_info.get("name", kernel.get("language", "python"))
    py_version = lang_info.get("version", "")

    sections = []
    figure_counter = 0
    code_counter = 0
    current_section = {
        "id": "section-intro",
        "title": "Introduction",
        "blocks": [],
    }

    for cell in nb.get("cells", []):
        cell_type = cell.get("cell_type", "")
        source = "".join(cell.get("source", []))
        tags = cell.get("metadata", {}).get("tags", [])

        # Check for removal
        if "remove" in tags or source.strip().startswith("# REMOVE"):
            continue

        # ── MARKDOWN ──
        if cell_type == "markdown":
            # Skip empty cells or cells that are just `$$$$`
            stripped = source.strip()
            if not stripped or stripped == "$$$$":
                continue

            # Check if this starts a NEW section (has a # heading)
            heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped, re.MULTILINE)
            if heading_match:
                # Save current section if it has blocks
                if current_section["blocks"]:
                    sections.append(current_section)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                section_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                current_section = {
                    "id": f"section-{section_id}",
                    "title": title,
                    "blocks": [],
                }
                # Remove the heading from the source, keep the rest
                remaining = stripped[heading_match.end():].strip()
                if remaining:
                    current_section["blocks"].append({
                        "type": "markdown",
                        "content": remaining,
                    })
            else:
                current_section["blocks"].append({
                    "type": "markdown",
                    "content": stripped,
                })

        # ── CODE ──
        elif cell_type == "code":
            if not source.strip():
                continue

            code_counter += 1
            hide = "hide" in tags or source.strip().startswith("# HIDE")
            show_flag = "show" in tags

            # Extract outputs
            outputs_data = []
            for out in cell.get("outputs", []):
                out_type = out.get("output_type", "")

                # Images
                if "data" in out:
                    for mime in ["image/png", "image/jpeg", "image/svg+xml"]:
                        if mime in out["data"]:
                            figure_counter += 1
                            img_data = out["data"][mime]
                            if isinstance(img_data, list):
                                img_data = "".join(img_data)
                            outputs_data.append({
                                "kind": "image",
                                "mime": mime,
                                "data": img_data.strip(),
                                "figure_num": figure_counter,
                            })
                            break
                    # HTML output
                    if "text/html" in out["data"] and not any(
                        o["kind"] == "image" for o in outputs_data
                    ):
                        html_content = out["data"]["text/html"]
                        if isinstance(html_content, list):
                            html_content = "".join(html_content)
                        outputs_data.append({
                            "kind": "html",
                            "data": html_content,
                        })

                # Text / stdout
                if out_type == "stream" and "text" in out:
                    text = "".join(out["text"]) if isinstance(out["text"], list) else out["text"]
                    outputs_data.append({
                        "kind": "text",
                        "data": text,
                    })

                # execute_result text
                if out_type == "execute_result" and "data" in out and "text/plain" in out["data"]:
                    text = out["data"]["text/plain"]
                    if isinstance(text, list):
                        text = "".join(text)
                    # Skip if it's just a figure repr
                    if "<Figure" not in text:
                        outputs_data.append({
                            "kind": "text",
                            "data": text,
                        })

                # Error output
                if out_type == "error":
                    tb = out.get("traceback", [])
                    # Strip ANSI codes
                    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
                    text = "\n".join(ansi_escape.sub("", line) for line in tb)
                    outputs_data.append({
                        "kind": "error",
                        "data": text,
                    })

            current_section["blocks"].append({
                "type": "code",
                "source": source,
                "language": language,
                "hidden": hide and not show_flag,
                "code_num": code_counter,
                "outputs": outputs_data,
            })

    # Don't forget the last section
    if current_section["blocks"]:
        sections.append(current_section)

    return {
        "language": language,
        "py_version": py_version,
        "kernel": kernel.get("display_name", "Python 3"),
        "sections": sections,
        "total_figures": figure_counter,
        "total_code_cells": code_counter,
    }


# ─────────────────────────────────────────────────────────────
# MARKDOWN → HTML (lightweight, no external deps)
# ─────────────────────────────────────────────────────────────

def md_to_html(md_text: str) -> str:
    """Convert markdown to HTML — handles common patterns.
    LaTeX is left as-is for KaTeX client-side rendering.
    """
    lines = md_text.split("\n")
    html_parts = []
    in_list = False
    in_block = False

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("")
            continue

        # Display math block ($$...$$) — leave as-is
        if stripped.startswith("$$"):
            html_parts.append(f'<div class="math-block">{stripped}</div>' if stripped.endswith("$$") and len(stripped) > 4 else stripped)
            continue

        # Headings (within a section, these become sub-headings)
        hm = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if hm:
            level = min(len(hm.group(1)) + 1, 6)  # bump down since section already has h2
            html_parts.append(f"<h{level}>{inline_md(hm.group(2))}</h{level}>")
            continue

        # Unordered list
        if re.match(r"^[-*+]\s+", stripped):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            content = re.sub(r"^[-*+]\s+", "", stripped)
            html_parts.append(f"<li>{inline_md(content)}</li>")
            continue

        # Blockquote
        if stripped.startswith(">"):
            content = stripped.lstrip("> ").strip()
            html_parts.append(f'<blockquote class="callout insight"><div class="callout-title">◈ Note</div><p>{inline_md(content)}</p></blockquote>')
            continue

        # Regular paragraph
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        html_parts.append(f"<p>{inline_md(stripped)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def inline_md(text: str) -> str:
    """Convert inline markdown: bold, italic, code, links."""
    # Don't touch LaTeX delimiters
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Links
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" target="_blank">\1</a>', text)
    return text


# ─────────────────────────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────────────────────────

def build_html(nb_data: dict, title: str, author: str, hide_all: bool, show_all: bool, source_file: str) -> str:
    """Assemble the final HTML report."""

    # Build sidebar nav items
    nav_items_html = ""
    icons = ["◈", "◆", "◉", "▣", "◇", "★", "⊡", "⊞", "⊕", "⊗", "△", "▽", "☉", "♦", "♠", "♣"]
    for i, sec in enumerate(nb_data["sections"]):
        icon = icons[i % len(icons)]
        active = ' active' if i == 0 else ''
        nav_items_html += f'''
    <a href="#{sec['id']}" class="nav-item{active}" data-section="{sec['id']}">
      <span class="nav-icon">{icon}</span> {html_lib.escape(sec['title'])}
    </a>'''

    # Build content sections
    sections_html = ""
    for idx, sec in enumerate(nb_data["sections"]):
        blocks_html = ""
        for block in sec["blocks"]:
            if block["type"] == "markdown":
                blocks_html += f'<div class="prose">{md_to_html(block["content"])}</div>\n'
            elif block["type"] == "code":
                blocks_html += render_code_block(block, hide_all, show_all)

        sections_html += f'''
      <section class="section" id="{sec['id']}">
        <div class="section-label">Section {_roman(idx + 1)}</div>
        <h2>{html_lib.escape(sec['title'])}</h2>
        {blocks_html}
      </section>'''

    now = datetime.now().strftime("%d %b %Y")
    lang = nb_data["language"].title()
    kernel = nb_data["kernel"]
    n_figs = nb_data["total_figures"]
    n_code = nb_data["total_code_cells"]

    return TEMPLATE.format(
        title=html_lib.escape(title),
        author=html_lib.escape(author),
        date=now,
        language=lang,
        kernel=html_lib.escape(kernel),
        nav_items=nav_items_html,
        sections=sections_html,
        source_file=html_lib.escape(source_file),
        n_figures=n_figs,
        n_code_cells=n_code,
        py_version=nb_data["py_version"] or "",
    )


def render_code_block(block: dict, hide_all: bool, show_all: bool) -> str:
    """Render a single code block with optional outputs."""
    source_escaped = html_lib.escape(block["source"])
    lang = block["language"]
    code_id = f"code-{block['code_num']}"

    # Determine visibility
    if show_all:
        hidden = False
    elif hide_all:
        hidden = True
    else:
        hidden = block["hidden"]

    collapsed_class = " collapsed" if hidden else ""
    btn_label = "Show" if hidden else "Hide"

    code_html = f'''
        <div class="code-block-wrapper">
          <div class="code-header">
            <div class="code-header-left">
              <div class="code-dots"><span></span><span></span><span></span></div>
              <span class="code-lang">{html_lib.escape(lang)} · Cell {block['code_num']}</span>
            </div>
            <div class="code-actions">
              <button class="code-btn" onclick="toggleCode(this)" data-target="{code_id}">{btn_label}</button>
              <button class="code-btn" onclick="copyCode('{code_id}', this)">Copy</button>
            </div>
          </div>
          <div class="code-body{collapsed_class}" id="{code_id}" style="max-height:600px">
            <pre><code class="language-{lang}">{source_escaped}</code></pre>
          </div>
        </div>'''

    # Render outputs
    for out in block.get("outputs", []):
        if out["kind"] == "image":
            mime = out["mime"]
            if mime == "image/svg+xml":
                code_html += f'''
        <div class="figure-wrapper">
          <div class="figure-toolbar">
            <div class="figure-toolbar-left">
              <span class="figure-tag">Output</span>
              <span class="figure-number">Figure {out['figure_num']}</span>
            </div>
            <div class="figure-actions">
              <button class="fig-btn" title="Zoom" onclick="openLightbox(this.closest('.figure-wrapper').querySelector('img'))">⤢</button>
            </div>
          </div>
          <div class="figure-image-container">
            <div class="svg-output">{out['data']}</div>
          </div>
          <div class="figure-caption"><p><strong>Figure {out['figure_num']}.</strong> Generated output.</p></div>
        </div>'''
            else:
                code_html += f'''
        <div class="figure-wrapper">
          <div class="figure-toolbar">
            <div class="figure-toolbar-left">
              <span class="figure-tag">Output</span>
              <span class="figure-number">Figure {out['figure_num']}</span>
            </div>
            <div class="figure-actions">
              <button class="fig-btn" title="Zoom" onclick="openLightbox(this.closest('.figure-wrapper').querySelector('img'))">⤢</button>
            </div>
          </div>
          <div class="figure-image-container">
            <img src="data:{mime};base64,{out['data']}" alt="Figure {out['figure_num']}" onclick="openLightbox(this)">
          </div>
          <div class="figure-caption"><p><strong>Figure {out['figure_num']}.</strong> Generated output.</p></div>
        </div>'''

        elif out["kind"] == "html":
            code_html += f'''
        <div class="output-html-wrapper">{out['data']}</div>'''

        elif out["kind"] == "text":
            text_escaped = html_lib.escape(out["data"])
            code_html += f'''
        <div class="code-block-wrapper output-text">
          <div class="code-header">
            <div class="code-header-left">
              <div class="code-dots"><span></span><span></span><span></span></div>
              <span class="code-lang">Output</span>
            </div>
          </div>
          <div class="code-body" style="max-height:400px">
            <pre><code class="language-text">{text_escaped}</code></pre>
          </div>
        </div>'''

        elif out["kind"] == "error":
            text_escaped = html_lib.escape(out["data"])
            code_html += f'''
        <div class="code-block-wrapper output-error">
          <div class="code-header" style="border-bottom-color: rgba(201,112,112,0.3);">
            <div class="code-header-left">
              <div class="code-dots"><span></span><span></span><span></span></div>
              <span class="code-lang" style="color:#c97070">Error</span>
            </div>
          </div>
          <div class="code-body" style="max-height:400px">
            <pre><code class="language-text">{text_escaped}</code></pre>
          </div>
        </div>'''

    return code_html


def _roman(num: int) -> str:
    """Convert integer to Roman numeral."""
    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),
            (50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    result = ''
    for v, r in vals:
        while num >= v:
            result += r
            num -= v
    return result


# ─────────────────────────────────────────────────────────────
# FULL HTML TEMPLATE
# ─────────────────────────────────────────────────────────────

TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;0,800;1,400;1,600&family=Source+Code+Pro:wght@400;500;600&family=Crimson+Pro:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400;1,500&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"></script>

<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" id="hljs-theme">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/r.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/julia.min.js"></script>

<style>
:root {{
  --bg-primary: #0c0e12;
  --bg-secondary: #12151c;
  --bg-card: #181c26;
  --bg-card-hover: #1e2230;
  --bg-code: #0d1117;
  --bg-sidebar: #0a0c10;
  --text-primary: #e8eaf0;
  --text-secondary: #9ca3b8;
  --text-muted: #5f6780;
  --text-accent: #c9a96e;
  --text-link: #7eb8da;
  --border-primary: rgba(255,255,255,0.06);
  --border-accent: rgba(201,169,110,0.3);
  --accent-gold: #c9a96e;
  --accent-gold-dim: rgba(201,169,110,0.15);
  --accent-blue: #5b8fb9;
  --accent-blue-dim: rgba(91,143,185,0.12);
  --accent-teal: #5ba899;
  --accent-red: #c97070;
  --gradient-hero: linear-gradient(165deg, #0c0e12 0%, #141824 40%, #1a1520 100%);
  --gradient-card: linear-gradient(135deg, var(--bg-card) 0%, #1a1f2e 100%);
  --gradient-gold: linear-gradient(135deg, #c9a96e, #e8d5a8);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.5);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 40px rgba(201,169,110,0.08);
  --radius-sm: 6px;
  --radius-md: 12px;
  --radius-lg: 20px;
  --font-display: 'Playfair Display', Georgia, serif;
  --font-body: 'Crimson Pro', Georgia, serif;
  --font-ui: 'DM Sans', -apple-system, sans-serif;
  --font-mono: 'Source Code Pro', 'Fira Code', monospace;
  --sidebar-width: 280px;
  --content-max: 820px;
  --reading-progress: 0%;
}}
:root.light {{
  --bg-primary: #f8f6f1;
  --bg-secondary: #f0ede6;
  --bg-card: #ffffff;
  --bg-card-hover: #fafaf8;
  --bg-code: #1e1e2e;
  --bg-sidebar: #f2efe8;
  --text-primary: #1a1a2e;
  --text-secondary: #555566;
  --text-muted: #999aaa;
  --text-accent: #8b6914;
  --text-link: #2e6999;
  --border-primary: rgba(0,0,0,0.08);
  --border-accent: rgba(139,105,20,0.25);
  --accent-gold: #9b7b2a;
  --accent-gold-dim: rgba(155,123,42,0.1);
  --accent-blue: #3a7ca5;
  --accent-blue-dim: rgba(58,124,165,0.08);
  --gradient-hero: linear-gradient(165deg, #f8f6f1 0%, #ede8dd 40%, #f5f0e8 100%);
  --gradient-card: linear-gradient(135deg, #ffffff 0%, #faf8f4 100%);
  --gradient-gold: linear-gradient(135deg, #9b7b2a, #c9a96e);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.08);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.1);
  --shadow-glow: 0 0 40px rgba(155,123,42,0.06);
}}
*, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ scroll-behavior:smooth; font-size:17px; scrollbar-width:thin; scrollbar-color:var(--text-muted) transparent; }}
body {{ background:var(--bg-primary); color:var(--text-primary); font-family:var(--font-body); line-height:1.75; -webkit-font-smoothing:antialiased; overflow-x:hidden; }}

#reading-progress {{
  position:fixed; top:0; left:0; height:3px; width:var(--reading-progress);
  background:var(--gradient-gold); z-index:10000; transition:width .15s ease-out;
  box-shadow: 0 0 12px rgba(201,169,110,0.4);
}}
#sidebar {{
  position:fixed; top:0; left:0; width:var(--sidebar-width); height:100vh;
  background:var(--bg-sidebar); border-right:1px solid var(--border-primary);
  z-index:1000; display:flex; flex-direction:column;
  transition: transform .4s cubic-bezier(.22,1,.36,1);
}}
#sidebar.collapsed {{ transform:translateX(calc(-1 * var(--sidebar-width))); }}
.sidebar-header {{ padding:32px 24px 24px; border-bottom:1px solid var(--border-primary); }}
.sidebar-logo {{
  font-family:var(--font-display); font-size:1.1rem; font-weight:700;
  color:var(--text-accent); letter-spacing:.02em; display:flex; align-items:center; gap:10px;
}}
.sidebar-logo .logo-icon {{
  width:28px; height:28px; border-radius:6px; background:var(--gradient-gold);
  display:flex; align-items:center; justify-content:center; font-size:.75rem;
  color:#0c0e12; font-weight:800;
}}
.sidebar-meta {{
  margin-top:12px; font-family:var(--font-ui); font-size:.7rem; color:var(--text-muted);
  text-transform:uppercase; letter-spacing:.12em;
}}
.sidebar-nav {{ flex:1; overflow-y:auto; padding:20px 0; }}
.sidebar-nav::-webkit-scrollbar {{ width:3px; }}
.sidebar-nav::-webkit-scrollbar-thumb {{ background:var(--text-muted); border-radius:10px; }}
.nav-section-label {{
  font-family:var(--font-ui); font-size:.6rem; text-transform:uppercase;
  letter-spacing:.18em; color:var(--text-muted); padding:16px 24px 8px; font-weight:600;
}}
.nav-item {{
  display:flex; align-items:center; gap:10px; padding:9px 24px;
  font-family:var(--font-ui); font-size:.78rem; color:var(--text-secondary);
  cursor:pointer; transition:all .2s ease; text-decoration:none; position:relative;
}}
.nav-item::before {{
  content:''; position:absolute; left:0; top:50%; transform:translateY(-50%);
  width:3px; height:0; background:var(--accent-gold); border-radius:0 4px 4px 0;
  transition:height .25s ease;
}}
.nav-item:hover, .nav-item.active {{
  color:var(--text-primary); background:var(--accent-gold-dim);
}}
.nav-item.active::before {{ height:20px; }}
.nav-item .nav-icon {{
  width:18px; height:18px; border-radius:4px; display:flex;
  align-items:center; justify-content:center; font-size:.6rem; flex-shrink:0;
}}
.sidebar-footer {{
  padding:16px 24px; border-top:1px solid var(--border-primary); display:flex; gap:8px;
}}
.sidebar-btn {{
  flex:1; padding:8px; border:1px solid var(--border-primary); border-radius:var(--radius-sm);
  background:transparent; color:var(--text-secondary); font-family:var(--font-ui);
  font-size:.7rem; cursor:pointer; transition:all .2s; display:flex;
  align-items:center; justify-content:center; gap:5px;
}}
.sidebar-btn:hover {{
  background:var(--accent-gold-dim); color:var(--text-accent); border-color:var(--border-accent);
}}
#sidebar-toggle {{
  position:fixed; top:16px; left:16px; z-index:1001; width:40px; height:40px;
  border-radius:var(--radius-sm); background:var(--bg-card); border:1px solid var(--border-primary);
  color:var(--text-secondary); cursor:pointer; display:none; align-items:center;
  justify-content:center; font-size:1.1rem; transition:all .2s; box-shadow:var(--shadow-sm);
}}
#sidebar-toggle:hover {{ color:var(--text-accent); border-color:var(--border-accent); }}
#main {{
  margin-left:var(--sidebar-width); min-height:100vh;
  transition:margin-left .4s cubic-bezier(.22,1,.36,1);
}}
#sidebar.collapsed ~ #main {{ margin-left:0; }}
.hero {{
  background:var(--gradient-hero); padding:100px 60px 80px; position:relative; overflow:hidden;
}}
.hero::before {{
  content:''; position:absolute; top:-50%; right:-20%; width:600px; height:600px;
  background:radial-gradient(circle, rgba(201,169,110,0.06) 0%, transparent 70%); pointer-events:none;
}}
.hero::after {{
  content:''; position:absolute; bottom:0; left:0; right:0; height:1px;
  background:linear-gradient(90deg, transparent, var(--border-accent), transparent);
}}
.hero-inner {{ max-width:var(--content-max); margin:0 auto; position:relative; }}
.hero-badge {{
  display:inline-flex; align-items:center; gap:8px; padding:6px 16px; border-radius:100px;
  background:var(--accent-gold-dim); border:1px solid var(--border-accent);
  font-family:var(--font-ui); font-size:.68rem; font-weight:600; color:var(--text-accent);
  letter-spacing:.06em; text-transform:uppercase; margin-bottom:28px;
  animation:fadeInUp .8s ease both;
}}
.hero-badge .pulse {{
  width:6px; height:6px; border-radius:50%; background:var(--accent-gold);
  animation:pulse 2s ease-in-out infinite;
}}
.hero h1 {{
  font-family:var(--font-display); font-size:clamp(2.2rem,4vw,3.2rem); font-weight:700;
  line-height:1.15; color:var(--text-primary); margin-bottom:20px; animation:fadeInUp .8s ease .1s both;
}}
.hero h1 em {{
  font-style:italic; background:var(--gradient-gold); -webkit-background-clip:text;
  -webkit-text-fill-color:transparent; background-clip:text;
}}
.hero-subtitle {{
  font-family:var(--font-body); font-size:1.15rem; color:var(--text-secondary);
  max-width:580px; line-height:1.7; animation:fadeInUp .8s ease .2s both;
}}
.hero-meta {{
  display:flex; align-items:center; gap:24px; margin-top:36px; padding-top:28px;
  border-top:1px solid var(--border-primary); animation:fadeInUp .8s ease .3s both; flex-wrap:wrap;
}}
.meta-item {{
  display:flex; align-items:center; gap:8px; font-family:var(--font-ui);
  font-size:.75rem; color:var(--text-muted);
}}
.meta-item .meta-icon {{ font-size:.85rem; }}
.meta-item strong {{ color:var(--text-secondary); font-weight:500; }}
.content-area {{ padding:0 60px 100px; }}
.content-inner {{ max-width:var(--content-max); margin:0 auto; }}
.section {{
  padding-top:64px; opacity:0; transform:translateY(30px);
  transition:all .7s cubic-bezier(.22,1,.36,1);
}}
.section.visible {{ opacity:1; transform:translateY(0); }}
.section-label {{
  font-family:var(--font-ui); font-size:.62rem; text-transform:uppercase;
  letter-spacing:.2em; color:var(--text-accent); font-weight:700; margin-bottom:12px;
  display:flex; align-items:center; gap:10px;
}}
.section-label::after {{ content:''; flex:1; height:1px; background:var(--border-accent); }}
.section h2 {{
  font-family:var(--font-display); font-size:1.8rem; font-weight:700;
  color:var(--text-primary); margin-bottom:24px; line-height:1.25;
}}
.section h3 {{
  font-family:var(--font-display); font-size:1.3rem; font-weight:600;
  color:var(--text-primary); margin:28px 0 16px; line-height:1.3;
}}
.section h4 {{
  font-family:var(--font-ui); font-size:1rem; font-weight:600;
  color:var(--text-primary); margin:20px 0 12px;
}}
.section p, .section .prose p {{
  font-family:var(--font-body); font-size:1.05rem; color:var(--text-secondary);
  line-height:1.85; margin-bottom:20px;
}}
.section p strong, .section .prose p strong {{ color:var(--text-primary); font-weight:600; }}
.section p a, .section .prose p a {{ color:var(--text-link); text-decoration:underline; text-underline-offset:3px; }}
.section ul {{
  margin:12px 0 20px 24px; font-family:var(--font-body); font-size:1.02rem;
  color:var(--text-secondary); line-height:1.85;
}}
.section ul li {{ margin-bottom:6px; }}
.section ul li code, .section p code {{
  font-family:var(--font-mono); font-size:.88em; padding:2px 6px;
  background:var(--accent-blue-dim); border-radius:4px; color:var(--accent-blue);
}}
.callout {{
  padding:24px 28px; border-radius:var(--radius-md); margin:28px 0; position:relative; overflow:hidden;
}}
.callout::before {{
  content:''; position:absolute; left:0; top:0; bottom:0; width:4px;
}}
.callout.insight {{
  background:var(--accent-gold-dim); border:1px solid var(--border-accent);
}}
.callout.insight::before {{ background:var(--accent-gold); }}
.callout-title {{
  font-family:var(--font-ui); font-size:.72rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.1em; margin-bottom:8px; display:flex; align-items:center; gap:6px;
}}
.callout.insight .callout-title {{ color:var(--text-accent); }}
.callout p {{ margin-bottom:0 !important; font-size:.92rem !important; }}

.code-block-wrapper {{
  margin:32px 0; border-radius:var(--radius-md); overflow:hidden;
  border:1px solid var(--border-primary); box-shadow:var(--shadow-md); transition:all .3s ease;
}}
.code-block-wrapper:hover {{ box-shadow:var(--shadow-lg); }}
.code-header {{
  display:flex; align-items:center; justify-content:space-between;
  padding:10px 18px; background:#161b22; border-bottom:1px solid rgba(255,255,255,0.06);
}}
.code-header-left {{ display:flex; align-items:center; gap:10px; }}
.code-dots {{ display:flex; gap:6px; }}
.code-dots span {{ width:10px; height:10px; border-radius:50%; }}
.code-dots span:nth-child(1) {{ background:#ff5f57; }}
.code-dots span:nth-child(2) {{ background:#febc2e; }}
.code-dots span:nth-child(3) {{ background:#28c840; }}
.code-lang {{
  font-family:var(--font-mono); font-size:.65rem; color:#8b949e;
  text-transform:uppercase; letter-spacing:.1em;
}}
.code-actions {{ display:flex; gap:4px; }}
.code-btn {{
  padding:4px 10px; border:1px solid rgba(255,255,255,0.08); border-radius:4px;
  background:transparent; color:#8b949e; font-family:var(--font-mono);
  font-size:.62rem; cursor:pointer; transition:all .2s;
}}
.code-btn:hover {{ background:rgba(255,255,255,0.06); color:#e6edf3; }}
.code-btn.copied {{ color:#3fb950; border-color:rgba(63,185,80,0.3); }}
.code-body {{
  background:var(--bg-code); overflow:hidden;
  transition:max-height .5s cubic-bezier(.22,1,.36,1), opacity .3s ease;
}}
.code-body.collapsed {{ max-height:0 !important; opacity:0; }}
.code-body pre {{ margin:0; padding:20px; overflow-x:auto; }}
.code-body code {{ font-family:var(--font-mono); font-size:.82rem; line-height:1.7; }}

.figure-wrapper {{
  margin:40px 0; border-radius:var(--radius-lg); overflow:hidden;
  background:var(--gradient-card); border:1px solid var(--border-primary);
  box-shadow:var(--shadow-lg); transition:all .3s ease;
}}
.figure-wrapper:hover {{ box-shadow:var(--shadow-glow), var(--shadow-lg); transform:translateY(-2px); }}
.figure-toolbar {{
  display:flex; align-items:center; justify-content:space-between; padding:14px 24px;
  border-bottom:1px solid var(--border-primary);
}}
.figure-toolbar-left {{ display:flex; align-items:center; gap:10px; }}
.figure-tag {{
  font-family:var(--font-ui); font-size:.62rem; text-transform:uppercase;
  letter-spacing:.15em; font-weight:700; color:var(--accent-teal); padding:3px 10px;
  border-radius:100px; background:rgba(91,168,153,0.12); border:1px solid rgba(91,168,153,0.2);
}}
.figure-number {{ font-family:var(--font-ui); font-size:.72rem; color:var(--text-muted); }}
.figure-actions {{ display:flex; gap:6px; }}
.fig-btn {{
  width:30px; height:30px; border-radius:var(--radius-sm); border:1px solid var(--border-primary);
  background:transparent; color:var(--text-muted); cursor:pointer; display:flex;
  align-items:center; justify-content:center; font-size:.8rem; transition:all .2s;
}}
.fig-btn:hover {{
  background:var(--accent-blue-dim); color:var(--accent-blue);
  border-color:rgba(91,143,185,0.3);
}}
.figure-image-container {{
  padding:24px; display:flex; justify-content:center; background:#ffffff; position:relative;
}}
:root:not(.light) .figure-image-container {{ background:rgba(255,255,255,0.97); }}
.figure-image-container img {{ max-width:100%; height:auto; display:block; cursor:zoom-in; }}
.figure-caption {{
  padding:16px 24px 20px; border-top:1px solid var(--border-primary);
}}
.figure-caption p {{
  font-family:var(--font-ui); font-size:.8rem; color:var(--text-secondary);
  line-height:1.6; margin:0 !important;
}}
.figure-caption p strong {{ color:var(--text-primary); }}

#lightbox {{
  position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.92);
  backdrop-filter:blur(20px); display:flex; align-items:center; justify-content:center;
  opacity:0; pointer-events:none; transition:opacity .35s ease; cursor:zoom-out;
}}
#lightbox.active {{ opacity:1; pointer-events:all; }}
#lightbox img {{
  max-width:90vw; max-height:90vh; border-radius:var(--radius-md);
  box-shadow:0 20px 60px rgba(0,0,0,0.5); transform:scale(0.9);
  transition:transform .4s cubic-bezier(.22,1,.36,1);
}}
#lightbox.active img {{ transform:scale(1); }}

.math-block {{
  margin:36px 0; padding:32px; background:var(--gradient-card);
  border:1px solid var(--border-primary); border-radius:var(--radius-md);
  text-align:center; position:relative; overflow:hidden; box-shadow:var(--shadow-sm);
}}
.math-block::before {{
  content:''; position:absolute; top:0; left:0; right:0; height:2px;
  background:linear-gradient(90deg, transparent, var(--accent-blue), transparent);
}}
.math-block .katex-display {{ margin:0; }}
.math-block .katex {{ font-size:1.4rem; }}

.output-html-wrapper {{
  margin:20px 0; padding:20px; background:var(--bg-card); border-radius:var(--radius-md);
  border:1px solid var(--border-primary); overflow-x:auto;
}}
.output-html-wrapper table {{
  width:100%; border-collapse:collapse; font-family:var(--font-ui); font-size:.82rem;
}}
.output-html-wrapper th {{
  text-align:left; padding:10px 14px; background:var(--bg-secondary);
  color:var(--text-accent); font-weight:600; font-size:.7rem; text-transform:uppercase;
  letter-spacing:.1em; border-bottom:2px solid var(--border-accent);
}}
.output-html-wrapper td {{
  padding:8px 14px; border-bottom:1px solid var(--border-primary); color:var(--text-secondary);
}}

.report-footer {{
  padding:48px 60px; border-top:1px solid var(--border-primary); text-align:center;
}}
.footer-inner {{ max-width:var(--content-max); margin:0 auto; }}
.footer-line {{
  font-family:var(--font-ui); font-size:.72rem; color:var(--text-muted); margin-bottom:4px;
}}
.footer-line code {{ font-family:var(--font-mono); }}
.footer-brand {{
  font-family:var(--font-display); font-size:.85rem; font-weight:700;
  color:var(--text-accent); margin-top:12px;
}}

@keyframes fadeInUp {{
  from {{ opacity:0; transform:translateY(24px); }}
  to   {{ opacity:1; transform:translateY(0); }}
}}
@keyframes pulse {{
  0%, 100% {{ opacity:1; transform:scale(1); }}
  50%      {{ opacity:0.5; transform:scale(1.5); }}
}}
@media (max-width:960px) {{
  #sidebar {{ transform:translateX(calc(-1 * var(--sidebar-width))); }}
  #sidebar.open {{ transform:translateX(0); }}
  #sidebar-toggle {{ display:flex; }}
  #main {{ margin-left:0 !important; }}
  .hero {{ padding:80px 28px 60px; }}
  .content-area {{ padding:0 28px 80px; }}
  .report-footer {{ padding:40px 28px; }}
}}
::-webkit-scrollbar {{ width:6px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
::-webkit-scrollbar-thumb {{ background:var(--text-muted); border-radius:10px; }}
</style>
</head>
<body>

<div id="reading-progress"></div>
<div id="lightbox" onclick="this.classList.remove('active')">
  <img id="lightbox-img" src="" alt="Enlarged figure">
</div>
<button id="sidebar-toggle" onclick="toggleSidebar()" aria-label="Toggle sidebar">&#9776;</button>

<nav id="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-logo">
      <div class="logo-icon">R</div>
      Report
    </div>
    <div class="sidebar-meta">{date} &middot; {language}</div>
  </div>
  <div class="sidebar-nav">
    <div class="nav-section-label">Contents</div>
    {nav_items}
  </div>
  <div class="sidebar-footer">
    <button class="sidebar-btn" onclick="toggleTheme()" id="theme-btn">&#9788; Light</button>
    <button class="sidebar-btn" onclick="window.print()">&#9112; Print</button>
  </div>
</nav>

<div id="main">
  <header class="hero" id="hero">
    <div class="hero-inner">
      <div class="hero-badge"><span class="pulse"></span>Notebook Report</div>
      <h1>{title}</h1>
      <p class="hero-subtitle">Auto-generated interactive report from a Jupyter Notebook.</p>
      <div class="hero-meta">
        <div class="meta-item"><span class="meta-icon">&#9672;</span><span>Author: <strong>{author}</strong></span></div>
        <div class="meta-item"><span class="meta-icon">&#9719;</span><span>Date: <strong>{date}</strong></span></div>
        <div class="meta-item"><span class="meta-icon">&#8865;</span><span>Kernel: <strong>{kernel}</strong></span></div>
        <div class="meta-item"><span class="meta-icon">&#9632;</span><span>Figures: <strong>{n_figures}</strong></span></div>
        <div class="meta-item"><span class="meta-icon">&#9633;</span><span>Code Cells: <strong>{n_code_cells}</strong></span></div>
      </div>
    </div>
  </header>
  <div class="content-area"><div class="content-inner">
    {sections}
  </div></div>
  <footer class="report-footer">
    <div class="footer-inner">
      <div class="footer-line">Generated from <code>{source_file}</code></div>
      <div class="footer-brand">&#9672; nb2report</div>
    </div>
  </footer>
</div>

<script>
function updateProgress() {{
  const h = document.documentElement;
  const s = h.scrollTop / (h.scrollHeight - h.clientHeight);
  h.style.setProperty('--reading-progress', Math.min(s * 100, 100) + '%');
}}
window.addEventListener('scroll', updateProgress, {{ passive: true }});

const sObs = new IntersectionObserver(es => {{
  es.forEach(e => {{ if (e.isIntersecting) e.target.classList.add('visible'); }});
}}, {{ threshold: 0.08 }});
document.querySelectorAll('.section').forEach(s => sObs.observe(s));

const nObs = new IntersectionObserver(es => {{
  es.forEach(e => {{
    if (e.isIntersecting) {{
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      const t = document.querySelector('.nav-item[data-section="'+e.target.id+'"]');
      if (t) t.classList.add('active');
    }}
  }});
}}, {{ rootMargin: '-20% 0px -70% 0px' }});
document.querySelectorAll('[id]').forEach(s => {{
  if (document.querySelector('.nav-item[data-section="'+s.id+'"]')) nObs.observe(s);
}});

function toggleSidebar() {{
  const sb = document.getElementById('sidebar');
  sb.classList.toggle('open'); sb.classList.toggle('collapsed');
}}
function toggleTheme() {{
  const isLight = document.documentElement.classList.toggle('light');
  document.getElementById('theme-btn').innerHTML = isLight ? '&#9790; Dark' : '&#9788; Light';
  document.getElementById('hljs-theme').href = isLight
    ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css'
    : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css';
}}
function toggleCode(btn) {{
  const t = document.getElementById(btn.dataset.target);
  t.classList.toggle('collapsed');
  btn.textContent = t.classList.contains('collapsed') ? 'Show' : 'Hide';
}}
function copyCode(id, btn) {{
  const code = document.querySelector('#'+id+' code').textContent;
  navigator.clipboard.writeText(code).then(() => {{
    btn.textContent = '\u2713 Copied'; btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.classList.remove('copied'); }}, 2000);
  }});
}}
function openLightbox(img) {{
  document.getElementById('lightbox-img').src = img.src;
  document.getElementById('lightbox').classList.add('active');
}}
hljs.highlightAll();
document.addEventListener('DOMContentLoaded', () => {{
  renderMathInElement(document.body, {{
    delimiters: [
      {{ left: '$$', right: '$$', display: true }},
      {{ left: '\\(', right: '\\)', display: false }},
      {{ left: '\\[', right: '\\]', display: true }}
    ],
    throwOnError: false
  }});
}});
</script>
</body>
</html>'''


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert a Jupyter Notebook to a premium HTML report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nb2report.py analysis.ipynb
  python nb2report.py analysis.ipynb -o report.html --title "Q3 Analysis"
  python nb2report.py analysis.ipynb --hide-all-code --author "Data Team"

Cell tags (set in notebook metadata):
  "hide"   — collapse code by default (user can expand)
  "show"   — force code visible (overrides --hide-all-code)
  "remove" — exclude cell entirely from report

Or start a code cell with:
  # HIDE   — same as "hide" tag
  # REMOVE — same as "remove" tag
        """,
    )
    parser.add_argument("notebook", help="Path to .ipynb file")
    parser.add_argument("-o", "--output", help="Output HTML file path")
    parser.add_argument("--title", help="Report title (default: notebook filename)")
    parser.add_argument("--author", default="Research Lab", help="Author name")
    parser.add_argument("--hide-all-code", action="store_true", help="Hide all code cells by default")
    parser.add_argument("--show-all-code", action="store_true", help="Show all code cells by default")
    args = parser.parse_args()

    nb_path = args.notebook
    if not os.path.isfile(nb_path):
        print(f"Error: file not found: {nb_path}", file=sys.stderr)
        sys.exit(1)

    source_file = os.path.basename(nb_path)
    title = args.title or Path(nb_path).stem.replace("_", " ").replace("-", " ").title()
    output_path = args.output or Path(nb_path).stem + "_report.html"

    print(f"Parsing: {nb_path}")
    nb_data = parse_notebook(nb_path)
    print(f"  Sections: {len(nb_data['sections'])}")
    print(f"  Code cells: {nb_data['total_code_cells']}")
    print(f"  Figures: {nb_data['total_figures']}")

    print(f"Building HTML...")
    html = build_html(nb_data, title, args.author, args.hide_all_code, args.show_all_code, source_file)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"Done! → {output_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()

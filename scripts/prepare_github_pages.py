"""Prepare TrumpApprovalByState for publication from GitHub Pages /docs.

Run from your PyCharm project root:
    python scripts/prepare_github_pages.py

This DOES NOT commit or push anything. It makes targeted, backed-up website
changes and ensures the static public JSON is available and not git-ignored.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path.cwd()
HTML = ROOT / 'docs' / 'index.html'
JS = ROOT / 'docs' / 'assets' / 'js' / 'app.js'
CSS = ROOT / 'docs' / 'assets' / 'css' / 'styles.css'
PREVIEW = ROOT / 'scripts' / 'prepare_preview.py'
GITIGNORE = ROOT / '.gitignore'
JSON_SOURCE = ROOT / 'data' / 'processed' / 'state_approval_with_2024_votes.json'
JSON_PUBLIC = ROOT / 'docs' / 'data' / 'state_approval.json'
NOJEKYLL = ROOT / 'docs' / '.nojekyll'

DEV_NOTICE = '<p class="rights-note"><strong>Development status:</strong> Local preview only. Automated public republication of the full Civiqs dataset has not yet been confirmed as authorized. Do not commit the local polling JSON to a public repository until that issue is resolved.</p>'
CSS_UNUSED = '.method-copy .rights-note{color:#7f614a}'
OLD_JS_COMMENT = 'Data source: docs/data/state_approval.json (ignored by Git until permission is resolved).'
NEW_JS_COMMENT = 'Data source: docs/data/state_approval.json (published static snapshot).'

REQUIRED_ROWS = {'state', 'state_abbr', 'report_date', 'approve', 'disapprove', 'republican_approve', 'republican_disapprove', 'democratic_approve', 'democratic_disapprove', 'trump_2024_votes', 'total_2024_presidential_votes', 'trump_2024_vote_share_pct', 'fec_2024_source_url'}

# Deliberately do NOT git-ignore docs/data/state_approval.json: the public site needs it.
SAFE_IGNORE_LINES = (
    '/data/',               # Only root working data; docs/data must remain public.
    '.venv/', 'venv/',
    '.idea/',
    '__pycache__/', '*.py[cod]',
    '.ipynb_checkpoints/',
    '.env', '.env.*',
    '*.log',
)

def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f'{label}: expected 1 match, found {count}. Nothing changed.')
    return text.replace(old, new, 1)


def main() -> None:
    for path in (HTML, JS, CSS, PREVIEW, JSON_SOURCE):
        if not path.is_file():
            raise FileNotFoundError(f'Missing {path}. Run from the project root and confirm the previous patches succeeded.')

    original_html = HTML.read_text(encoding='utf-8')
    original_js = JS.read_text(encoding='utf-8')
    original_css = CSS.read_text(encoding='utf-8')
    original_preview = PREVIEW.read_text(encoding='utf-8')
    original_ignore = GITIGNORE.read_text(encoding='utf-8') if GITIGNORE.exists() else ''

    # Refuse to silently publish a stale dashboard.
    if 'data-sort-column="trump2024"' not in original_html:
        raise ValueError('FEC 2024 sortable table column is missing. Nothing changed.')
    if 'Estimated approval among registered voters' not in original_html:
        raise ValueError('Latest approval wording has not been applied. Run the previous patch first.')
    if 'Estimated approval among ${approvalPopulation}' not in original_js:
        raise ValueError('Latest JavaScript approval wording is missing. Nothing changed.')
    if '2024 presidential election' not in original_html.lower():
        raise ValueError('2024 election context is missing. Nothing changed.')

    rows = json.loads(JSON_SOURCE.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or len(rows) != 50:
        raise ValueError('Merged Civiqs/FEC JSON must contain exactly 50 state records.')
    names = [r.get('state') for r in rows]
    abbrs = [r.get('state_abbr') for r in rows]
    if len(set(names)) != 50 or len(set(abbrs)) != 50 or any(not REQUIRED_ROWS.issubset(r) for r in rows):
        raise ValueError('Invalid or incomplete 50-state data. No files changed.')
    if len({r['report_date'] for r in rows}) != 1:
        raise ValueError('State dates do not match. No files changed.')
    # 2024 election totals must agree with the included derived vote shares.
    for r in rows:
        votes = int(r['trump_2024_votes'])
        total = int(r['total_2024_presidential_votes'])
        pct = float(r['trump_2024_vote_share_pct'])
        if not (0 <= votes <= total and total > 0 and abs(100 * votes / total - pct) <= 0.011):
            raise ValueError(f"Invalid FEC vote share: {r['state']}. Nothing changed.")

    new_html = once(original_html, DEV_NOTICE, '', 'Development status paragraph')
    new_css = once(original_css, CSS_UNUSED, '', 'Unused development-status styling')
    new_js = once(original_js, OLD_JS_COMMENT, NEW_JS_COMMENT, 'JavaScript header comment')

    # prepare_preview.py must stop re-adding the JSON to .gitignore.
    old_ignore_setting = 'GITIGNORE_LINES = ["data/processed/", "docs/data/state_approval.json"]'
    new_ignore_setting = 'GITIGNORE_LINES = ["data/processed/"]'
    new_preview = once(original_preview, old_ignore_setting, new_ignore_setting, 'Preview ignore rule')
    new_preview = once(new_preview,
        'This explicitly prevents the generated Civiqs dataset from being accidentally\nadded to a public GitHub repository while reuse permissions are being settled.',
        'Copies the validated public snapshot into docs/data for GitHub Pages.',
        'Preview helper description')
    new_preview = once(new_preview,
        'print(f"Local-only JSON created: {DESTINATION}")',
        'print(f"GitHub Pages JSON created: {DESTINATION}")',
        'Preview output message')
    new_preview = once(new_preview,
        '    print("Reminder: public data republication permissions are still unresolved.")\n',
        '', 'Preview old reminder')

    # Remove any obsolete exact-file ignore entry. Preserve other user rules.
    cleaned_lines = [ln for ln in original_ignore.splitlines() if ln.strip() != 'docs/data/state_approval.json']
    missing = [ln for ln in SAFE_IGNORE_LINES if ln not in {x.strip() for x in cleaned_lines}]
    if missing:
        cleaned_lines += ['', '# Local environments and project working files', *missing]
    new_ignore = '\n'.join(cleaned_lines).rstrip('\n') + '\n'

    # Check JS syntax before touching project files. No stdin encoding pitfalls on Windows.
    node = shutil.which('node')
    if node:
        check = subprocess.run([node, '--check', '-'], input=new_js.encode('utf-8'), capture_output=True)
        if check.returncode != 0:
            raise RuntimeError('JavaScript syntax check failed: ' + check.stderr.decode('utf-8', errors='replace'))

    changes = {HTML: new_html, JS: new_js, CSS: new_css, PREVIEW: new_preview, GITIGNORE: new_ignore}
    backup_root = ROOT / 'data' / 'raw' / 'dashboard_backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    for path in changes:
        if path.exists():
            backup = backup_root / path.relative_to(ROOT)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
    if JSON_PUBLIC.is_file():
        backup = backup_root / JSON_PUBLIC.relative_to(ROOT)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(JSON_PUBLIC, backup)
    for path, body in changes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        print(f'Updated: {path.relative_to(ROOT)}')
    JSON_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(JSON_SOURCE, JSON_PUBLIC)
    NOJEKYLL.touch()
    print(f'Published snapshot prepared: {JSON_PUBLIC.relative_to(ROOT)} ({len(rows)} states, Civiqs date {rows[0]["report_date"]})')
    print('Prepared: docs/.nojekyll')

    if (ROOT / '.git').exists() and shutil.which('git'):
        ignore_check = subprocess.run(['git', 'check-ignore', '-v', 'docs/data/state_approval.json'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if ignore_check.returncode == 0:
            print('WARNING: Another gitignore rule still excludes the public JSON:')
            print(ignore_check.stdout.rstrip())
            print('Resolve this before committing. Run: git check-ignore -v docs/data/state_approval.json')
        else:
            print('Git ignore check: public JSON is not ignored.')

    print('SUCCESS: Website ready for Git staging. NO Git commit or push has occurred.')
    print('Publishing docs/data/state_approval.json makes the 50-state snapshot publicly downloadable.')
    print(f'Local backups: {backup_root}')


if __name__ == '__main__':
    main()

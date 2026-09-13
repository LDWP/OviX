# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec file for OviX Backend
This configuration builds the FastAPI backend into a standalone executable.
"""

import sys
from pathlib import Path

# Project paths
project_root = Path(__file__).parent.parent.parent
backend_src = project_root / 'backend' / 'src'
config_dir = project_root / 'config'

block_cipher = None

a = Analysis(
    ['backend_entry.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include config files
        (str(config_dir), 'config'),
        # Include pywikibot family files if they exist
        (str(project_root / 'pywikibot'), 'pywikibot') if (project_root / 'pywikibot').exists() else None,
    ],
    hiddenimports=[
        # FastAPI and dependencies
        'uvicorn',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'pydantic',
        'pydantic.dataclasses',
        
        # Pywikibot and related
        'pywikibot',
        'pywikibot.bot',
        'pywikibot.data',
        'pywikibot.family',
        'pywikibot.page',
        'pywikibot.site',
        'requests',
        'requests.adapters',
        'urllib3',
        
        # Wikipedia maintenance modules
        'wikipedia_maintenance',
        'wikipedia_maintenance.utils',
        'wikipedia_maintenance.utils.api_throttler',
        'wikipedia_maintenance.utils.kill_switch_manager',
        'wikipedia_maintenance.utils.published_tracker',
        'wikipedia_maintenance.utils.analyzed_tracker',
        'wikipedia_maintenance.utils.database',
        'wikipedia_maintenance.utils.config',
        'wikipedia_maintenance.orchestrator',
        'wikipedia_maintenance.orchestrator.scheduler_state_sqlite',
        'wikipedia_maintenance.orchestrator.daily_article_collector',
        'wikipedia_maintenance.retrievers',
        'wikipedia_maintenance.retrievers.category',
        'wikipedia_maintenance.retrievers.file',
        'wikipedia_maintenance.retrievers.manual',
        'wikipedia_maintenance.retrievers.petscan',
        'wikipedia_maintenance.retrievers.user_contribs',
        'wikipedia_maintenance.utils.reference_template_helper',
        
        # Data processing
        'pandas',
        'pandas._libs',
        'numpy',
        'numpy._core',
        
        # HTML parsing
        'bs4',
        'lxml',
        'lxml.etree',
        
        # Configuration
        'yaml',
        'dotenv',
        
        # Logging
        'logging_config',
        
        # SQLite
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused heavy packages
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out None values from datas
a.datas = [d for d in a.datas if d is not None]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ovix_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ovix_backend',
)

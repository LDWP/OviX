"""
Generic Reference Template Helper for Wikipedia reference templates.

This module provides utilities for:
- Detecting various reference templates ({{Lien web}}, {{article}}, {{ouvrage}}, etc.)
- Parsing template parameters (robust to nested templates/links)
- Generating reference templates with archive parameters

Hardened version: fixes nested-template parsing, brace-balanced template
extraction, safer parameter merging, input validation, and immutability
of parsed structures.

This file merges the correct, validated semantics of the original
"hardened" implementation with later quality-of-life improvements
(TTL-based YAML cache, stricter domain validation, factored-out
helpers for site-domain correction and template rebuilding).

LOCKED BEHAVIOR (per bot policy review):
- |site= is NEVER added, modified, or corrected by archive-repair logic.
- |consulté le= is NEVER added by archive-repair logic (reserved for humans).
- "www." is NEVER stripped from any domain/site value.
- Original parameter spacing/formatting is preserved EXACTLY as written
  by the original contributor, both for existing parameters (untouched)
  and for newly added parameters (matched to the template's own style).
  This includes spacing on BOTH sides of '|' AND on BOTH sides of '='.
  Bots must not perform whitespace-only "cleanup" edits.
"""

from __future__ import annotations

import re
import logging
import os
import time
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReferenceTemplate:
    """Parsed reference template (immutable snapshot)."""
    template_name: str
    parameters: Dict[str, str] = field(default_factory=dict)
    full_match: str = ""
    start_position: int = -1
    end_position: int = -1
    is_supported: bool = True  # True if template is in KNOWN_TEMPLATE_NAMES


class ReferenceTemplateHelper:
    """
    Generic helper for Wikipedia reference template manipulation.

    Handles multiple reference template types:
    - {{Lien web}}
    - {{article}}
    - {{ouvrage}}
    - {{Lien brisé}}

    When a dead link is repaired with an archive, the helper generates
    the appropriate template format with archive parameters.
    """

    # Template names recognized as reference templates (case-insensitive).
    # Matched against the template's own name (after {{ and before first | or }}).
    KNOWN_TEMPLATE_NAMES = {
        'lien web': 'Lien web',
        'lien_web': 'Lien web',
        'article': 'article',
        'ouvrage': 'ouvrage',
        'chapitre': 'chapitre',
        'thèse': 'thèse',
        'these': 'thèse',
        'podcast': 'podcast',
        'vidéo': 'vidéo',
        'video': 'vidéo',
        'lien vidéo': 'Lien vidéo',
        'lien_video': 'Lien vidéo',
        'lien brisé': 'Lien brisé',
        'lien_brisé': 'Lien brisé',
        'lien archive': 'Lien archive',
        'lien_archive': 'Lien archive',
        'interview': 'interview',
        # English citation templates (mapped to French equivalents)
        'cite web': 'Lien web',
        'cite_web': 'Lien web',
        'cite news': 'Lien web',
        'cite_news': 'Lien web',
        'cite report': 'Lien web',
        'cite_report': 'Lien web',
        'cite journal': 'article',
        'cite_journal': 'article',
        'cite book': 'ouvrage',
        'cite_book': 'ouvrage',
    }

    # Templates for which it is semantically valid to promote the archive
    # URL to the main `url` parameter. `Lien brisé` explicitly marks a
    # link as broken, so silently pointing `url` at the archive there
    # would misrepresent the template's own semantics.
    # NOTE: All names are lowercase for case-insensitive comparison (all usages normalize template names).
    # lien archive is NOT included here as it uses horodatage archive parameter instead
    TEMPLATES_SUPPORTING_ARCHIVE_AS_MAIN_LINK = {'lien web', 'interview', 'podcast', 'vidéo', 'lien vidéo'}

    # Templates for which |brisé le= is semantically valid.
    # These are web resources that may have dead links that need to be marked.
    # NOTE: All names are lowercase for case-insensitive comparison.
    # lien web is included as it is documented with this parameter
    # article is NOT included as it is not documented in {{Article}} template documentation
    # chapitre and thèse are NOT included as they are not documented with this parameter
    # ouvrage IS included as bots add brisé le for archive repairs (even if undocumented)
    TEMPLATES_SUPPORTING_BRISE_LE = {'lien web', 'ouvrage'}

    # Templates for which a |site= parameter is not semantically valid
    # (e.g. a book has no "site"). Kept for reference/introspection only:
    # archive-repair logic no longer touches |site= at all (see LOCKED
    # BEHAVIOR at top of file), but this set is still used by
    # generate_enriched_template (ReferenceEnricherAnalyzer path) and by
    # informational helpers.
    # Books and chapters are physical/digital publications, not web sites.
    # Articles are journal articles, not web sites, and should not have |site= added.
    # Theses are academic documents, not web sites.
    TEMPLATES_WITHOUT_SITE_PARAM = {'ouvrage', 'chapitre', 'article', 'thèse'}

    # All variants of the site parameter that should be checked for consistency
    # This includes site, website, périodique, work and their case variations
    # Used across multiple methods to ensure consistent blocking behavior
    SITE_PARAMETER_VARIANTS = ('site', 'Site', 'SITE', 'website', 'Website', 'WEBSITE', 'périodique', 'Périodique', 'PÉRIODIQUE', 'work', 'Work', 'WORK')

    # Whitelist: Templates for which |consulté le= is semantically valid.
    # These are web resources that are consulted online.
    # chapitre is included for lire en ligne context.
    # ouvrage is included for archive repair context (when link is corrected)
    # NOTE: All names are lowercase for case-insensitive comparison.
    # lien archive is NOT included as it has different semantics (uses horodatage archive).
    # NOTE: kept for use by generate_enriched_template only; archive-repair
    # logic never adds |consulté le= (see LOCKED BEHAVIOR at top of file).
    TEMPLATES_SUPPORTING_CONSULTE_LE = {'lien web', 'article', 'ouvrage', 'chapitre', 'interview', 'podcast', 'vidéo', 'lien vidéo'}

    # Templates for which archive parameters (archive-url, archive-date)
    # are NOT semantically valid. These are physical/digital publications that
    # don't have web URLs that can be archived.
    # Note: this does NOT mean that |brisé le= is invalid; its support
    # is defined separately by TEMPLATES_SUPPORTING_BRISE_LE.
    # ouvrage is NOT included here as it accepts archiveurl/archivedate (even if undocumented)
    # chapitre and thèse are included as they don't have archivable web URLs
    # lien archive is included as it uses horodatage archive parameter instead
    # lien brisé is included as it's a historical marker and should not be transformed
    TEMPLATES_WITHOUT_ARCHIVE_PARAMS = {'chapitre', 'thèse', 'lien archive', 'lien brisé'}

    # Maps raw archive-provider identifiers to their display/article name
    # on the French Wikipedia. Used only for the human-readable prose
    # rendering (render_archive_repair_prose) — never written into the
    # generated wikitext, since no real reference template has an
    # equivalent parameter.
    PROVIDER_NAMES: Dict[str, str] = {
        'WaybackMachine': 'Internet Archive',
        'Archive.org': 'Internet Archive',
        'Arquivo.pt': 'Arquivo.pt',
        'Wikiwix': 'Wikiwix',
    }

    # Maps archive provider domains to their Wikipedia site names (with wikilinks).
    # NOTE: retained for potential future/other use (e.g. prose rendering),
    # but archive-repair logic no longer writes |site= at all, so this
    # mapping is no longer consulted from generate_archive_repair_template.
    ARCHIVE_DOMAIN_TO_SITE_NAME: Dict[str, str] = {
        'web.archive.org': '[[Internet Archive]]',
        'archive.org': '[[Internet Archive]]',
        'wikiwix.com': '[[Wikiwix]]',
        'archive.wikiwix.com': '[[Wikiwix]]',
        'web.arquivo.pt': 'Arquivo.pt',
        'arquivo.pt': 'Arquivo.pt',
        'archive.today': '[[Archive.today]]',
    }

    # Best-effort mapping from a bare domain (as returned by
    # _safe_extract_domain, i.e. urlparse().netloc with any "www."
    # already implied by the source URL) to a human-readable site name
    # for the |site= parameter.
    # NOTE: This is now loaded from case_normalization_data.yaml for centralized maintenance.
    # The hardcoded fallback below is only used if the YAML file cannot be loaded.
    DOMAIN_TO_SITE_NAME: Dict[str, str] = {}

    # Cache metadata for YAML reload with TTL, so a config change in
    # production doesn't require a redeploy/restart to take effect.
    _domain_mapping_load_time: Optional[float] = None
    _domain_mapping_ttl_seconds: float = 300  # 5 minutes TTL

    @classmethod
    def _load_domain_to_site_name_mapping(cls, force_reload: bool = False) -> Dict[str, str]:
        """
        Load domain to site name mapping from case_normalization_data.yaml.

        Uses TTL-based caching to avoid reloading on every call.

        Args:
            force_reload: If True, bypass TTL and force reload from disk.

        Returns:
            Dictionary mapping domains to human-readable site names (preserving wiki link format [[...]]).
            Falls back to empty dict if file cannot be loaded.
        """
        # Check if cache is still valid (within TTL)
        current_time = time.time()
        if not force_reload and cls._domain_mapping_load_time is not None:
            cache_age = current_time - cls._domain_mapping_load_time
            if cache_age < cls._domain_mapping_ttl_seconds and cls.DOMAIN_TO_SITE_NAME:
                logger.debug(f"Using cached domain mapping (age={cache_age:.1f}s, TTL={cls._domain_mapping_ttl_seconds}s)")
                return cls.DOMAIN_TO_SITE_NAME

        logger.info(f"Loading domain mapping from YAML (force_reload={force_reload})")

        try:
            # Use PROJECT_ROOT from environment if available (set by api/main.py)
            # Otherwise fall back to relative path calculation
            project_root = os.environ.get('PROJECT_ROOT')
            if project_root:
                config_path = Path(project_root) / "config" / "case_normalization_data.yaml"
            else:
                # Fallback: Go from backend/src/wikipedia_maintenance/utils/ to project root
                # Path: backend/src/wikipedia_maintenance/utils -> backend/src/wikipedia_maintenance -> backend/src -> backend -> project root
                config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "case_normalization_data.yaml"

            logger.info(f"Loading domain mapping from: {config_path}")
            logger.info(f"Config path exists: {config_path.exists()}")

            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                    logger.info(f"YAML loaded successfully, keys: {list(config_data.keys()) if config_data else 'None'}")

                    if config_data and 'domain_to_site_name' in config_data:
                        logger.info(f"domain_to_site_name found with {len(config_data['domain_to_site_name'])} entries")
                        # Extract the site names from the YAML format
                        # YAML format: "domain.com: [[Site Name]]" -> parsed as [['Site Name']]
                        # We need to extract the inner string and reconstruct [[Site Name]]
                        mapping = {}
                        for domain, wiki_links in config_data['domain_to_site_name'].items():
                            if wiki_links:
                                # Handle both list format [['Billboard']] and string format '[[Billboard]]'
                                if isinstance(wiki_links, list) and len(wiki_links) > 0:
                                    inner = wiki_links[0]
                                    if isinstance(inner, list) and len(inner) > 0:
                                        site_name = f"[[{inner[0]}]]"
                                    else:
                                        site_name = str(inner)
                                else:
                                    # String format: directly use the value (e.g., '[[Billboard]]')
                                    site_name = str(wiki_links)
                                mapping[domain] = site_name
                        logger.info(f"Loaded {len(mapping)} domain->site name mappings from YAML")
                        # Update cache
                        cls.DOMAIN_TO_SITE_NAME = mapping
                        cls._domain_mapping_load_time = current_time
                        return mapping
                    else:
                        logger.warning("domain_to_site_name not found in config_data")
        except Exception as e:
            logger.warning(f"Failed to load domain_to_site_name from YAML: {e}. Using empty mapping.")
            import traceback
            logger.warning(f"Traceback: {traceback.format_exc()}")

        return {}

    @classmethod
    def reload_domain_mapping(cls) -> None:
        """
        Force reload the domain to site name mapping from YAML.

        This bypasses the TTL cache and is useful when the config file
        changes in production without redeployment.
        """
        logger.info("Force reloading domain mapping from YAML")
        cls._load_domain_to_site_name_mapping(force_reload=True)

    # French month names for prose date rendering ("5 janvier 2015").
    _FRENCH_MONTHS = [
        '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
        'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
    ]

    # Common parameters across reference templates (fallback ordering).
    COMMON_PARAMETERS: List[str] = [
        'langue',
        'auteur', 'auteur1', 'auteur2', 'auteur3', 'auteur4', 'auteur5',
        'auteur prénom', 'auteur nom', 'auteur lien',
        'auteur1 prénom', 'auteur1 nom', 'auteur1 lien',
        'auteur2 prénom', 'auteur2 nom', 'auteur2 lien',
        'auteur3 prénom', 'auteur3 nom', 'auteur3 lien',
        'et al.', 'auteur institutionnel',
        'traducteur', 'photographe', 'directeur', 'éditeur', 'publisher',
        'titre', 'sous-titre', 'traduction titre', 'description',
        'url', 'lire en ligne', 'url texte', 'lien',
        'format électronique', 'accès url',
        'série', 'work', 'site', 'website', 'périodique', 'journal',
        'lieu', 'lieu édition', 'location',
        'date', 'année', 'year', 'en ligne le', 'en ligne',
        'date jour', 'date mois', 'date année',
        'volume', 'numéro', 'issue', 'pages', 'page',
        'archive-url', 'archiveurl', 'archive-date', 'archivedate',
        'brisé le', 'dead-url', 'deadurl', 'lien brisé',
        'isbn', 'issn', 'e-issn', 'oclc', 'pmid', 'pmcid',
        'doi', 'accès doi', 'jstor', 'bibcode', 'math reviews', 'zbmath', 'arxiv',
        'consulté le', 'extrait', 'citation', 'quote', 'passage',
        'id', 'libellé', 'plume', 'nature document', 'afficher plume', 'nocat',
    ]

    TEMPLATE_SPECIFIC_PARAMETERS: Dict[str, List[str]] = {
        'Lien web': [
            'langue',
            'auteur', 'auteur prénom', 'auteur nom', 'auteur lien', 'auteur responsabilité', 'auteur directeur',
            'auteur2', 'auteur2 prénom', 'auteur2 nom', 'auteur2 lien', 'auteur2 responsabilité', 'auteur2 directeur',
            'auteur3', 'auteur3 prénom', 'auteur3 nom',
            'auteur4', 'auteur4 prénom', 'auteur4 nom',
            'auteur5', 'auteur5 prénom', 'auteur5 nom',
            'auteur6', 'auteur6 prénom', 'auteur6 nom',
            'auteur7', 'auteur7 prénom', 'auteur7 nom',
            'auteur8', 'auteur8 prénom', 'auteur8 nom',
            'auteur9', 'auteur9 prénom', 'auteur9 nom',
            'auteur10', 'auteur10 prénom', 'auteur10 nom',
            'auteur11', 'auteur11 prénom', 'auteur11 nom',
            'auteur12', 'auteur12 prénom', 'auteur12 nom',
            'auteur13', 'auteur13 prénom', 'auteur13 nom',
            'auteur14', 'auteur14 prénom', 'auteur14 nom',
            'et al.', 'auteur institutionnel',
            'traducteur', 'photographe',
            'titre', 'sous-titre', 'traduction titre', 'description',
            'url', 'lire en ligne', 'url texte', 'lien',
            'format électronique', 'accès url',
            'série', 'work', 'site', 'website', 'périodique',
            'lieu', 'lieu édition', 'location',
            'éditeur', 'publisher', 'editeur',
            'date', 'année', 'year', 'en ligne le', 'en ligne',
            'date jour', 'date mois', 'date année',
            'archive-url', 'archiveurl', 'archive-date', 'archivedate',
            'brisé le', 'dead-url', 'deadurl', 'lien brisé',  # Recognition only, never generated by OviX
            'isbn', 'issn', 'e-issn', 'oclc', 'pmid', 'pmcid',
            'doi', 'accès doi', 'jstor', 'bibcode', 'math reviews', 'zbmath', 'arxiv',
            'consulté le', 'extrait', 'citation', 'quote', 'page', 'pages', 'passage',
            'id', 'libellé', 'plume', 'nature document', 'afficher plume', 'nocat',
        ],
        'article': [
            'langue',
            'auteur', 'auteur prénom', 'auteur nom', 'auteur lien', 'auteur responsabilité', 'auteur directeur',
            'auteur2', 'auteur2 prénom', 'auteur2 nom', 'auteur2 lien', 'auteur2 responsabilité', 'auteur2 directeur',
            'auteur3', 'auteur3 prénom', 'auteur3 nom',
            'auteur4', 'auteur4 prénom', 'auteur4 nom',
            'auteur5', 'auteur5 prénom', 'auteur5 nom',
            'auteur6', 'auteur6 prénom', 'auteur6 nom',
            'auteur7', 'auteur7 prénom', 'auteur7 nom',
            'auteur8', 'auteur8 prénom', 'auteur8 nom',
            'auteur9', 'auteur9 prénom', 'auteur9 nom',
            'auteur10', 'auteur10 prénom', 'auteur10 nom',
            'auteur11', 'auteur11 prénom', 'auteur11 nom',
            'auteur12', 'auteur12 prénom', 'auteur12 nom',
            'auteur13', 'auteur13 prénom', 'auteur13 nom',
            'auteur14', 'auteur14 prénom', 'auteur14 nom',
            'et al.', 'auteur institutionnel',
            'traducteur', 'photographe',
            'titre', 'sous-titre', 'traduction titre', 'description',
            'url', 'lire en ligne', 'url texte', 'lien',
            'format électronique', 'accès url',
            'série', 'work', 'site', 'website', 'périodique',
            'lieu', 'lieu édition', 'location',
            'éditeur', 'publisher', 'editeur',
            'date', 'année', 'year', 'en ligne le', 'en ligne',
            'date jour', 'date mois', 'date année',
            'volume', 'numéro', 'issue', 'pages', 'page',
            'archive-url', 'archiveurl', 'archive-date', 'archivedate',
            'dead-url', 'deadurl', 'lien brisé',  # Recognition only, not generated by OviX
            'isbn', 'issn', 'e-issn', 'oclc', 'pmid', 'pmcid',
            'doi', 'accès doi', 'jstor', 'bibcode', 'math reviews', 'zbmath', 'arxiv',
            'consulté le', 'extrait', 'citation', 'quote', 'passage',
            'id', 'libellé', 'plume', 'nature document', 'afficher plume', 'nocat',
        ],
        'ouvrage': [
            'langue',
            'auteur', 'auteur prénom', 'auteur nom', 'auteur lien', 'auteur responsabilité', 'auteur directeur',
            'auteur2', 'auteur2 prénom', 'auteur2 nom', 'auteur2 lien', 'auteur2 responsabilité', 'auteur2 directeur',
            'auteur3', 'auteur3 prénom', 'auteur3 nom',
            'auteur4', 'auteur4 prénom', 'auteur4 nom',
            'auteur5', 'auteur5 prénom', 'auteur5 nom',
            'auteur6', 'auteur6 prénom', 'auteur6 nom',
            'auteur7', 'auteur7 prénom', 'auteur7 nom',
            'auteur8', 'auteur8 prénom', 'auteur8 nom',
            'auteur9', 'auteur9 prénom', 'auteur9 nom',
            'auteur10', 'auteur10 prénom', 'auteur10 nom',
            'et al.', 'auteur institutionnel',
            'traducteur', 'langue originale', 'préface', 'postface', 'illustrateur', 'photographe', 'champ libre',
            'titre', 'sous-titre', 'titre original', 'titre traduction',
            'volume', 'tome', 'volume titre',
            'lieu', 'éditeur', 'nature ouvrage', 'collection', 'série', 'numéro dans collection',
            'année', 'mois', 'jour', 'date', 'édition numéro', 'année première édition', 'réimpression',
            'format livre', 'pages totales', 'passage', 'page',
            'isbn', 'isbn2', 'isbn3', 'isbn 10', 'isbn erroné',
            'issn', 'e-issn', 'ismn', 'ean', 'oclc', 'notice bnf', 'sbn', 'lccn', 'dnb',
            'pmid', 'doi', 'accès doi', 'jstor', 'bibcode', 'math reviews', 'zbmath', 'arxiv', 'hal', 'hdl',
            'accès hdl', 's2cid', 'libris', 'citeseerx', 'jfm', 'sudoc', 'wikisource',
            'présentation en ligne', 'lire en ligne', 'accès url', 'format électronique', 'consulté le',
            'archive-url', 'archiveurl', 'archive-date', 'archivedate', 'brisé le',  # Bot archive additions per Wikipedia docs
            'partie', 'chapitre numéro', 'chapitre titre',
            'identifiant', 'libellé', 'référence', 'référence simplifiée', 'extrait', 'commentaire', 'plume', 'nocat',
        ],
        'chapitre': [
            'langue',
            'auteur', 'auteur prénom', 'auteur nom', 'auteur lien',
            'titre', 'sous-titre',
            'titre ouvrage',
            'ouvrage',
            'éditeur',
            'lieu',
            'année', 'date',
            'volume', 'tome',
            'isbn', 'issn',
            'pages', 'page', 'passage',
            'présentation en ligne', 'lire en ligne', 'écouter en ligne', 'format électronique', 'consulté le',
            'id', 'libellé',
        ],
        'Lien brisé': [
            'titre', 'url', 'date', 'brisé le', 'archive-url', 'archive-date',
        ],
        'Lien archive': [
            'titre', 'url', 'horodatage archive', 'date', 'éditeur', 'format',
            'langue', 'auteur', 'auteur prénom', 'auteur nom', 'auteur lien',
            'site', 'périodique',
            'lieu',
            'page', 'pages', 'passage',
            'id', 'libellé',
            # Obsolete parameters (recognition only, never generated by OviX):
            # 'consulté le', 'archive-url', 'archive-date', 'brisé le'
        ],
        'Lien vidéo': [
            'langue',
            'auteur', 'auteur prénom', 'auteur nom', 'auteur lien', 'auteur responsabilité',
            'auteur2', 'auteur2 prénom', 'auteur2 nom', 'auteur2 lien', 'auteur2 responsabilité',
            'auteur3', 'auteur3 prénom', 'auteur3 nom',
            'et al.', 'auteur institutionnel',
            'traducteur', 'photographe',
            'titre', 'sous-titre', 'traduction titre', 'description',
            'url', 'lire en ligne', 'url texte', 'lien',
            'format électronique', 'accès url',
            'série', 'work', 'site', 'website', 'périodique',
            'lieu', 'lieu édition', 'location',
            'éditeur', 'publisher', 'editeur',
            'date', 'année', 'year', 'en ligne le', 'en ligne',
            'date jour', 'date mois', 'date année',
            'archive-url', 'archiveurl', 'archive-date', 'archivedate',
            'brisé le', 'dead-url', 'deadurl', 'lien brisé',  # Recognition only, never generated by OviX
            'isbn', 'issn', 'e-issn', 'oclc', 'pmid', 'pmcid',
            'doi', 'accès doi', 'jstor', 'bibcode', 'math reviews', 'zbmath', 'arxiv',
            'consulté le', 'extrait', 'citation', 'quote', 'page', 'pages', 'passage',
            'id', 'libellé', 'plume', 'nature document', 'afficher plume', 'nocat',
            'durée', 'format', 'genre',
        ],
    }

    # Matches the template's opening tag and captures its bare name,
    # e.g. "{{ Lien web |" -> "Lien web". Used only to identify the
    # template type once brace-balanced extraction has found its bounds.
    _TEMPLATE_NAME_RE = re.compile(r'\{\{\s*([^|{}]+?)\s*(?:\||\}\})')

    # Strict domain validation for |site= resolution: alphanumeric,
    # hyphens, and dots, with at least one dot and a TLD of 2+ chars.
    # Prevents treating a literal, human-readable name written into
    # |site= (e.g. "Radio-Canada.ca") as a bare domain to re-map.
    _DOMAIN_PATTERN = re.compile(r'^[a-z0-9.-]+\.[a-z]{2,}$', re.IGNORECASE)

    @staticmethod
    def _normalize_template_name(name: str) -> str:
        """
        Normalize a template name for consistent comparison across all sets.

        This normalization is faithful to MediaWiki's behavior for template names:
        - Underscores and spaces are equivalent
        - Multiple spaces are collapsed to single spaces
        - Leading/trailing spaces are trimmed
        - Case is normalized to lowercase

        This ensures that all set lookups (TEMPLATES_SUPPORTING_*, etc.)
        work consistently regardless of input format.

        Args:
            name: Template name (e.g., "Lien web", "lien_web", "Lien_Web", "Lien _ web")

        Returns:
            Normalized lowercase name with single spaces (e.g., "lien web")
        """
        # Replace underscores with spaces (MediaWiki treats them as equivalent)
        with_spaces = name.replace('_', ' ')
        # Convert to lowercase
        lowercased = with_spaces.lower()
        # Collapse multiple spaces to single space (MediaWiki behavior)
        collapsed = ' '.join(lowercased.split())
        return collapsed

    @staticmethod
    def _get_canonical_template_name(name: str) -> str:
        """
        Get the canonical template name from an alias or raw name.

        Uses KNOWN_TEMPLATE_NAMES to map aliases to their canonical forms.
        If the name is not in the mapping, returns the normalized name as-is.

        Uses _normalize_template_name for robust normalization (handles
        multiple spaces, underscores, etc. consistently with MediaWiki behavior).

        Args:
            name: Template name (e.g., "cite web", "Lien web", "lien_web", "Lien _ web")

        Returns:
            Canonical template name (e.g., "Lien web" for "cite web" if mapped)
        """
        normalized = ReferenceTemplateHelper._normalize_template_name(name)
        return ReferenceTemplateHelper.KNOWN_TEMPLATE_NAMES.get(normalized, normalized)

    @staticmethod
    def _get_param_any(parameters: Dict[str, str], variants: tuple) -> Optional[str]:
        """Return the first non-None value found among the given parameter
        name variants, or None if none of them are present."""
        for name in variants:
            value = parameters.get(name)
            if value is not None:
                return value
        return None

    # Parses `key=value` pairs from *top-level* pipe-separated segments
    # only (see _split_top_level). Segments are pre-split respecting
    # nested {{ }} and [[ ]].
    #
    # IMPORTANT (spacing fidelity): this regex captures, as SEPARATE named
    # groups, the whitespace immediately before the '=' (eq_before) and
    # immediately after it (eq_after), instead of silently discarding
    # them via a blanket '\s*=\s*'. This is what allows _rebuild_template
    # to reproduce "titre = Sound" (spaced) as-is instead of collapsing
    # it to "titre=Sound" (compact) when a template is only partially
    # touched (e.g. only archive-url/archive-date/brisé le added).
    #
    # `key` itself is captured non-greedily with no surrounding space:
    # any leading whitespace on the segment (i.e. whitespace right after
    # the previous '|') is left for the caller to inspect separately
    # (see the after_pipe handling in _rebuild_template / the leading
    # '\s*' consumed here for _parse_template_parameters purposes).
    _PARAM_KV_RE = re.compile(
        r'^\s*(?P<key>[^=]+?)(?P<eq_before>[ \t]*)=(?P<eq_after>[ \t]*)(?P<value>.*)$',
        re.DOTALL,
    )

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Template discovery
    # ------------------------------------------------------------------

    def find_reference_template(self, content: str, url: str, position: int) -> Optional[ReferenceTemplate]:
        """
        Find if a URL is part of a reference template.

        Uses brace-balanced scanning (not naive rfind/find) so templates
        containing nested templates (e.g. {{date|...}}) or double
        brackets ([[...]]) in parameter values are handled correctly.

        Args:
            content: Full wikitext content
            url: URL to search for (used only for logging)
            position: Position of the URL in content

        Returns:
            ReferenceTemplate if found, None otherwise
        """
        if not content or position < 0 or position > len(content):
            self._logger.info(f"TEMPLATE_NOT_FOUND | url={url} | reason=invalid_position")
            return None

        bounds = self._find_enclosing_template_bounds(content, position)
        if bounds is None:
            self._logger.info(f"TEMPLATE_NOT_FOUND | url={url} | reason=no_enclosing_template")
            return None

        template_start, template_end = bounds
        template_content = content[template_start:template_end]

        self._logger.info(
            f"TEMPLATE_CANDIDATE | url={url} | template_start={template_start} | "
            f"template_end={template_end} | content_length={len(template_content)}"
        )

        name_match = self._TEMPLATE_NAME_RE.match(template_content)
        if not name_match:
            self._logger.info(f"TEMPLATE_NOT_MATCHED | url={url} | reason=unparseable_name")
            return None

        raw_name = name_match.group(1).strip()
        normalized = self._normalize_template_name(raw_name)
        template_name = self.KNOWN_TEMPLATE_NAMES.get(normalized)

        if template_name is None:
            # Template exists but is not supported - return with is_supported=False
            # This allows callers to distinguish between "no template" and "unsupported template"
            parameters = self._parse_template_parameters(template_content)
            self._logger.info(
                f"TEMPLATE_UNSUPPORTED | url={url} | raw_name={raw_name!r} | "
                f"template_content={template_content[:200]!r}"
            )
            return ReferenceTemplate(
                template_name=raw_name,  # Use the actual name found
                parameters=parameters,
                full_match=template_content,
                start_position=template_start,
                end_position=template_end,
                is_supported=False  # Mark as unsupported
            )

        parameters = self._parse_template_parameters(template_content)

        self._logger.info(
            f"TEMPLATE_FOUND | url={url} | template_name={template_name} | "
            f"parameters_count={len(parameters)}"
        )

        return ReferenceTemplate(
            template_name=template_name,
            parameters=parameters,
            full_match=template_content,
            start_position=template_start,
            end_position=template_end,
            is_supported=True  # Mark as supported
        )

    def _find_enclosing_template_bounds(self, content: str, position: int) -> Optional[Tuple[int, int]]:
        """
        Find the start/end indices of the innermost {{...}} template
        that encloses `position`, using proper brace balancing.

        Returns (start, end) where end is exclusive (i.e. content[start:end]
        includes the trailing '}}'), or None if no enclosing template exists.
        """
        # Find all template start markers before `position`, walk forward
        # from each candidate (nearest first) balancing braces until we
        # either enclose `position` or overshoot it.
        search_from = 0
        best: Optional[Tuple[int, int]] = None

        while True:
            start = content.find('{{', search_from)
            if start == -1 or start > position:
                break

            end = self._match_balanced_braces(content, start)
            if end is not None and start <= position < end:
                # Keep the innermost (latest-starting) enclosing template.
                best = (start, end)

            search_from = start + 2

        return best

    @staticmethod
    def _match_balanced_braces(content: str, open_pos: int) -> Optional[int]:
        """
        Given the index of an opening '{{', return the index just past
        the matching closing '}}', accounting for nested {{ }}.
        Returns None if unbalanced.
        """
        depth = 0
        i = open_pos
        length = len(content)
        while i < length - 1:
            two = content[i:i + 2]
            if two == '{{':
                depth += 1
                i += 2
                continue
            if two == '}}':
                depth -= 1
                i += 2
                if depth == 0:
                    return i
                continue
            i += 1
        return None

    # ------------------------------------------------------------------
    # Parameter parsing
    # ------------------------------------------------------------------

    def _parse_template_parameters(self, template_content: str) -> Dict[str, str]:
        """
        Parse parameters from a reference template, respecting nested
        {{ }} and [[ ]] structures so a value like
        {{date|2020|01|01}} or [[Some|Link]] is not truncated at its
        internal '|'.

        Args:
            template_content: Full template string including {{...}}

        Returns:
            Dictionary of parameter names to values (first occurrence wins,
            except that a later archive.org duplicate is always ignored).
        """
        if not (template_content.startswith('{{') and template_content.endswith('}}')):
            self._logger.info("PARAM_PARSE_SKIPPED | reason=malformed_template_bounds")
            return {}

        inner = template_content[2:-2]

        first_pipe = self._find_top_level_pipe(inner, start=0)
        if first_pipe is None:
            # No parameters at all (e.g. "{{Lien web}}").
            return {}

        params_blob = inner[first_pipe + 1:]
        segments = self._split_top_level(params_blob)

        parameters: Dict[str, str] = {}
        for segment in segments:
            kv = self._PARAM_KV_RE.match(segment)
            if not kv:
                # Positional/unnamed parameter or malformed segment; skip
                # rather than corrupt the map with a bogus key.
                if segment.strip():
                    self._logger.info(f"PARAM_PARSE_SKIPPED_SEGMENT | segment={segment[:80]!r}")
                continue

            key = kv.group('key').strip()
            # `value` already excludes the whitespace right after '='
            # (captured separately as eq_after) and any leading whitespace
            # of the segment; it may still carry TRAILING whitespace that
            # belongs to the boundary with the next '|' (that trailing
            # whitespace is reproduced by _rebuild_template as the next
            # parameter's before_pipe), so it must be stripped here to
            # avoid storing/duplicating it in the semantic value.
            value = kv.group('value').rstrip()
            if not key:
                continue

            if key not in parameters:
                parameters[key] = value
            else:
                if 'web.archive.org' in value or 'archive.org' in value:
                    self._logger.info(f"SKIPPING_DUPLICATE_ARCHIVE_PARAM | key={key} | value={value[:120]}")
                    continue
                self._logger.info(
                    f"KEEPING_FIRST_OCCURRENCE | key={key} | "
                    f"first={parameters[key][:60]} | second={value[:60]}"
                )

        return parameters

    @staticmethod
    def _find_top_level_pipe(text: str, start: int = 0) -> Optional[int]:
        """Find the index of the first '|' not nested inside {{ }} or [[ ]]."""
        depth_curly = 0
        depth_bracket = 0
        i = start
        length = len(text)
        while i < length:
            two = text[i:i + 2]
            if two == '{{':
                depth_curly += 1
                i += 2
                continue
            if two == '}}':
                depth_curly = max(0, depth_curly - 1)
                i += 2
                continue
            if two == '[[':
                depth_bracket += 1
                i += 2
                continue
            if two == ']]':
                depth_bracket = max(0, depth_bracket - 1)
                i += 2
                continue
            if text[i] == '|' and depth_curly == 0 and depth_bracket == 0:
                return i
            i += 1
        return None

    @classmethod
    def _split_top_level(cls, text: str) -> List[str]:
        """
        Split text on '|' characters that aren't nested inside {{ }} or [[ ]].

        NOTE: the '|' separator itself is consumed (not included in either
        the preceding or following segment) — callers that need to
        reconstruct exact original spacing around '|' must read the
        leading whitespace of each returned segment (see _rebuild_template),
        since that whitespace is everything that appeared between the
        '|' and the parameter name in the original text.
        """
        segments: List[str] = []
        depth_curly = 0
        depth_bracket = 0
        current: List[str] = []
        i = 0
        length = len(text)
        while i < length:
            two = text[i:i + 2]
            if two == '{{':
                depth_curly += 1
                current.append(two)
                i += 2
                continue
            if two == '}}':
                depth_curly = max(0, depth_curly - 1)
                current.append(two)
                i += 2
                continue
            if two == '[[':
                depth_bracket += 1
                current.append(two)
                i += 2
                continue
            if two == ']]':
                depth_bracket = max(0, depth_bracket - 1)
                current.append(two)
                i += 2
                continue
            if text[i] == '|' and depth_curly == 0 and depth_bracket == 0:
                segments.append(''.join(current))
                current = []
                i += 1
                continue
            current.append(text[i])
            i += 1
        segments.append(''.join(current))
        return segments

    # ------------------------------------------------------------------
    # Template generation
    # ------------------------------------------------------------------

    def generate_archive_repair_template(
        self,
        original_template: ReferenceTemplate,
        archive_url: str,
        archive_date: str,
        original_url: str,
        assume_patch_deployed: bool = False,
        provider: Optional[str] = None,
        consulted_date: Optional[str] = None,
        archive_title: Optional[str] = None,
    ) -> str:
        """
        Generate a reference template string with archive parameters added
        (archive-url, archive-date, brisé le).

        This method is specifically for DeadLinkAnalyzer to add archive
        parameters to templates when repairing dead links.

        LOCKED BEHAVIOR (per bot policy review — do not re-enable without
        explicit consensus):
        - |site= is NEVER added, modified, or "corrected" here. A human
          contributor's choice of site value (including a bare domain,
          with or without "www.") must be left exactly as written.
        - |consulté le= is NEVER added here. That parameter documents a
          human's own consultation of the source and must not be filled
          in by a bot, even if the bot itself fetched the page.
        - All parameters that are NOT being touched by this repair keep
          their EXACT original formatting (spacing around '|' AND '='),
          reproduced verbatim from original_template.full_match. Newly
          added parameters (archive-url, archive-date, brisé le) use the
          same spacing style as the template's own existing parameters,
          so the result blends in rather than forcing a different style.

        Args:
            original_template: Original parsed template
            archive_url: Archive URL to use
            archive_date: Archive date from provider (YYYYMMDDHHMMSS or YYYY-MM-DD)
            original_url: Original dead URL
            assume_patch_deployed: If True and the template type supports it,
                use the archive URL as the main `url` link.
            provider: Raw archive provider identifier (e.g. 'WaybackMachine',
                'Arquivo.pt'). NOTE: `archive-host` is not a recognized
                parameter of the real Wikipedia {{Lien web}}/{{article}}/
                {{ouvrage}} templates — MediaWiki does not render it, so it
                is never written into the generated wikitext. The provider
                is only resolved/logged here; use
                render_archive_repair_prose() if you need a human-readable
                "via Internet Archive" mention in prose output.
            archive_title: Title extracted from archive metadata. If provided
                and the template is missing a titre parameter, it will be added.

        Returns:
            New template string with archive parameters.

        Raises:
            ValueError: if required inputs are missing/invalid.
        """
        if original_template is None:
            raise ValueError("original_template is required")
        if not archive_url or not archive_url.strip():
            raise ValueError("archive_url must be a non-empty string")
        if not original_url or not original_url.strip():
            raise ValueError("original_url must be a non-empty string")

        archive_url = archive_url.strip()
        original_url = original_url.strip()

        params = dict(original_template.parameters)  # shallow copy; safe, immutable source

        # Add title from archive metadata if template is missing titre parameter
        # This helps repair templates that are missing required parameters
        if archive_title and archive_title.strip() and 'titre' not in params:
            params['titre'] = archive_title.strip()
            self._logger.info(f"ARCHIVE_TITLE_ADDED | template={original_template.template_name} | title={archive_title[:80]}")

        # Check if this template type supports archive parameters at all
        # Normalize template name for comparison to handle case/spacing variations
        normalized_template_name = self._normalize_template_name(original_template.template_name)
        supports_archive_params = normalized_template_name not in self.TEMPLATES_WITHOUT_ARCHIVE_PARAMS

        if not supports_archive_params:
            self._logger.info(f"ARCHIVE_PARAMS_SKIPPED | template={original_template.template_name} | reason=template_does_not_support_archives")

        can_promote_archive = (
            assume_patch_deployed
            and normalized_template_name in self.TEMPLATES_SUPPORTING_ARCHIVE_AS_MAIN_LINK
        )
        params['url'] = archive_url if can_promote_archive else original_url

        # LOCKED: |site= is never touched by archive-repair logic.
        # (Previously this block updated |site= to the archive provider's
        # name when the archive was promoted as the main link. Disabled
        # per policy: bots must not overwrite a contributor's site choice.)

        # Only add archive-url and archive-date if template supports them
        formatted_archive_date = ""
        if supports_archive_params:
            params['archive-url'] = archive_url

            formatted_archive_date = self._format_archive_date(archive_date)
            if formatted_archive_date:
                params['archive-date'] = formatted_archive_date

        # Get current date for brisé le, formatted as French prose
        # (e.g., "12 septembre 2026"). consulté le is never added here
        # (see LOCKED BEHAVIOR above), so this date is only used for
        # brisé le.
        if consulted_date:
            current_date = self._format_date_prose(consulted_date)
        else:
            today = datetime.now(timezone.utc)
            current_date = f"{today.day} {self._FRENCH_MONTHS[today.month]} {today.year}"

        # Only add brisé le if not already present AND template supports this parameter
        # TEMPLATES_SUPPORTING_BRISE_LE includes 'lien web' only (ouvrage does not render brisé le)
        if (normalized_template_name in self.TEMPLATES_SUPPORTING_BRISE_LE
            and 'brisé le' not in params
            and 'dead-url' not in params
            and 'deadurl' not in params
            and 'lien brisé' not in params):
            params['brisé le'] = current_date

        # LOCKED: |consulté le= is never added by archive-repair logic.
        # (Previously this block added a consultation date. Disabled per
        # policy: this parameter is reserved for human contributors who
        # actually consulted the source themselves.)

        if provider:
            # Resolved/logged for traceability only. Deliberately NOT
            # written into `params`: no real Wikipedia reference template
            # has an `archive-host` (or equivalent) parameter, so writing
            # it would produce an unrecognized-parameter artifact that
            # MediaWiki silently ignores in the rendered page.
            resolved_provider = self.PROVIDER_NAMES.get(provider, provider)
            self._logger.info(f"PROVIDER_RESOLVED_NOT_WRITTEN | raw={provider} | resolved={resolved_provider}")

        # Clean up stale "dead" flags now that the link has been repaired,
        # to avoid contradictory metadata (e.g. deadurl=yes alongside a
        # freshly archived, working url).
        for stale_key in ('dead-url', 'deadurl'):
            params.pop(stale_key, None)

        # LOCKED: |site= is never added, corrected, or removed here.
        # (Previously this block auto-filled |site= for templates missing
        # it, and "corrected" existing |site= values including stripping
        # "www.". Both are disabled per policy: a bot must not perform
        # this kind of cosmetic/interpretive edit to a contributor's
        # reference, and www.-stripping is not reliably safe — not every
        # www. domain has a working non-www redirect.)

        # Rebuild template with updated parameters, preserving original
        # order AND original spacing exactly (see _rebuild_template).
        new_template = self._rebuild_template(original_template.template_name, original_template.full_match, params)

        self._logger.info(
            f"GENERATED_ARCHIVE_TEMPLATE | template={original_template.template_name} | "
            f"original_url={original_url} | archive_url={archive_url} | "
            f"archive_date={formatted_archive_date} | assume_patch_deployed={assume_patch_deployed} | "
            f"archive_promoted={can_promote_archive}"
        )

        return new_template

    def _rebuild_template(self, template_name: str, original_full_match: str, params: Dict[str, str]) -> str:
        """
        Rebuild a template string with updated parameters while preserving
        the original parameter order AND EXACT original spacing style —
        on BOTH sides of '|' AND on BOTH sides of '=' AND the original
        template name casing (e.g., "lien web" stays "lien web", never
        changed to "Lien web").

        This method must never perform whitespace "cleanup": if the
        original template was written compact (|url=...|titre=...), the
        rebuilt output stays compact. If the original used spaced pipes
        and/or spaced equals (| titre = Sound | url = ...), the rebuilt
        output keeps that spacing — both for parameters that already
        existed (untouched, byte-for-byte spacing) and for brand-new
        parameters being added by a repair (matched to the template's own
        detected style).

        SAFETY: every emitted parameter is guaranteed to be preceded by a
        literal '|' character and to contain a literal '=' character.
        Both separators are added unconditionally by this method (never
        derived from parsed spacing alone — only the whitespace AROUND
        them is), so a parsing edge case can never cause a separator to
        be silently dropped and parameters/keys/values to run together.

        Args:
            template_name: Name of the template (used for validation, but
                original casing is extracted from original_full_match)
            original_full_match: Original template string (including {{ and }})
                used to recover parameter order, spacing, and original template name casing.
            params: Updated parameter dictionary (key -> value) to emit.

        Returns:
            Rebuilt template string with parameters in original order plus
            any new ones, using spacing consistent with the original
            template's own style, and preserving the original template name casing.
        """
        # Extract original template name with exact casing from original_full_match
        # This ensures we preserve the original casing (e.g., "lien web" stays "lien web")
        original_template_name = None
        if original_full_match and original_full_match.startswith('{{'):
            # Extract the template name between {{ and first | or }}
            template_content = original_full_match[2:]  # Remove {{
            first_pipe_idx = template_content.find('|')
            first_brace_idx = template_content.find('}}')
            
            if first_pipe_idx >= 0 and first_brace_idx >= 0:
                # Both | and }} present, use the first one
                end_idx = min(first_pipe_idx, first_brace_idx)
            elif first_pipe_idx >= 0:
                end_idx = first_pipe_idx
            elif first_brace_idx >= 0:
                end_idx = first_brace_idx
            else:
                end_idx = len(template_content)
            
            original_template_name = template_content[:end_idx].strip()
        
        # Use original template name if found, otherwise fall back to provided template_name
        final_template_name = original_template_name if original_template_name else template_name
        
        template_parts = [f'{{{{{final_template_name}']

        original_param_order: List[str] = []
        # Maps param name -> (whitespace_before_pipe, whitespace_after_pipe),
        # the exact whitespace that appeared on each side of the '|' in
        # the original text (either or both may be '').
        original_pipe_spacing: Dict[str, Tuple[str, str]] = {}
        default_pipe_spacing: Tuple[str, str] = ('', '')

        # Maps param name -> (whitespace_before_equals, whitespace_after_equals),
        # the exact whitespace that appeared on each side of the '=' in
        # the original text (either or both may be ''). This is what makes
        # "titre = Sound" survive as "titre = Sound" (not "titre=Sound")
        # even when the template is only partially modified.
        original_eq_spacing: Dict[str, Tuple[str, str]] = {}
        default_eq_spacing: Tuple[str, str] = ('', '')

        if original_full_match and original_full_match.startswith('{{') and original_full_match.endswith('}}'):
            template_content = original_full_match[2:-2]  # Remove {{ and }}
            segments = self._split_top_level(template_content)
            # IMPORTANT: _split_top_level consumes the '|' separator itself
            # and does not redistribute it to either side. In real wikitext
            # such as "{{Lien web |langue=en |titre=...}}", the whitespace
            # that visually sits "after the |" (e.g. "web |langue") is
            # actually trailing whitespace of the PRECEDING segment
            # ("Lien web ") — NOT leading whitespace of the following
            # segment ("langue=en "). So the correct prefix for parameter
            # N is the trailing whitespace of segment N-1 (segments[i-1]),
            # not the leading whitespace of segment N.
            for i in range(1, len(segments)):  # Skip template name (index 0)
                segment = segments[i]
                kv = self._PARAM_KV_RE.match(segment)
                if kv:
                    param_name = kv.group('key').strip()
                    original_param_order.append(param_name)

                    # --- Spacing around '|' ---
                    # Full separator = trailing whitespace of the PRECEDING
                    # segment (whitespace before the '|', e.g. "ouvrage ")
                    # PLUS leading whitespace of THIS segment (whitespace
                    # after the '|', e.g. " auteur"). Both sides are
                    # captured independently since wikitext authors may
                    # use either or both styles ("|x=", "| x=", "x= |", etc.).
                    preceding_segment = segments[i - 1]
                    trail_match = re.search(r'[ \t]*$', preceding_segment)
                    before_pipe = trail_match.group(0) if trail_match else ''
                    lead_match = re.match(r'^[ \t]*', segment)
                    after_pipe = lead_match.group(0) if lead_match else ''
                    original_pipe_spacing[param_name] = (before_pipe, after_pipe)

                    # --- Spacing around '=' ---
                    # Captured directly from the parsed key=value match:
                    # eq_before is the whitespace between the key and '=',
                    # eq_after is the whitespace between '=' and the value.
                    # E.g. for "titre = Sound", eq_before=' ', eq_after=' '.
                    # For "titre=Sound", both are ''.
                    eq_before = kv.group('eq_before')
                    eq_after = kv.group('eq_after')
                    original_eq_spacing[param_name] = (eq_before, eq_after)

            if original_param_order:
                # Use the last existing parameter's own spacing as the
                # style to apply to brand-new parameters, since it best
                # reflects this specific template's actual formatting.
                last_param = original_param_order[-1]
                default_pipe_spacing = original_pipe_spacing.get(last_param, ('', ''))
                default_eq_spacing = original_eq_spacing.get(last_param, ('', ''))

        # Re-emit existing parameters in their original order, with their
        # exact original spacing on BOTH sides of the '|' AND BOTH sides
        # of the '=' — untouched. E.g. "ouvrage | auteur = Dupont | éditeur=..."
        # has whitespace both before and after each '|' and around the
        # '=' of 'auteur'; "Lien web |langue=en" has whitespace only before
        # the '|'; "url=...|site=..." has none at all anywhere. The '|'
        # and '=' themselves are always added literally here, independent
        # of whatever the captured spacing contains, so neither separator
        # can ever be silently dropped.
        emitted = set()
        for param in original_param_order:
            if param in params:
                before_pipe, after_pipe = original_pipe_spacing.get(param, default_pipe_spacing)
                eq_before, eq_after = original_eq_spacing.get(param, default_eq_spacing)
                template_parts.append(
                    before_pipe + '|' + after_pipe
                    + param + eq_before + '=' + eq_after + params[param]
                )
                emitted.add(param)

        # Brand-new parameters (e.g. archive-url, archive-date, brisé le)
        # not present in the original template use the detected default
        # spacing style (for both '|' and '='), so they visually match the
        # template's own style rather than forcing compact or spaced
        # formatting onto it.
        for param, value in params.items():
            if param not in emitted:
                before_pipe, after_pipe = default_pipe_spacing
                eq_before, eq_after = default_eq_spacing
                template_parts.append(
                    before_pipe + '|' + after_pipe
                    + param + eq_before + '=' + eq_after + value
                )

        template_parts.append('}}')
        return ''.join(template_parts)

    @staticmethod
    def _safe_extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc
        except (ValueError, AttributeError):
            return ""

    def _correct_site_domain(self, existing_site: str) -> Optional[str]:
        """
        Correct an existing |site= value by extracting the domain and
        mapping it to a human-readable name.

        NOTE: this method is retained for use by generate_enriched_template
        (the ReferenceEnricherAnalyzer path), NOT by archive-repair logic
        (generate_archive_repair_template never calls this — see LOCKED
        BEHAVIOR at top of file).

        Handles:
        - Full URLs (extracts domain)
        - Domain -> human-readable name mapping via YAML

        IMPORTANT:
        - Only returns a value if a mapping is found (wikilink format).
          Never returns a bare domain.
        - NEVER strips "www." from the domain: not every "www." domain
          has a working non-www redirect, and doing so is a cosmetic
          change to what the contributor wrote. "www." is preserved
          verbatim in both the lookup and any returned value.

        Args:
            existing_site: Current site parameter value (may be a URL,
                a bare domain, or an already human-readable name).

        Returns:
            Corrected site value (wikilink format if mapped), or None if
            no correction needed/possible.
        """
        if not existing_site:
            return None

        # If existing_site is already an internal link [[...]], never correct it
        # This prevents mistakenly treating wikilinks like [[Radio-Canada.ca]] as domains needing correction
        if existing_site.strip().startswith('[['):
            return None

        # Only attempt correction if this looks like a domain or URL.
        if not ('://' in existing_site or existing_site.strip().startswith('www.') or '.' in existing_site.strip()):
            return None

        # Extract domain from URL, or use as-is if it's already a domain.
        # "www." (if present) is always preserved — never stripped.
        if '://' in existing_site:
            parsed = urlparse(existing_site)
            domain = parsed.netloc
        else:
            domain = existing_site.strip()

        # Try to get the mapped site name for the domain, www. preserved.
        corrected_site = self._resolve_site_display_name(domain)

        # Only return a value if we got an actual wikilink mapping.
        # Never fall back to stripping "www." as a "correction" — that is
        # not this method's job and is explicitly disallowed.
        if corrected_site and corrected_site.strip().startswith('[['):
            return corrected_site

        return None

    def _resolve_site_display_name(self, domain: str, include_archive_domains: bool = False) -> str:
        """
        Best-effort lookup of a human-readable site name for |site=,
        given a bare domain (e.g. "music.apple.com").

        Looks up domain_to_site_name from YAML first with the domain exactly
        as given (www. preserved), then with a "www." prefix stripped ONLY
        for the purpose of matching an entry that was itself defined
        without www. in the YAML (covers both "www.example.com" and
        "example.com" entries interchangeably in the *mapping*, without
        ever altering what gets returned when nothing matches).

        IMPORTANT: the final fallback (nothing matched in the YAML mapping)
        returns the domain completely UNCHANGED, "www." included. This
        method must never strip "www." from a value it doesn't have an
        explicit, curated replacement for.

        The YAML mapping contains wiki link format [[Site Name]] which is preserved.

        If the input is not a recognizable bare domain (e.g. already a
        human-readable name, a wikilink, or a literal name that happens
        to contain a dot like "Radio-Canada.ca"), it is returned unchanged.

        Args:
            domain: Domain to resolve
            include_archive_domains: If True, also check ARCHIVE_DOMAIN_TO_SITE_NAME
                mapping (used only for dead link repair context). Default False to avoid
                contaminating normal site resolution with archive-specific mappings.
        """
        if not domain:
            return domain

        # Check if this is already a wikilink or human-readable name.
        if '[' in domain and ']' in domain:
            return domain

        # Strict domain validation: only alphanumeric/hyphen/dot chars,
        # at least one dot, TLD of 2+ chars. Prevents mis-detecting a
        # literal name written into |site= (e.g. "Radio-Canada.ca") as
        # a bare domain to re-map.
        if not self._DOMAIN_PATTERN.match(domain.strip()):
            return domain

        # Normalize domain to lowercase for consistent matching
        # (YAML entries are lowercase). This is a comparison-only
        # normalization; the original "domain" (with its original case
        # and its "www." if any) is what gets returned on no-match.
        domain_lower = domain.lower()

        # Check archive provider mapping ONLY if explicitly requested (dead link repair context)
        # This prevents archive-specific mappings from contaminating normal site resolution
        if include_archive_domains:
            archive_mapped = self.ARCHIVE_DOMAIN_TO_SITE_NAME.get(domain_lower)
            if archive_mapped:
                return archive_mapped
            if domain_lower.startswith('www.'):
                domain_without_www = domain_lower[len('www.'):]
                archive_mapped = self.ARCHIVE_DOMAIN_TO_SITE_NAME.get(domain_without_www)
                if archive_mapped:
                    return archive_mapped

        # Load mapping from YAML (TTL-cached at class level for efficiency).
        if not ReferenceTemplateHelper.DOMAIN_TO_SITE_NAME:
            ReferenceTemplateHelper.DOMAIN_TO_SITE_NAME = self._load_domain_to_site_name_mapping()

        # Try exact match first from YAML.
        mapped = ReferenceTemplateHelper.DOMAIN_TO_SITE_NAME.get(domain_lower)
        if mapped:
            if isinstance(mapped, list):
                inner = mapped[0]
                if isinstance(inner, list) and len(inner) > 0:
                    return f"[[{inner[0]}]]"
                return str(inner) if inner else domain
            return str(mapped)

        # Try matching a YAML entry that was defined without "www.",
        # purely for lookup purposes — does not affect what is returned
        # below if nothing matches.
        if domain_lower.startswith('www.'):
            domain_without_www = domain_lower[len('www.'):]
            mapped = ReferenceTemplateHelper.DOMAIN_TO_SITE_NAME.get(domain_without_www)
            if mapped:
                if isinstance(mapped, list):
                    inner = mapped[0]
                    if isinstance(inner, list) and len(inner) > 0:
                        return f"[[{inner[0]}]]"
                    return str(inner) if inner else domain_without_www
                return str(mapped)

        # Fallback: return the domain completely unchanged, "www." included.
        # Never strip "www." here — not every www. domain redirects
        # correctly without it, and this must remain a purely additive
        # (mapping-only) operation.
        return domain

    def _format_archive_date(self, archive_date: Optional[str]) -> str:
        """
        Format archive date for the reference template.

        Archive providers typically return dates as YYYYMMDDHHMMSS.
        This converts to YYYY-MM-DD; already-formatted or unrecognized
        inputs are handled gracefully instead of raising.

        Args:
            archive_date: Archive date string, or None/empty.

        Returns:
            Formatted date (YYYY-MM-DD), or "" if unavailable.
        """
        if not archive_date:
            return ""

        archive_date = archive_date.strip()
        if not archive_date:
            return ""

        # Already YYYY-MM-DD.
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', archive_date):
            return archive_date

        # YYYYMMDD[HHMMSS] numeric form.
        digits = re.sub(r'\D', '', archive_date)
        if len(digits) >= 8:
            year, month, day = digits[0:4], digits[4:6], digits[6:8]
            if year.isdigit() and 1 <= int(month or 0) <= 12 and 1 <= int(day or 0) <= 31:
                return f"{year}-{month}-{day}"

        self._logger.info(f"ARCHIVE_DATE_FORMAT_UNRECOGNIZED | raw={archive_date!r}")
        return archive_date

    def generate_enriched_template(
        self,
        original_template: ReferenceTemplate,
        site_value: Optional[str] = None,
        consulte_le_value: Optional[str] = None,
    ) -> str:
        """
        Generate a reference template string with enrichment parameters
        (site and/or consulté le) added, preserving all existing parameters.

        This method is specifically for ReferenceEnricherAnalyzer to add
        missing site and consulté le parameters to healthy reference
        templates — it is a DIFFERENT code path from
        generate_archive_repair_template (used by DeadLinkAnalyzer), and
        the LOCKED BEHAVIOR restrictions on |site=/|consulté le= documented
        there do NOT apply here, since this method is only invoked when
        the caller (a human-reviewed enrichment workflow) explicitly
        supplies a site_value/consulte_le_value to add.

        Args:
            original_template: Original parsed template
            site_value: Site value to add if missing (None to skip)
            consulte_le_value: Consulté le value to add if missing (None to skip)

        Returns:
            New template string with enrichment parameters added.
            Returns original template unchanged if no parameters need to be added.

        Raises:
            ValueError: if original_template is None.
        """
        if original_template is None:
            raise ValueError("original_template is required")

        # Check if any enrichment is needed using parameter variants
        # Check all site parameter variants for consistency
        current_site = self._get_param_any(original_template.parameters, self.SITE_PARAMETER_VARIANTS)

        # Check 'consulté le' variants including case variations
        current_consulte_le = original_template.parameters.get('consulté le') or original_template.parameters.get('Consulté le') or original_template.parameters.get('consulte le')

        # If current_site is already an internal link [[...]], never correct it
        # This prevents mistakenly treating wikilinks like [[Radio-Canada.ca]] as domains needing correction
        if current_site and current_site.strip().startswith('[['):
            site_needs_correction = False
        else:
            # Check if site needs domain mapping correction (broader than just www. prefix)
            site_needs_correction = bool(current_site) and ('://' in current_site or current_site.strip().startswith('www.') or '.' in current_site.strip())

        # If both parameters are already present and non-empty, no enrichment needed
        # unless site needs domain mapping correction
        if current_site and current_consulte_le and not site_needs_correction:
            self._logger.info(f"ENRICHMENT_NOT_NEEDED | template={original_template.template_name} | reason=both_params_present")
            return original_template.full_match

        # If no values to add and no site correction needed, no enrichment needed
        if (not site_value or not site_value.strip()) and (not consulte_le_value or not consulte_le_value.strip()) and not site_needs_correction:
            self._logger.info(f"ENRICHMENT_NOT_NEEDED | template={original_template.template_name} | reason=no_values_to_add")
            return original_template.full_match

        params = dict(original_template.parameters)  # shallow copy; safe, immutable source

        # Correct domain mapping in existing site value if present.
        # (www. is never stripped — see _correct_site_domain.)
        if site_needs_correction:
            corrected_site = self._correct_site_domain(current_site)
            if corrected_site:
                self._logger.info(
                    f"ENRICHMENT_SITE_CORRECTION | template={original_template.template_name} | "
                    f"existing_site={current_site} | new_site={corrected_site}"
                )
                params['site'] = corrected_site

        # Add site parameter if missing and value provided
        if site_value and site_value.strip() and not current_site:
            # Check if template supports site parameter
            # Normalize template name for comparison to handle case/spacing variations
            normalized_template_name = self._normalize_template_name(original_template.template_name)
            if normalized_template_name not in self.TEMPLATES_WITHOUT_SITE_PARAM:
                # Skip if manually curated parameters are present (série, collection, éditeur)
                # Policy: FEW ENRICHMENTS + ZERO UNRELATED CHANGES - conservative blocking
                # Check both lowercase and capitalized variants
                série = params.get('série') or params.get('Série')
                collection = params.get('collection') or params.get('Collection')
                editeur = params.get('éditeur') or params.get('Éditeur')
                if série or collection or editeur:
                    self._logger.info(f"ENRICHMENT_SITE_SKIPPED | template={original_template.template_name} | reason=manually_curated_params_present")
                else:
                    # Check if titre already contains the site name to avoid duplication
                    # Normalize for comparison (case-insensitive, remove brackets and www)
                    site_clean = site_value.strip().lower().replace('www.', '').replace('[[', '').replace(']]', '')
                    titre = params.get('titre')
                    if titre:
                        titre_clean = titre.strip().lower().replace('www.', '').replace('[[', '').replace(']]', '')
                        if site_clean == titre_clean or site_clean in titre_clean or titre_clean in site_clean:
                            self._logger.info(f"ENRICHMENT_SITE_SKIPPED | template={original_template.template_name} | reason=titre_contains_site_name")
                        else:
                            params['site'] = site_value.strip()
                            self._logger.info(f"ENRICHMENT_SITE_ADDED | template={original_template.template_name} | site={site_value}")
                    else:
                        params['site'] = site_value.strip()
                        self._logger.info(f"ENRICHMENT_SITE_ADDED | template={original_template.template_name} | site={site_value}")
            else:
                self._logger.info(f"ENRICHMENT_SITE_SKIPPED | template={original_template.template_name} | reason=template_without_site_param")

        # Add consulté le parameter if missing and value provided
        # DEFENSIVE: Only add consulté le if site is also being added or corrected
        # This enforces the documented rule: consulté le is added ONLY when site is also added or upgraded
        # Exception: if site_value is None (caller provides no site), consulté le can be added alone
        # This allows ReferenceEnricherAnalyzer to add consulté le independently when appropriate
        if consulte_le_value and consulte_le_value.strip() and not current_consulte_le:
            # Check if site was added or corrected in this enrichment
            site_was_added_or_corrected = ('site' in params and params['site'] != current_site)
            # Allow consulté le if site was modified OR if no site value was provided at all
            if site_was_added_or_corrected or not site_value:
                # Check if template supports consulté le parameter
                # Normalize template name for comparison to handle case/spacing variations
                normalized_template_name = self._normalize_template_name(original_template.template_name)
                if normalized_template_name in self.TEMPLATES_SUPPORTING_CONSULTE_LE:
                    params['consulté le'] = consulte_le_value.strip()
                    self._logger.info(f"ENRICHMENT_CONSULTE_LE_ADDED | template={original_template.template_name} | consulte_le={consulte_le_value}")
                else:
                    self._logger.info(f"ENRICHMENT_CONSULTE_LE_SKIPPED | template={original_template.template_name} | reason=template_not_in_whitelist")
            else:
                self._logger.info(f"ENRICHMENT_CONSULTE_LE_SKIPPED | template={original_template.template_name} | reason=site_value_provided_but_not_added_or_corrected")

        # Rebuild template with updated parameters, preserving original
        # order and spacing (see _rebuild_template).
        new_template = self._rebuild_template(original_template.template_name, original_template.full_match, params)

        self._logger.info(
            f"GENERATED_ENRICHED_TEMPLATE | template={original_template.template_name} | "
            f"site_added={site_value is not None and not current_site} | "
            f"consulte_le_added={consulte_le_value is not None and not current_consulte_le}"
        )

        return new_template

    def add_brise_le_parameter(
        self,
        original_template: ReferenceTemplate,
        brise_le_date: str,
    ) -> str:
        """
        Add a brisé le parameter to an existing template, preserving all other parameters.

        This method is specifically for DeadLinkAnalyzer to mark a dead link as broken
        when a valid archive already exists.

        Args:
            original_template: Original parsed template
            brise_le_date: Date string in YYYY-MM-DD format for the brisé le parameter

        Returns:
            New template string with brisé le parameter added.
            Returns original template unchanged if brisé le is already present.

        Raises:
            ValueError: if original_template is None.
        """
        if original_template is None:
            raise ValueError("original_template is required")

        # Check if brisé le is already present (check all variants)
        brise_le_variants = ('brisé le', 'brise le', 'dead-url', 'deadurl', 'lien brisé')
        has_brise_le = False
        for variant in brise_le_variants:
            if variant in original_template.parameters:
                has_brise_le = True
                self._logger.info(f"BRISE_LE_ALREADY_PRESENT | template={original_template.template_name} | variant={variant}")
                break

        if has_brise_le:
            return original_template.full_match

        # Check if template supports brisé le parameter (explicit whitelist,
        # not inferred from TEMPLATES_WITHOUT_ARCHIVE_PARAMS: a template can
        # lack archivable web params yet still not belong on this whitelist,
        # e.g. 'article' is not documented with |brisé le=).
        normalized_template_name = self._normalize_template_name(original_template.template_name)
        if normalized_template_name not in self.TEMPLATES_SUPPORTING_BRISE_LE:
            self._logger.info(f"BRISE_LE_SKIPPED | template={original_template.template_name} | reason=template_does_not_support_brise_le")
            return original_template.full_match

        params = dict(original_template.parameters)  # shallow copy; safe, immutable source

        # Add brisé le parameter
        params['brisé le'] = brise_le_date
        self._logger.info(f"BRISE_LE_ADDED | template={original_template.template_name} | brise_le={brise_le_date}")

        # Rebuild template with brisé le parameter added, preserving
        # original order and spacing (see _rebuild_template).
        new_template = self._rebuild_template(original_template.template_name, original_template.full_match, params)

        self._logger.info(
            f"GENERATED_BRISE_LE_TEMPLATE | template={original_template.template_name} | "
            f"brise_le={brise_le_date}"
        )

        return new_template

    # ------------------------------------------------------------------
    # Human-readable rendering
    # ------------------------------------------------------------------

    def render_archive_repair_prose(
        self,
        original_template: ReferenceTemplate,
        archive_url: str,
        archive_date: str,
        original_url: str,
        provider: Optional[str] = None,
        consulted_date: Optional[str] = None,
        assume_patch_deployed: bool = False,
    ) -> str:
        """
        Render a human-readable French citation sentence for a repaired
        dead link, e.g.:

        Titre, « Texte du lien » [archive du 1er janvier 2020],
        sur original-site.com via Internet Archive, 5 janvier 2015

        - The title (if present) is quoted with French guillemets « ».
        - The link text points at the archive URL when `assume_patch_deployed`
          is True and the template supports promoting the archive as the
          main link; otherwise the link text points at the original URL and
          the archive is only referenced via "[archive du ...]".
        - "archive du <date>" always uses the *archive* date, never the
          publication date.
        - "sur <site> via <provider>" uses the resolved provider name.
        - Publication date (`date`/`année`) is appended when available.
          Consultation date is deliberately NOT appended here (see
          DISABLED note below) — this is prose output for display/logging,
          not wikitext, but is kept consistent with the same policy.

        Args:
            original_template: Parsed template (for titre/date/site/etc.)
            archive_url: Archive URL
            archive_date: Archive date from provider (YYYYMMDDHHMMSS or YYYY-MM-DD)
            original_url: Original dead URL
            provider: Raw archive provider identifier (e.g. 'WaybackMachine')
            consulted_date: Consultation date (YYYY-MM-DD); currently unused
                (kept in the signature for backward compatibility).
            assume_patch_deployed: If True and the template supports it, the
                link text points to the archive URL instead of the original.

        Returns:
            A single formatted prose sentence (str).

        Raises:
            ValueError: if required inputs are missing/invalid.
        """
        if original_template is None:
            raise ValueError("original_template is required")
        if not archive_url or not archive_url.strip():
            raise ValueError("archive_url must be a non-empty string")
        if not original_url or not original_url.strip():
            raise ValueError("original_url must be a non-empty string")

        archive_url = archive_url.strip()
        original_url = original_url.strip()
        params = original_template.parameters

        # Normalize template name for comparison to handle case/spacing variations
        normalized_template_name = self._normalize_template_name(original_template.template_name)
        can_promote_archive = (
            assume_patch_deployed
            and normalized_template_name in self.TEMPLATES_SUPPORTING_ARCHIVE_AS_MAIN_LINK
        )
        link_target = archive_url if can_promote_archive else original_url

        titre = params.get('titre', '').strip()
        link_label = titre if titre else link_target

        # First segment: "Titre, « [lien](cible) »" or just "« [lien](cible) »"
        if titre:
            head = f'{titre}, « [{link_label}]({link_target}) »'
        else:
            head = f'« [{link_label}]({link_target}) »'

        # Archive marker glues directly onto the head with a space, no comma
        # before it: '... » [archive du 1er janvier 2020], sur ...'
        formatted_archive_date = self._format_archive_date(archive_date)
        archive_date_prose = self._format_date_prose(formatted_archive_date)
        archive_marker = f'[archive du {archive_date_prose}]' if archive_date_prose else '[archive du date inconnue]'
        head = f'{head} {archive_marker}'

        trailing: List[str] = []

        # Extract site name, handling cases where site parameter contains a URL instead of a name
        raw_site = params.get('site') or params.get('website')

        # Check if site parameter already contains a wikilink format like [www.multiple.be]
        # If so, don't add "sur <site>" in trailing section to avoid duplication
        site_is_wikilink = False
        if raw_site and ('[' in raw_site and ']' in raw_site):
            site_is_wikilink = True
            self._logger.debug(f"Site parameter '{raw_site}' already contains wikilink format, skipping 'sur <site>'")

        if raw_site and ('://' in raw_site or raw_site.startswith('www.')):
            site = self._safe_extract_domain(raw_site)
        else:
            site = raw_site or self._safe_extract_domain(original_url)
        resolved_provider = self.PROVIDER_NAMES.get(provider, provider) if provider else None

        # Avoid duplication: if link_label already contains the site name (domain),
        # don't add "sur <site>" in trailing section
        # This prevents: "[www.multiple.be](...), sur multiple.be"
        site_in_link_label = False
        if not titre and site and not site_is_wikilink:  # Only check when titre is empty and site is not a wikilink
            # Check if the site name appears in the link label (case-insensitive)
            site_lower = site.lower().replace('www.', '')
            link_label_lower = link_label.lower().replace('www.', '').replace('https://', '').replace('http://', '')
            if site_lower in link_label_lower or link_label_lower in site_lower:
                site_in_link_label = True
                self._logger.debug(f"Site '{site}' already present in link label '{link_label}', skipping 'sur {site}'")

        if site and resolved_provider and not site_in_link_label and not site_is_wikilink:
            trailing.append(f'sur {site} via {resolved_provider}')
        elif site and not site_in_link_label and not site_is_wikilink:
            trailing.append(f'sur {site}')
        elif resolved_provider:
            trailing.append(f'via {resolved_provider}')

        pub_date_raw = params.get('date') or params.get('année') or params.get('year')
        pub_date_prose = self._format_date_prose(self._format_archive_date(pub_date_raw)) if pub_date_raw else None
        if pub_date_prose:
            trailing.append(pub_date_prose)

        # DISABLED: Auto-add consulté le date to prose output.
        # This is intentionally never added — consultation date is
        # reserved for human contributors, consistent with the wikitext
        # generation policy in generate_archive_repair_template.
        # if not consulted_date:
        #     consulted_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        # consulted_prose = self._format_date_prose(consulted_date)
        # if consulted_prose:
        #     trailing.append(f'(consulté le {consulted_prose})')

        if not trailing:
            return head
        return head + ', ' + ', '.join(trailing)

    def _format_date_prose(self, iso_date: Optional[str]) -> str:
        """
        Convert a YYYY-MM-DD date into French prose form, e.g.
        '2020-01-01' -> '1er janvier 2020', '2020-01-05' -> '5 janvier 2020'.

        Falls back to returning the input unchanged if it isn't a clean
        YYYY-MM-DD string (e.g. year-only dates like '2015').
        """
        if not iso_date:
            return ""

        match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', iso_date.strip())
        if not match:
            # Year-only or unparseable: return as-is (still useful prose).
            return iso_date.strip()

        year, month, day = match.groups()
        month_idx = int(month)
        if not (1 <= month_idx <= 12):
            return iso_date.strip()

        day_int = int(day)
        day_str = '1er' if day_int == 1 else str(day_int)
        month_name = self._FRENCH_MONTHS[month_idx]

        return f'{day_str} {month_name} {year}'

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def should_use_archive_template(self, content: str, url: str, position: int) -> bool:
        """
        Determine if archive template format should be used, i.e. whether
        the URL at `position` is part of a recognized reference template.

        Requires is_supported=True: a template whose name is recognized as
        present but not in KNOWN_TEMPLATE_NAMES (is_supported=False) must
        not make this return True, so this aligns with DeadLinkAnalyzer's
        own explicit is_supported check on the same underlying data.
        """
        template = self.find_reference_template(content, url, position)
        return template is not None and template.is_supported
"""
Tracking Parameter Remover - Removes tracking URL query parameters from external URLs.

This module provides functionality to clean URLs by removing common tracking parameters
that are used for analytics and marketing purposes but are not needed for the actual
functionality of the URL.
"""

import re
import urllib.parse
import logging
from typing import Optional


logger = logging.getLogger(__name__)

# Known tracking parameters from various platforms
KNOWN_TRACKER_PARAMS = [
    'utm_.+',  # Universal Tracking Module (Google Analytics, etc.)
    'fbclid',  # Facebook Click Identifier
    'gad_.+',  # Google Ads
    'gclid',  # Google Click Identifier
    '[gw]braid',  # Google Click Identifier for AdWords
    'li_fat_id',  # LinkedIn First-Party Attribution
    'mc_.+',  # Mailchimp campaign parameters
    'pk_.+',  # Matomo / Piwik analytics
    'msclkid',  # Microsoft Click Identifier
    'epik',  # Pinterest tracking
    'scid',  # Snapchat tracking
    'ttclid',  # TikTok tracking
    'twclid',  # Twitter / X tracking
    'vero_.+',  # Vero tracking
    'wprov',  # Wikimedia / MediaWiki provenance
    '_openstat',  # Yandex tracking
    'yclid',  # Yandex Click Identifier
    'si',  # YouTube, Spotify source identifier
]

# Compiled regex for efficient matching
KNOWN_TRACKER_REGEX = re.compile(rf'({"|".join(KNOWN_TRACKER_PARAMS)})')


class TrackingParamRemover:
    """
    Service to remove tracking parameters from URLs.
    
    This class provides methods to clean URLs by removing tracking parameters
    while preserving the functionality of the URL.
    """

    def __init__(self):
        """Initialize tracking parameter remover."""
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def remove_tracking_params(self, url: str) -> str:
        """
        Remove tracking query parameters from a URL if they are present.

        Args:
            url: The URL to clean

        Returns:
            URL with tracking parameters removed, or original URL if no tracking
            parameters were found
        """
        try:
            parsed_url = urllib.parse.urlparse(url)
            
            # If no query parameters, return original URL
            if not parsed_url.query:
                return url
            
            # Filter out tracking parameters
            filtered_params = []
            tracker_present = False
            
            for k, v in urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True):
                if KNOWN_TRACKER_REGEX.fullmatch(k):
                    tracker_present = True
                    self._logger.debug(f"Removed tracking parameter: {k}")
                else:
                    filtered_params.append((k, v))
            
            # Return original URL if no tracker parameters were present
            if not tracker_present:
                return url
            
            # Rebuild URL with filtered parameters
            new_query = urllib.parse.urlencode(filtered_params)
            new_url = urllib.parse.urlunparse(parsed_url._replace(query=new_query))
            
            self._logger.info(f"TRACKING_PARAMS_REMOVED | original={url} | cleaned={new_url}")
            return new_url
            
        except Exception as e:
            self._logger.error(f"Error removing tracking params from {url}: {e}")
            # Return original URL on error to avoid breaking functionality
            return url

    def has_tracking_params(self, url: str) -> bool:
        """
        Check if a URL contains tracking parameters.

        Args:
            url: The URL to check

        Returns:
            True if tracking parameters are present, False otherwise
        """
        try:
            parsed_url = urllib.parse.urlparse(url)
            
            if not parsed_url.query:
                return False
            
            for k, _ in urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True):
                if KNOWN_TRACKER_REGEX.fullmatch(k):
                    return True
            
            return False
            
        except Exception as e:
            self._logger.error(f"Error checking tracking params in {url}: {e}")
            return False

    def get_removed_params(self, url: str) -> list:
        """
        Get list of tracking parameters that would be removed from a URL.

        Args:
            url: The URL to analyze

        Returns:
            List of parameter names that would be removed
        """
        try:
            parsed_url = urllib.parse.urlparse(url)
            
            if not parsed_url.query:
                return []
            
            removed_params = []
            for k, _ in urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True):
                if KNOWN_TRACKER_REGEX.fullmatch(k):
                    removed_params.append(k)
            
            return removed_params
            
        except Exception as e:
            self._logger.error(f"Error getting removed params from {url}: {e}")
            return []


# Singleton instance for easy import
tracking_param_remover = TrackingParamRemover()

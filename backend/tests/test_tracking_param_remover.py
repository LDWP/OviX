"""
Test script for tracking parameter removal functionality.
"""

import sys
import os

# Add the backend src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'src'))

from wikipedia_maintenance.utils.tracking_param_remover import TrackingParamRemover

def test_tracking_param_remover():
    """Test the tracking parameter removal functionality."""
    remover = TrackingParamRemover()
    
    # Test cases
    test_cases = [
        # URL with UTM parameters
        ("https://example.com?utm_source=newsletter&utm_medium=email&utm_campaign=spring_sale", 
         "https://example.com"),
        
        # URL with Facebook tracking
        ("https://example.com?fbclid=test123", 
         "https://example.com"),
        
        # URL with Google tracking
        ("https://example.com?gclid=test456", 
         "https://example.com"),
        
        # URL with multiple tracking parameters mixed with regular parameters
        ("https://example.com?utm_source=test&id=123&fbclid=test&category=tech", 
         "https://example.com?id=123&category=tech"),
        
        # URL with no tracking parameters (should remain unchanged)
        ("https://example.com?id=123&category=tech", 
         "https://example.com?id=123&category=tech"),
        
        # URL with no query parameters (should remain unchanged)
        ("https://example.com", 
         "https://example.com"),
        
        # URL with only tracking parameters
        ("https://example.com?utm_source=test&fbclid=test2", 
         "https://example.com"),
        
        # Complex URL with multiple tracking parameters
        ("https://example.com/path?utm_source=test&utm_medium=email&gclid=test123&regular_param=value", 
         "https://example.com/path?regular_param=value"),
    ]
    
    print("Testing TrackingParamRemover...")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for original, expected in test_cases:
        result = remover.remove_tracking_params(original)
        if result == expected:
            print(f"PASS: {original[:60]}... -> {result[:60]}...")
            passed += 1
        else:
            print(f"FAIL: {original[:60]}...")
            print(f"  Expected: {expected}")
            print(f"  Got:      {result}")
            failed += 1
    
    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    
    # Test helper methods
    print("\nTesting helper methods...")
    print("=" * 80)
    
    # Test has_tracking_params
    url_with_tracking = "https://example.com?utm_source=test"
    url_without_tracking = "https://example.com?id=123"
    
    print(f"has_tracking_params('{url_with_tracking}'): {remover.has_tracking_params(url_with_tracking)}")
    print(f"has_tracking_params('{url_without_tracking}'): {remover.has_tracking_params(url_without_tracking)}")
    
    # Test get_removed_params
    removed = remover.get_removed_params("https://example.com?utm_source=test&fbclid=test2&id=123")
    print(f"get_removed_params('https://example.com?utm_source=test&fbclid=test2&id=123'): {removed}")
    
    print("=" * 80)
    
    return failed == 0

if __name__ == "__main__":
    success = test_tracking_param_remover()
    sys.exit(0 if success else 1)

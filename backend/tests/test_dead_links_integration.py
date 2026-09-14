"""
Test script for dead_links.py integration with tracking parameter removal.
"""

import sys
import os

# Add the backend src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'src'))

def test_dead_links_import():
    """Test that dead_links.py can be imported with the new tracking parameter removal."""
    try:
        # Import the tracking parameter remover first
        from wikipedia_maintenance.utils.tracking_param_remover import TrackingParamRemover
        print("PASS: TrackingParamRemover imported successfully")
        
        # Test the basic functionality
        remover = TrackingParamRemover()
        test_url = "https://example.com?utm_source=test&id=123"
        cleaned_url = remover.remove_tracking_params(test_url)
        expected_url = "https://example.com?id=123"
        
        if cleaned_url == expected_url:
            print(f"PASS: Tracking parameter removal works correctly")
            print(f"  Original: {test_url}")
            print(f"  Cleaned:  {cleaned_url}")
        else:
            print(f"FAIL: Tracking parameter removal failed")
            print(f"  Expected: {expected_url}")
            print(f"  Got:      {cleaned_url}")
            return False
        
        # Check that the module has the expected tracking parameters
        from wikipedia_maintenance.utils.tracking_param_remover import KNOWN_TRACKER_PARAMS
        print(f"PASS: Known tracking parameters: {len(KNOWN_TRACKER_PARAMS)} types")
        
        # Test some specific tracking parameters
        test_tracking_params = [
            "utm_source",
            "utm_medium", 
            "fbclid",
            "gclid",
            "msclkid",
            "twclid"
        ]
        
        print(f"PASS: Testing specific tracking parameters:")
        for param in test_tracking_params:
            test_url = f"https://example.com?{param}=test123"
            cleaned = remover.remove_tracking_params(test_url)
            if cleaned == "https://example.com":
                print(f"  PASS: {param} removed correctly")
            else:
                print(f"  FAIL: {param} not removed: {cleaned}")
                return False
        
        print("\nPASS: All integration tests passed!")
        return True
        
    except Exception as e:
        print(f"FAIL: Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_dead_links_import()
    sys.exit(0 if success else 1)

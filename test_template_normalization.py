"""
Test script for template name normalization and case preservation fixes.

Tests:
1. Template name normalization handles MediaWiki variations correctly
2. Case preservation in template reconstruction
3. Validator prevents unnecessary case changes
4. No regression in existing functionality
"""

import sys
import os

# Add the backend/src to the path
backend_src = os.path.join(os.path.dirname(__file__), 'backend', 'src')
sys.path.insert(0, backend_src)

from wikipedia_maintenance.utils.reference_template_helper import ReferenceTemplateHelper
from wikipedia_maintenance.utils.template_replacement_validator import TemplateReplacementValidator


def test_normalize_template_name():
    """Test that _normalize_template_name handles MediaWiki variations correctly."""
    print("Testing _normalize_template_name...")
    
    test_cases = [
        ('Lien web', 'lien web'),
        ('lien web', 'lien web'),
        ('lien_web', 'lien web'),
        ('Lien_Web', 'lien Web'),  # MediaWiki: first char lowercase only
        ('Lien _ web', 'lien web'),
        ('  Lien  web  ', 'lien web'),
        ('Cite web', 'cite web'),
        ('cite_web', 'cite web'),
        ('Article', 'article'),
        ('Ouvrage', 'ouvrage'),
    ]
    
    all_passed = True
    for input_name, expected in test_cases:
        result = ReferenceTemplateHelper._normalize_template_name(input_name)
        if result == expected:
            print(f"  [PASS] '{input_name}' -> '{result}'")
        else:
            print(f"  [FAIL] '{input_name}' -> '{result}' (expected '{expected}')")
            all_passed = False
    
    return all_passed


def test_get_canonical_template_name():
    """Test that _get_canonical_template_name uses robust normalization."""
    print("\nTesting _get_canonical_template_name...")
    
    test_cases = [
        ("Lien web", "Lien web"),
        ("lien web", "Lien web"),
        ("lien_web", "Lien web"),
        ("Lien _ web", "Lien web"),  # Should now work with collapse
        ("cite web", "Lien web"),
        ("cite_web", "Lien web"),
        ("article", "article"),
        ("ouvrage", "ouvrage"),
    ]
    
    all_passed = True
    for input_name, expected in test_cases:
        result = ReferenceTemplateHelper._get_canonical_template_name(input_name)
        if result == expected:
            print(f"  [PASS] '{input_name}' -> '{result}'")
        else:
            print(f"  [FAIL] '{input_name}' -> '{result}' (expected '{expected}')")
            all_passed = False
    
    return all_passed


def test_template_reconstruction_case_preservation():
    """Test that _rebuild_template preserves original template name casing."""
    print("\nTesting _rebuild_template case preservation...")
    
    helper = ReferenceTemplateHelper()
    
    test_cases = [
        # (original_template, original_full_match, expected_template_name)
        ("lien web", "{{lien web|url=http://example.com|titre=Test}}", "lien web"),
        ("Lien web", "{{Lien web|url=http://example.com|titre=Test}}", "Lien web"),
        ("Lien_Web", "{{Lien_Web|url=http://example.com|titre=Test}}", "Lien_Web"),
        ("article", "{{article|url=http://example.com|titre=Test}}", "article"),
    ]
    
    all_passed = True
    for template_name, original_full_match, expected_name in test_cases:
        params = {"url": "http://example.com", "titre": "Test"}
        result = helper._rebuild_template(template_name, original_full_match, params)
        
        # Extract template name from result
        if result.startswith('{{') and '|' in result:
            result_name = result[2:result.find('|')].strip()
        elif result.startswith('{{') and '}}' in result:
            result_name = result[2:result.find('}}')].strip()
        else:
            result_name = result
        
        if result_name == expected_name:
            print(f"  [PASS] '{template_name}' preserved as '{result_name}'")
        else:
            print(f"  [FAIL] '{template_name}' became '{result_name}' (expected '{expected_name}')")
            all_passed = False
    
    return all_passed


def test_validator_allows_case_changes():
    """Test that validator allows case changes (bot should not interfere with casing)."""
    print("\nTesting validator allows case changes...")
    
    validator = TemplateReplacementValidator()
    
    # Test case: lien web → Lien web should be accepted (bot does not interfere with casing)
    old_content = "Some text {{lien web|url=http://example.com}} more text"
    new_content = "Some text {{Lien web|url=http://example.com}} more text"
    old_template_start = old_content.find("{{")
    old_template_end = old_content.find("}}") + 2
    new_template = "{{Lien web|url=http://example.com}}"
    
    is_valid, error_msg = validator.validate(
        old_content, new_content,
        old_template_start, old_template_end,
        new_template,
        normalize_name_func=ReferenceTemplateHelper._get_canonical_template_name
    )
    
    if is_valid:
        print(f"  [PASS] Case change 'lien web' -> 'Lien web' correctly accepted")
        return True
    else:
        print(f"  [FAIL] Case change 'lien web' -> 'Lien web' incorrectly rejected")
        print(f"    Reason: {error_msg}")
        return False


def test_validator_allows_legitimate_conversions():
    """Test that validator allows legitimate template conversions."""
    print("\nTesting validator allows legitimate conversions...")
    
    validator = TemplateReplacementValidator()
    
    # Test case: cite web → Lien web should be accepted (legitimate conversion)
    old_content = "Some text {{cite web|url=http://example.com}} more text"
    new_content = "Some text {{Lien web|url=http://example.com}} more text"
    old_template_start = old_content.find("{{")
    old_template_end = old_content.find("}}") + 2
    new_template = "{{Lien web|url=http://example.com}}"
    
    is_valid, error_msg = validator.validate(
        old_content, new_content,
        old_template_start, old_template_end,
        new_template,
        normalize_name_func=ReferenceTemplateHelper._get_canonical_template_name
    )
    
    if is_valid:
        print(f"  [PASS] Legitimate conversion 'cite web' -> 'Lien web' correctly accepted")
        return True
    else:
        print(f"  [FAIL] Legitimate conversion 'cite web' -> 'Lien web' incorrectly rejected")
        print(f"    Reason: {error_msg}")
        return False


def test_known_template_names_mapping():
    """Test that KNOWN_TEMPLATE_NAMES mapping works with new normalization."""
    print("\nTesting KNOWN_TEMPLATE_NAMES mapping...")
    
    helper = ReferenceTemplateHelper()
    
    test_cases = [
        ("lien web", "Lien web"),
        ("Lien _ web", "Lien web"),  # Should now work with collapse
        ("cite web", "Lien web"),
        ("cite_web", "Lien web"),
    ]
    
    all_passed = True
    for input_name, expected in test_cases:
        normalized = helper._normalize_template_name(input_name)
        result = helper.KNOWN_TEMPLATE_NAMES.get(normalized, normalized)
        
        if result == expected:
            print(f"  [PASS] '{input_name}' -> '{result}'")
        else:
            print(f"  [FAIL] '{input_name}' -> '{result}' (expected '{expected}')")
            all_passed = False
    
    return all_passed


def main():
    """Run all tests."""
    print("=" * 60)
    print("Template Normalization and Case Preservation Tests")
    print("=" * 60)
    
    results = []
    
    results.append(("Normalization", test_normalize_template_name()))
    results.append(("Canonical name", test_get_canonical_template_name()))
    results.append(("Case preservation", test_template_reconstruction_case_preservation()))
    results.append(("Validator allows case changes", test_validator_allows_case_changes()))
    results.append(("Validator allows conversions", test_validator_allows_legitimate_conversions()))
    results.append(("KNOWN_TEMPLATE_NAMES mapping", test_known_template_names_mapping()))
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("All tests passed! No regression detected.")
        return 0
    else:
        print("Some tests failed. Please review the failures above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

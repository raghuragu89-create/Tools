"""
Create Demo Test Cases in TestRail Project 51.
Uses existing run 173610 as examples, creates in a NEW suite called "Demo - Automation Analysis"
"""
import json, base64, sys
from urllib.request import Request, urlopen

# Config
URL = "https://your-instance.testrail.io"
EMAIL = "your-email@example.com"
KEY = "frWDlm1cEOuuIpcWVIdU-IIGEIq7uBHYIayEhMSko"
PROJECT_ID = 51
PREFIX = "/index.php?/api/v2/"
AUTH = base64.b64encode(f"{EMAIL}:{KEY}".encode()).decode()


def api_get(endpoint):
    req = Request(URL + PREFIX + endpoint)
    req.add_header("Authorization", f"Basic {AUTH}")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def api_post(endpoint, data):
    req = Request(URL + PREFIX + endpoint, data=json.dumps(data).encode(), method="POST")
    req.add_header("Authorization", f"Basic {AUTH}")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# Step 1: Fetch existing TCs from run 173610 for reference
print("Fetching existing TCs from run 173610 for reference...")
try:
    tests = api_get("get_tests/173610")
    if isinstance(tests, dict):
        tests = tests.get("tests", [])
    print(f"  Found {len(tests)} reference TCs")
    for t in tests[:3]:
        print(f"    Example: {t.get('title', '?')}")
except Exception as e:
    print(f"  Warning: Could not fetch run 173610: {e}")
    tests = []

# Step 2: Create a new suite for demo TCs
print("\nCreating new suite: 'Demo - Automation Analysis'...")
try:
    suite = api_post(f"add_suite/{PROJECT_ID}", {
        "name": "Demo - Automation Analysis",
        "description": "⚠️ DEMO ONLY — Do NOT use this suite for production testing. Created for TestRail Analyzer pipeline demo."
    })
    suite_id = suite["id"]
    print(f"  Suite created: ID {suite_id}")
except Exception as e:
    print(f"  Error creating suite: {e}")
    print("  Trying to find existing demo suite...")
    suites = api_get(f"get_suites/{PROJECT_ID}")
    suite_id = None
    for s in suites:
        if "Demo" in s.get("name", ""):
            suite_id = s["id"]
            print(f"  Found existing: {s['name']} (ID: {suite_id})")
            break
    if not suite_id:
        print("  FAILED. Exiting.")
        sys.exit(1)

# Step 3: Create a section
print("\nCreating section: 'Demo Accessibility Tests'...")
try:
    section = api_post(f"add_section/{PROJECT_ID}", {
        "suite_id": suite_id,
        "name": "Demo Accessibility Tests",
        "description": "Demo test cases for pipeline validation"
    })
    section_id = section["id"]
    print(f"  Section created: ID {section_id}")
except Exception as e:
    print(f"  Section error: {e}")
    section_id = None

# Step 4: Create demo test cases
print("\nCreating demo test cases...")

demo_cases = [
    {
        "title": "[Demo] Verify screen reader announces page title on navigation",
        "custom_steps": "1. Open the application in browser\n2. Enable screen reader (NVDA/VoiceOver)\n3. Navigate to the home page\n4. Listen for page title announcement\n5. Verify screen reader reads the correct page title",
        "custom_expected": "Screen reader announces the page title correctly when the page loads. The announcement should include the full page name and application context.",
        "custom_preconds": "Screen reader software installed and enabled. Browser supports ARIA landmarks.",
        "priority_id": 2,
    },
    {
        "title": "[Demo] Verify all images have alt text for accessibility compliance",
        "custom_steps": "1. Navigate to the product listing page\n2. Inspect each image element in the DOM\n3. Check for alt attribute presence\n4. Verify alt text is descriptive and meaningful\n5. Check decorative images have empty alt attribute",
        "custom_expected": "All meaningful images have descriptive alt text. Decorative images have alt=\"\". No image is missing the alt attribute entirely.",
        "custom_preconds": "Product listing page has at least 10 images loaded.",
        "priority_id": 2,
    },
    {
        "title": "[Demo] Verify keyboard navigation through main menu items",
        "custom_steps": "1. Open the application\n2. Press Tab key to move focus to main navigation\n3. Use arrow keys to navigate between menu items\n4. Press Enter to select a menu item\n5. Verify focus moves to the selected page content\n6. Press Escape to close any dropdown menus",
        "custom_expected": "User can navigate all menu items using only keyboard. Focus indicator is visible on each item. Enter activates the link. Escape closes dropdowns. Tab order follows logical reading order.",
        "custom_preconds": "Application loaded. No mouse input used during test.",
        "priority_id": 1,
    },
    {
        "title": "[Demo] Verify color contrast ratio meets WCAG 2.1 AA standards",
        "custom_steps": "1. Open the login page\n2. Use browser DevTools or aXe extension\n3. Check foreground/background color contrast for all text elements\n4. Verify contrast ratio is at least 4.5:1 for normal text\n5. Verify contrast ratio is at least 3:1 for large text",
        "custom_expected": "All text elements meet WCAG 2.1 AA contrast requirements. Normal text has 4.5:1 ratio minimum. Large text (18px+ or 14px+ bold) has 3:1 minimum.",
        "custom_preconds": "aXe DevTools extension installed. Login page accessible.",
        "priority_id": 2,
    },
    {
        "title": "[Demo] Verify form error messages are accessible to screen readers",
        "custom_steps": "1. Navigate to registration form\n2. Submit form with empty required fields\n3. Check that error messages appear\n4. Verify errors are announced by screen reader\n5. Verify aria-invalid is set on invalid fields\n6. Verify aria-describedby links error message to field",
        "custom_expected": "Error messages are announced immediately by screen reader when form validation fails. Each invalid field has aria-invalid=true and aria-describedby pointing to the error message element.",
        "custom_preconds": "Screen reader enabled. Registration form accessible.",
        "priority_id": 1,
    },
    {
        "title": "[Demo] Verify focus trap in modal dialog",
        "custom_steps": "1. Click button to open modal dialog\n2. Verify focus moves to first focusable element in modal\n3. Tab through all elements in modal\n4. Verify focus does not leave the modal\n5. Press Escape to close modal\n6. Verify focus returns to the triggering button",
        "custom_expected": "Focus is trapped within the modal dialog. Tabbing cycles through modal elements only. Escape closes the modal. Focus returns to the original trigger element after close.",
        "custom_preconds": "Page has a modal trigger button. Modal contains at least 3 focusable elements.",
        "priority_id": 2,
    },
    {
        "title": "[Demo] Check ARIA labels on interactive buttons without visible text",
        "custom_steps": "1. Navigate to the toolbar section\n2. Identify icon-only buttons (no visible text)\n3. Inspect each button for aria-label or aria-labelledby\n4. Verify the label accurately describes the button action",
        "custom_expected": "All icon-only buttons have aria-label or aria-labelledby attributes. Labels are concise and describe the action (e.g., 'Close', 'Search', 'Menu').",
        "custom_preconds": "Toolbar section visible with icon buttons.",
        "priority_id": 3,
    },
    {
        "title": "[Demo] Verify skip navigation link functionality",
        "custom_steps": "1. Load the page\n2. Press Tab once (first focusable element)\n3. Verify 'Skip to main content' link appears\n4. Press Enter on skip link\n5. Verify focus moves to main content area",
        "custom_expected": "Skip navigation link is the first focusable element. Activating it moves focus directly to main content, bypassing all navigation elements.",
        "custom_preconds": "Page has standard header navigation with multiple links.",
        "priority_id": 3,
    },
    {
        "title": "[Demo] Verify video player has captions and audio descriptions",
        "custom_steps": "1. Navigate to page with video content\n2. Play the video\n3. Enable closed captions\n4. Verify captions match spoken content\n5. Check for audio description track availability",
        "custom_expected": "Video player has visible caption toggle. Captions are synchronized with audio. Audio description track is available for visual content that is not described in the main audio.",
        "custom_preconds": "Video content page loaded. Video has audio and visual information.",
        "priority_id": 3,
    },
    {
        "title": "[Demo] Verify responsive design maintains accessibility at different viewports",
        "custom_steps": "1. Open page at 1920x1080 desktop resolution\n2. Resize to 768px tablet viewport\n3. Resize to 375px mobile viewport\n4. At each size verify: focus indicators visible, tap targets 44px minimum, text reflows without horizontal scroll\n5. Run aXe scan at each viewport size",
        "custom_expected": "All accessibility features maintained at every viewport. No content is hidden or inaccessible. Touch targets meet 44x44px minimum. Text reflows without requiring horizontal scrolling at 320px.",
        "custom_preconds": "Browser supports responsive design mode. aXe extension available.",
        "priority_id": 2,
    },
]

created = 0
for tc in demo_cases:
    try:
        payload = {
            "title": tc["title"],
            "custom_steps": tc["custom_steps"],
            "custom_expected": tc["custom_expected"],
            "custom_preconds": tc.get("custom_preconds", ""),
            "priority_id": tc.get("priority_id", 2),
        }
        if section_id:
            result = api_post(f"add_case/{section_id}", payload)
        else:
            result = api_post(f"add_case/{suite_id}", payload)
        print(f"  ✓ Created: {tc['title'][:60]}... (ID: {result.get('id')})")
        created += 1
    except Exception as e:
        print(f"  ✗ Failed: {tc['title'][:40]}... — {e}")

print(f"\n{'='*60}")
print(f"Done! Created {created}/{len(demo_cases)} demo TCs")
print(f"Suite: 'Demo - Automation Analysis' (ID: {suite_id})")
print(f"⚠️  DO NOT use this suite for production testing!")
print(f"{'='*60}")

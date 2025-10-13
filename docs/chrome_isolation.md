# Chrome Browser Isolation for Automation

## Overview

The Chrome browser launched by `start_service.py` is dedicated to Boss Zhipin automation via Playwright/CDP. This document explains how we prevent manual user interaction from interfering with automation.

## Implementation

### 1. Chrome App Mode (Active)

**Location**: `start_service.py` lines 239-263

**How it works**: 
- Chrome is launched with the `--app=<URL>` flag
- This creates a dedicated application window without the address bar
- The window opens directly to Boss Zhipin's chat interface
- Navigation is still possible within the app window, but the dedicated nature makes it clear this is for automation only

**Advantages**:
- ✅ Clean, minimal UI signals "automation only"
- ✅ No address bar prevents casual URL entry
- ✅ Native Chrome feature, very stable
- ✅ Doesn't interfere with Playwright automation

**Code**:
```python
# Get BASE_URL from config for app mode
from src.config import settings
chat_url = settings.CHAT_URL or "about:blank"

chrome_cmd = [
    chrome_path,
    f"--remote-debugging-port={cdp_port}",
    f"--user-data-dir={user_data}",
    # ... other flags ...
    # Launch in app mode - creates dedicated window without address bar
    f"--app={chat_url}"
]
```

### 2. JavaScript Navigation Guard (Optional)

**Location**: `boss_service.py` method `_inject_navigation_guard()`

**How it works**:
- Injects JavaScript that intercepts all link click events
- Blocks navigation to any URL outside `settings.BASE_URL`
- Only allows relative links and same-origin navigation
- Logs blocked navigation attempts to console

**Status**: Currently **NOT active** by default. The `--app` mode provides sufficient isolation.

**To enable**: Call `await self._inject_navigation_guard(page)` after page loads in `_ensure_page()` or `_prepare_browser_session()`.

**Advantages**:
- ✅ Completely blocks external link navigation
- ✅ Provides detailed logging
- ✅ Can be dynamically enabled/disabled
- ⚠️ Requires re-injection after page refreshes

**Code Example**:
```python
async def _ensure_page(self) -> Page:
    # ... existing code ...
    candidate = await self.context.new_page()
    await candidate.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=20000)
    
    # Optional: Enable navigation guard
    # await self._inject_navigation_guard(candidate)
    
    return candidate
```

## Comparison

| Feature | App Mode | Navigation Guard |
|---------|----------|------------------|
| Prevents URL bar access | ✅ Yes | ❌ No |
| Blocks link clicks | ⚠️ Partial | ✅ Complete |
| Visual indication | ✅ Yes (dedicated window) | ❌ No |
| Performance impact | ✅ None | ⚠️ Minimal JS overhead |
| Stability | ✅ Very stable | ⚠️ Needs re-injection |
| Default status | ✅ Active | ❌ Disabled |

## Recommendation

**Current setup (App Mode only)** is recommended for most use cases because:
1. Provides clear visual indication this Chrome is for automation
2. Zero maintenance overhead
3. Doesn't interfere with Playwright's automation capabilities
4. Stable across page reloads

**Add Navigation Guard** only if:
- Users frequently click links manually in the automation window
- You need detailed logging of navigation attempts
- You want to completely lock down the browser

## Testing

Start the service and verify the Chrome window:
```bash
python start_service.py
```

Expected behavior:
- Chrome opens in a dedicated window without address bar
- Window title shows "Boss直聘" 
- No tabs visible (single app window)
- Playwright automation works normally

## Troubleshooting

### Chrome won't start in app mode
- Verify `config/config.yaml` has valid `boss_zhipin.chat_url`
- Check Chrome version supports `--app` flag (all modern versions do)
- Try removing `user_data_dir` to start fresh

### Navigation guard not working
- Ensure the method is actually called (check logs)
- Verify JavaScript console for "[Navigation Guard] Installed" message
- Re-inject after page refreshes if needed

## Future Enhancements

Possible improvements:
1. **Kiosk mode**: Use `--kiosk` for fullscreen locked mode (more restrictive)
2. **Content Security Policy**: Configure CSP headers to restrict navigation
3. **Browser policies**: Use Chrome enterprise policies for system-wide restrictions

## References

- [Chrome Command Line Switches](https://peter.sh/experiments/chromium-command-line-switches/)
- [Playwright CDP Documentation](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)
- [Boss Service Architecture](docs/technical.md)


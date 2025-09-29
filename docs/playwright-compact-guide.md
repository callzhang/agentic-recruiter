# Playwright Python Compact Guide

## Setup and Launch
Core primitives for spinning up browsers and isolated sessions before any page work.
- `sync_playwright()` / `async_playwright()` – enter these context managers (e.g. `with sync_playwright() as p:`) to spin up Playwright, receive the `p.chromium`, `p.firefox`, and `p.webkit` browser factories, and ensure the driver shuts down when the block ends.
- `playwright.chromium|firefox|webkit.launch(headless?, channel?, args?, proxy?)` – launch a real browser process (Chromium, Firefox, or WebKit) with the desired command-line options.
- `browser.new_context(viewport?, is_mobile?, locale?, timezone?, permissions?, geolocation?, color_scheme?, reduced_motion?, java_script_enabled?, http_credentials?, proxy?, storage_state?, record_video_dir/size?, accept_downloads?)` – create an incognito-like browser profile with its own cookies, storage, permissions, and device overrides.
- `browser.new_page()` / `context.new_page()` – open a fresh tab inside a context; `browser_type.launch_persistent_context(user_data_dir, ...)` instead loads an existing user profile from disk.
- `browser.close()` / `context.close()` – shut down the browser or context to release resources and write out videos, downloads, and traces.

## Pages and Navigation
Commands that load URLs, react to lifecycle hooks, and manage top-level pages or popups.
- `page.goto(url, wait_until?, referer?, timeout?)`, `page.reload()`, `page.wait_for_url(pattern, wait_until?, timeout?)` – navigate to a URL, refresh, or wait until the address bar matches a pattern.
- `page.wait_for_event(name, predicate?, timeout?)` and helpers like `page.wait_for_load_state()` – pause test execution until Playwright fires the specified lifecycle event.
- Popups and dialogs: `context.on('page', handler)`, `page.expect_popup()`, `page.on('dialog', handler)`, `dialog.accept(text?)`, `dialog.dismiss()` – listen for new windows and handle JavaScript alerts/confirm/prompt UIs.
- `page.pause()`, `page.bring_to_front()`, `page.close(run_before_unload?)`, `page.is_closed()` – enter the inspector, focus a tab, close it safely, or check whether it was already closed.

## Locators and Handles
APIs that find elements, compose queries, and drop down to raw DOM handles when necessary.
- Core locator: `page.locator(selector, has?, has_text?)` plus semantic helpers such as `get_by_role|label|text|placeholder|alt_text|title|test_id` – describe how to find elements by accessibility role, label text, or other attributes.
- Locator operations: `.click()`, `.dblclick()`, `.hover()`, `.scroll_into_view_if_needed()`, `.dispatch_event()`, `.check()`, `.uncheck()`, `.set_input_files()`, `.fill()`, `.type()`, `.press()`, `.press_sequentially()`, `.select_option()`, `.focus()`, `.drag_to()`, `.highlight()` – perform standard user gestures on the located element.
- Composition helpers: `.first`, `.last`, `.nth(i)`, `.filter(has?, has_text?, visible?, has_not?, has_not_text?)`, `.locator(selector)`, `.and_(other)`, `.or_(other)`, `.all()`, `.all_inner_texts()`, `.all_text_contents()` – refine or combine locator results and extract lists of texts.
- Frames: `page.frame_locator(selector)` and `page.frame(name?, url?, predicate?)` – target elements inside iframes either with nested locators or by grabbing the frame object directly.
- Element/JS handles (`page.query_selector`, `.evaluate_handle()`, `frame.evaluate_handle()`, `handle.dispose()`) – capture persistent handles to DOM nodes or JavaScript objects when you need manual control outside the locator model.
- Custom selector engines via `selectors.register(name, script, content_script=True?)` – plug in your own selector logic before pages are created.

## Keyboard, Mouse, and Touch
Low-level input surfaces for simulating hardware events beyond high-level locators.
- Keyboard API: `page.keyboard.type(text, delay?)`, `.press(key, delay?)`, `.down(key)`, `.up(key)`, `.insert_text(text)` – send keystrokes exactly as if a physical keyboard were used, including modifier keys and custom delays.
- Mouse API: `page.mouse.move(x, y, steps?)`, `.down(button?, click_count?, modifiers?)`, `.up(...)`, `.click(...)`, `.dblclick(...)`, `.wheel(delta_x, delta_y)` – move the cursor, click buttons, and scroll programmatically.
- Prefer `locator.fill()` for text fields; fall back to `locator.type()` or `press_sequentially()` when the application requires character-by-character input handlers.
- Touch/gesture emulation through `page.touchscreen.tap(x, y)` or `locator.dispatch_event('touchstart', init)` – reproduce taps, swipes, and custom multi-touch gestures on touch-centric UIs.

## Assertions
Built-in expect-style checks that auto-wait and fail fast when page state is wrong.
- `expect(locator)` checks: `to_be_visible|hidden|enabled|disabled|editable|checked|unchecked|attached|detached`, `to_have_text`, `to_contain_text`, `to_have_value`, `to_have_attribute`, `to_have_class`, `to_have_css`, `to_have_count`, `to_have_js_property`, `to_have_screenshot`, `to_match_aria_snapshot` – assert common visual or structural conditions on a locator.
- Page/response expectations: `expect(page).to_have_title|url`, `expect(async_fn).rejects/fulfill` – validate browser-level state or wrap coroutine outcomes inside the same retry logic.
- Configure retries with `expect.set_options(timeout=...)` or per-call `timeout`/message overrides to customize how long an assertion should keep waiting.

## Input Widgets and User Actions
High-level helpers aimed at common form flows, file pickers, drags, and scrolling.
- Forms: `locator.fill()`, `.clear()`, `.select_option(value|label|index|values)`, `.check()`, `.uncheck()`, `.set_input_files(paths|payloads)` – populate text boxes, choose dropdown options, tick checkboxes, and upload files in a single call.
- Keys and shortcuts: `locator.press("Enter")`, `press("Control+ArrowRight")`, `press("Shift+A")` – simulate keyboard shortcuts using the focused element as the target.
- File workflows: `page.expect_file_chooser()`, `file_chooser.set_files()`, `set_input_files([])` – wait for a file dialog to appear, programmatically choose files or folders, and clear selections.
- Drag-and-drop: `locator.drag_to(target)` or manual `hover()/page.mouse.down()/...` sequences – move items between drop zones exactly the way a user would.
- Scrolling: `locator.scroll_into_view_if_needed()`, `page.mouse.wheel()`, `locator.evaluate("el => el.scrollTop += 100")` – bring lazy-loaded content into view or fine-tune scrolling positions.

## Network and API Control
Tools for observing, stubbing, or driving HTTP traffic alongside UI steps.
- Route traffic with `context.route(url, handler)`/`page.route`; combine with `route.fulfill(status?, headers?, body?/json?)`, `route.continue_(overrides?)`, `route.abort(reason?)`, `route.fetch(overrides?)`, `context.unroute()` – intercept any network request and decide whether to mock, tweak, or let it through.
- Observe traffic via `page.on('request'|'response'|'requestfailed')`, `page.wait_for_request()`, `page.expect_response()` – listen for network activity and wait for specific calls to appear.
- API client: `playwright.request.new_context(base_url?, extra_http_headers?, http_credentials?)`, then `api.get|post|put|patch|delete|head(...)` plus `response.ok`, `.status`, `.json()`, `.text()`, `.body()`, `api.dispose()` – send direct HTTP requests without opening a browser and assert on the response payload.
- Reuse auth: `context.storage_state(path?)`, `browser.new_context(storage_state=...)` – capture cookies and local storage once and load them back into new contexts.
- HTTP proxy and auth at launch/context level (`proxy={'server':..., 'username':..., 'password':...}`, `http_credentials={...}`) – route traffic through corporate proxies or supply basic auth credentials globally.

## Downloads, Storage, Media, Tracing
Manage side artifacts—files, cookies, screenshots, videos, and trace archives—for auditing runs.
- Downloads: `page.expect_download()` context manager, `download.save_as(path)`, `download.path()`, `download.url`, `download.failure` – capture the file that a click triggered and store it in a known location.
- Storage & cookies: `context.cookies()`, `.add_cookies(cookies)`, `.clear_cookies()`, `.grant_permissions(perms, origin?)`, `.clear_permissions()`, `context.storage_state(path?)` – inspect or pre-seed browser storage so that tests start from a known state.
- Screenshots: `page.screenshot(path?, full_page?, clip?, omit_background?, quality?)`, `locator.screenshot()` – produce visual evidence for whole pages or individual elements.
- Video capture via context options (`record_video_dir`, `record_video_size`); access with `page.video.path()`, `.save_as(path)`, `.delete()` – automatically record a video of each test run and archive or discard it as needed.
- Tracing: `context.tracing.start(screenshots?, snapshots?, sources?, title?)`, `.start_chunk(title?)`, `.stop_chunk(path?)`, `.stop(path?)`; review in `playwright show-trace` or `trace.playwright.dev` – collect a timeline of actions, DOM snapshots, and network events for debugging.

## Clock and Timing Control
Deterministic time travel primitives for exercising timers and scheduling logic without waiting.
- Manipulate timers through `page.clock.set_fixed_time(datetime)`, `.install(time?, timezone?, epoch?)`, `.pause_at(datetime)`, `.fast_forward(duration)`, `.run_for(milliseconds)`, `.resume()`, `.reset()` – freeze `Date.now`, jump forward, or tick timers manually so you can test alarms, inactivity timeouts, and animations instantly.

## Events and Web Workers
Hooks for subscribing to browser events, background workers, and service workers.
- Events: `page.on('console'|'pageerror'|'frameattached'|'framedetached'|'framenavigated'|'websocket'|'download'|...)`; remove with `page.off` / `remove_listener` – attach callbacks that react whenever the page logs to the console, throws errors, opens new frames, or starts downloads.
- Workers: `page.on('worker', handler)`, `worker.evaluate()` – watch for web workers and run scripts inside them when your app offloads logic to a background thread.
- Service workers via `context.service_workers`, `context.wait_for_event('serviceworker')` – obtain references to installed service workers so you can confirm offline caching or push logic.

## JavaScript Execution and Injection
Run custom scripts inside the page, expose helpers, or preload code/styles.
- Evaluate: `page.evaluate(expression, arg?)`, `.evaluate_handle()`, `.evaluate_on_selector(selector, expression, arg?)`, `.evaluate_on_selector_all(...)`, `frame.evaluate(...)`, `locator.evaluate(...)` – execute JavaScript in the page context and optionally pass Python data into it or pull results back out.
- Inject resources: `page.add_script_tag(path?/content?, type?, id?)`, `page.add_style_tag(path?/content?)`, `page.add_init_script(script)` – load external bundles, inline styles, or helper utilities before the app scripts run.
- Expose helpers: `page.expose_function(name, callable)` – make a Python function callable from the browser so page code can report back into the test.

## Emulation and Environment
Flip runtime knobs—device metrics, locale, network—to mimic real user environments.
- Device emulation via `playwright.devices['Device Name']`; spread into `browser.new_context(**device)` – reuse curated presets (viewport, user agent, touch support) for popular phones and tablets.
- Manual overrides: `viewport`, `device_scale_factor`, `is_mobile`, `has_touch`, `user_agent`, `color_scheme`, `reduced_motion`, `forced_colors`, `timezone_id`, `locale`, `geolocation`, `permissions`, `offline`, `java_script_enabled` – tailor the context to simulate any device, location, or accessibility setting.
- Media emulation: `page.emulate_media(media?, color_scheme?, reduced_motion?, forced_colors?)` – tell the page it’s printing, in dark mode, or respecting reduced motion so CSS switches to the correct mode.
- Timeouts: `context.set_default_timeout(ms)`, `context.set_default_navigation_timeout(ms)`, `page.set_default_timeout(ms)`, `page.set_default_navigation_timeout(ms)` – adjust how long Playwright should wait before timing out actions or navigations.

## Debugging and Tooling
Inspector, CLI, and logging tricks for diagnosing flaky or failing tests.
- Inspector: run with `PWDEBUG=1` or call `page.pause()` – open the interactive inspector where you can step through actions, view locators, and replay steps.
- CLI: `playwright install [browser]`, `install-deps`, `codegen url`, `show-trace trace.zip`, `test --browser webkit`, `test --trace on`, `test --reporter=list`, `show-report` – essential command-line tooling for installing browsers, recording scripts, running tests, and viewing reports/traces.
- Logging: set `DEBUG=pw:api` for verbose protocol traces; subscribe with `page.on('console', handler)` – surface low-level Playwright logs and browser console output in your test run.

## Chrome Extensions and WebView2
Special workflows for automating Chromium-based extensions and Win32 WebView2 hosts.
- Load extensions with `playwright.chromium.launch_persistent_context(user_data_dir, args=["--disable-extensions-except=PATH", "--load-extension=PATH"], channel="chromium")`; inspect service worker via `context.service_workers` – spin up Chromium with your unpacked extension so you can exercise background/service-worker logic.
- Test extension UI pages through `chrome-extension://<extension_id>/...` routes – navigate straight to popup or options pages using the generated extension ID.
- Automate WebView2 apps by starting the host with `--remote-debugging-port`, then `browser_type.connect_over_cdp(endpoint)`; provide unique `WEBVIEW2_USER_DATA_FOLDER` per run – connect Playwright to native Windows WebView2 controls for end-to-end automation.

## Test Structuring Patterns
Reusable patterns that keep larger suites maintainable and expressive.
- Page Object Model: wrap related locators and behavior inside Python classes so tests read like business scenarios rather than raw selectors.
- Mix API + UI: use `api_request_context` fixtures to set up or verify state via HTTP calls while the UI confirms user-visible changes.
- Snapshot testing: `expect(locator).to_match_aria_snapshot(snapshot)` with regex or strict modes – capture the accessibility tree and compare it across runs for regression safety.
- Generator/codegen: `playwright codegen --target python` – record flows interactively to generate starter Python scripts, optionally with saved authentication state.

This guide clusters Playwright’s Python surface—browser orchestration, robust locating, input simulation, assertions, network control, environment emulation, and diagnostics—so you can quickly map scenarios to the APIs involved.

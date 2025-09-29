# WASM Loader Patch Summary

This folder contains a patched copy of `wasm_canvas-1.0.2-5030_patched.js` that differs from the CDN version used by the resume iframe. Two functional changes were introduced so downstream Playwright scripts can extract full resume details:

1. **Bootstrap hook inside `__wbg_finalize_init`**  
   After the WebAssembly exports are initialised, the script now guarantees a global `window.__resume_data_store` object exists. This is the coordination point that our Playwright tooling reads after the module finishes rendering.

2. **Wrappers around the exported `start` functions**  
   Both `start` and `start_anonymous_resume` are wrapped so their invocation still calls the original Rust entrypoints, but the arguments are recorded first:
   - `geek_info_other_fields` and the encrypt string are copied into `window.__resume_data_store` before the engine draws the canvas.
   - Flags (`__resume_wrapped_start` / `__resume_wrapped_start_anonymous`) prevent the wrapper from being installed more than once.

With these hooks in place, any automation that routes the CDN URL to this local file can recover the rich resume sections (e.g. "个人优势", skills) straight from JavaScript instead of relying on canvas scraping.

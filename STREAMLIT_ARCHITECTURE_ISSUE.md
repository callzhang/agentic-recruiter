# Streamlit Architecture Issue: Missing Job Selector

## Problem

**Symptom**: `AttributeError: 'NoneType' object has no attribute 'get'` in `pages/5_消息列表.py:269`

```python
context = {
    "job_description": selected_job.get("description", ""),  # ❌ selected_job is None
    ...
}
```

## Root Cause

**Missing Link**: No centralized job selector populates `st.session_state["selected_job"]`.

### Current State

1. ✅ `streamlit_shared.py:30` - Initializes `selected_job = None`
2. ❌ **NO PAGE** ever sets `selected_job` to an actual job object
3. ❌ `pages/5_消息列表.py:231` - Blindly reads `selected_job` expecting a dict
4. ❌ `pages/5_消息列表.py:269,270,307,308` - Calls `.get()` on `None`

### Architecture Gap

```
pages/4_岗位画像.py     → Manages jobs in YAML ✅
                         → Does NOT set st.session_state["selected_job"] ❌

pages/6_推荐牛人.py      → Loads jobs from cache ✅
                         → Uses selected_job_index locally only ❌
                         → Does NOT sync to st.session_state["selected_job"] ❌

pages/5_消息列表.py      → Expects st.session_state["selected_job"] to be set ❌
                         → Crashes when it's None ❌
```

## Why It Fails

Following the principle "let it fall and find out reason":

1. **Job configuration exists** (`config/jobs.yaml`) ✅
2. **Job management UI exists** (`pages/4_岗位画像.py`) ✅
3. **Job selection exists** (in `pages/6_推荐牛人.py` locally) ✅
4. **Global job state missing** - No component sets `st.session_state["selected_job"]` ❌

## Solution Options

### Option 1: Add Job Selector to Sidebar (Recommended)

Add to `streamlit_shared.py/sidebar_controls()`:

```python
def sidebar_controls(*, include_config_path: bool = False, include_job_selector: bool = False) -> None:
    ...
    
    if include_job_selector:
        config = load_config(get_config_path())
        roles = config.get("roles", [])
        
        if roles:
            job_options = {role["position"]: role for role in roles}
            selected_job_name = st.sidebar.selectbox(
                "当前岗位",
                options=list(job_options.keys()),
                key="__job_selector__"
            )
            st.session_state["selected_job"] = job_options[selected_job_name]
            st.session_state["selected_job_index"] = roles.index(job_options[selected_job_name])
        else:
            st.sidebar.warning("未配置岗位，请到「岗位画像」页面添加")
            st.session_state["selected_job"] = None
```

Then in `pages/5_消息列表.py`:
```python
sidebar_controls(include_config_path=False, include_job_selector=True)
```

**Pros**:
- ✅ Centralized, reusable across pages
- ✅ Single source of truth
- ✅ Consistent UX

**Cons**:
- ⚠️ Sidebar gets crowded

### Option 2: Add Job Selector to Each Page

Each page (`pages/5_消息列表.py`, `pages/6_推荐牛人.py`) manages its own job selector.

**Pros**:
- ✅ Page-specific customization

**Cons**:
- ❌ Code duplication
- ❌ Inconsistent UX
- ❌ State sync issues

### Option 3: Default to First Job

Fallback in `streamlit_shared.py/ensure_state()`:

```python
if "selected_job" not in st.session_state or st.session_state["selected_job"] is None:
    config = load_config(get_config_path())
    roles = config.get("roles", [])
    st.session_state["selected_job"] = roles[0] if roles else None
```

**Pros**:
- ✅ Simple, automatic

**Cons**:
- ❌ No user control
- ❌ Assumes first job is desired

## Recommendation

**Implement Option 1** - Add centralized job selector to sidebar with:
1. `include_job_selector` parameter in `sidebar_controls()`
2. Load jobs from YAML config
3. Set `st.session_state["selected_job"]` and `st.session_state["selected_job_index"]`
4. Handle empty jobs list gracefully

## Principle Alignment

> "Everything should work as coded, if not, let it fall and find out reason"

✅ **Reason found**: Missing job selector component
✅ **Proper fix**: Add the missing component, don't mask with `try-except`
✅ **Fail-fast**: Let `None.get()` crash to expose the architecture gap

## Status

🚧 **Issue Identified, Solution Designed**
- User needs to decide which option to implement
- No code changes made yet (following principle: understand first, act second)


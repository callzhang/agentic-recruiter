FROM langchain/langgraph-api:3.11

RUN PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir 'langchain>=1.0.0' 'langchain-openai>=0.3.0' 'robust-json-parser>=0.1.0'

# -- Adding non-package dependency agent --
ADD ./agent /deps/outer-agent/agent
RUN set -ex && \
    for line in '[project]' \
                'name = "agent"' \
                'version = "0.1"' \
                '[tool.setuptools]' \
                'packages = ["agent"]' \
                '[tool.setuptools.package-data]' \
                '"*" = ["**/*"]' \
                '[build-system]' \
                'requires = ["setuptools>=61"]' \
                'build-backend = "setuptools.build_meta"'; do \
        echo "$line" >> /deps/outer-agent/pyproject.toml; \
    done
# -- End of non-package dependency agent --

# -- Installing all local dependencies --
RUN for dep in /deps/*; do             echo "Installing $dep";             if [ -d "$dep" ]; then                 echo "Installing $dep";                 (cd "$dep" && PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir -c /api/constraints.txt -e .);             fi;         done
# Verify agent package is installed and importable
RUN python3 -c "import agent; print('Agent package found at:', agent.__file__)" || (echo "Agent package not found, checking..." && python3 -c "import sys; print('Python path:', sys.path)" && ls -la /deps/outer-agent/)
# -- End of local dependencies install --
ENV LANGGRAPH_STORE='{"index": {"embed": "openai:text-embedding-3-small", "dims": 1536, "fields": ["$"]}, "ttl": {"refresh_on_read": true, "sweep_interval_minutes": 60, "default_ttl": 43200}}'
ENV LANGGRAPH_CHECKPOINTER='{"ttl": {"strategy": "delete", "sweep_interval_minutes": 60, "default_ttl": 43200}}'
ENV LANGSERVE_GRAPHS='{"manager_agent": "/deps/outer-agent/agent/graph.py:manager_graph", "recruiter_agent": "/deps/outer-agent/agent/graph.py:recruiter_graph"}'



# -- Ensure user deps didn't inadvertently overwrite langgraph-api
RUN mkdir -p /api/langgraph_api /api/langgraph_runtime /api/langgraph_license && touch /api/langgraph_api/__init__.py /api/langgraph_runtime/__init__.py /api/langgraph_license/__init__.py
RUN PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir --no-deps -e /api
# -- Reinstall langchain and other dependencies after API reinstall to ensure they're available --
RUN PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir 'langchain>=1.0.0' 'langchain-openai>=0.3.0' 'robust-json-parser>=0.1.0'
# -- End of ensuring user deps didn't inadvertently overwrite langgraph-api --
# -- Removing build deps from the final image ~<:===~~~ --
RUN pip uninstall -y pip setuptools wheel
RUN rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/lib/python*/site-packages/setuptools* /usr/local/lib/python*/site-packages/wheel* && find /usr/local/bin -name "pip*" -delete || true
RUN rm -rf /usr/lib/python*/site-packages/pip* /usr/lib/python*/site-packages/setuptools* /usr/lib/python*/site-packages/wheel* && find /usr/bin -name "pip*" -delete || true
RUN uv pip uninstall --system pip setuptools wheel && rm /usr/bin/uv /usr/bin/uvx


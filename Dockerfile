FROM public.ecr.aws/docker/library/node:22.23.2-bookworm-slim AS node
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/homebound
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
COPY agentsafe/*.mjs agentsafe/*.sh agentsafe/package*.json ./agentsafe/
RUN npm ci --omit=dev --prefix agentsafe && useradd --uid 10001 --create-home homebound \
    && mkdir -p .homebound audit && chown -R homebound:homebound .homebound audit
USER homebound
EXPOSE 8300
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8300/healthz', timeout=2)"
CMD ["python", "-m", "app.cli.web", "--container"]

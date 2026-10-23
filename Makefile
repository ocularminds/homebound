PYTHON ?= .venv/bin/python

.PHONY: install check preview demo package canvas-image canvas-worker validate-infra

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements-dev.lock
	$(PYTHON) -m pip install --no-deps -e .
	npm ci --prefix agentsafe

check:
	$(PYTHON) -m pytest -q
	npm run check --prefix agentsafe
	node --test tests/*.test.cjs

preview:
	$(PYTHON) -m app.cli.web

demo:
	./scripts/run-demo.sh --with-services

package:
	$(PYTHON) scripts/build_submission.py

canvas-image:
	docker build --platform linux/arm64 -f infra/firetv/Dockerfile -t homebound-canvas:submission .

canvas-worker:
	$(PYTHON) scripts/build_canvas_worker.py

validate-infra:
	.homebound/cfn-tools/bin/cfn-lint --template infra/firetv/ambient-canvas.yaml --regions us-east-1 eu-west-1
	.homebound/cfn-guard/bin/cfn-guard validate --rules .homebound/aws-guard-rules --rules infra/firetv/canvas.guard --data infra/firetv/ambient-canvas.yaml --show-summary fail

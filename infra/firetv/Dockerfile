FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /srv/homebound
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home homebound
USER homebound
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.ambient.runtime:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

FROM python:3.13
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY . .
RUN uv sync --locked
CMD ["uv", "run", "ecrupdater.py"]

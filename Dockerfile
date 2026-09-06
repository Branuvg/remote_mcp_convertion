FROM python:3.13-slim

# Copy the uv binary from its official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv sync --frozen

EXPOSE $PORT

CMD ["uv", "run", "server.py"]

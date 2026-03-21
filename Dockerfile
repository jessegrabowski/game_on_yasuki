FROM ghcr.io/prefix-dev/pixi:latest

ARG VERSION=0.0.0+unknown
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GAME_ON_YASUKI=${VERSION}

LABEL maintainer="Jesse Grabowski <jessegrabowski@gmail.com>"
LABEL description="Game on, Yasuki! - Online client for playing classic L5R"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml pixi.lock ./
RUN mkdir -p src/yasuki_core && touch src/yasuki_core/__init__.py
RUN pixi install --locked --environment prod

COPY src/ ./src/
COPY tests/ ./tests/
COPY play.py README.md ./

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["pixi", "run", "-e", "prod", "api"]

FROM ghcr.io/prefix-dev/pixi:latest AS build
ARG VERSION=0.0.0+unknown
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GAME_ON_YASUKI=${VERSION}

WORKDIR /app

COPY pyproject.toml pixi.lock* ./
COPY app/ ./app/
COPY tests/ ./tests/
COPY play.py README.md ./

RUN pixi install --locked || pixi install

FROM ghcr.io/prefix-dev/pixi:latest

LABEL maintainer="Jesse Grabowski <jessegrabowski@gmail.com>"
LABEL description="Game on, Yasuki! - Online client for playing classic L5R"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV L5R_DATABASE_URL=postgresql://l5r:l5r@db/l5r

WORKDIR /app

COPY --from=build /app /app

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["pixi", "run", "play"]

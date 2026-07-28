# Docker Guide

Docker runs PostgreSQL (and optionally the API server) without a native install.
The GUI still runs on the host machine.

**Prerequisites:** Docker (Docker Desktop, or Docker Engine + Compose v2) installed and
running, and [Pixi](https://pixi.sh) (see [Setup](setup.md)). PostgreSQL binds host port
5432 and the API binds 8000, so stop any local service already using them.

## Configure

`POSTGRES_PASSWORD` is required and has no default — the containers will not start until
it is set. Copy the template and set it:

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD (and any other values you want to change)
```

Docker Compose loads `.env` automatically from the project root; `.env` is gitignored.

## Database Only

Start PostgreSQL and seed the card database:

```bash
pixi run docker-up
```

Wait for `yasuki-db-init exited with code 0`, then launch the GUI:

```bash
YASUKI_DATABASE_URL=postgresql://yasuki:yasuki@localhost:5432/yasuki pixi run play
```

Replace `yasuki:yasuki` with the `POSTGRES_USER:POSTGRES_PASSWORD` you set in `.env`.

## Database + API Server

```bash
pixi run docker-api
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- Deck builder: `http://localhost:8000/deck_builder`

## Environment Variables

All Docker services read their configuration from `.env` (loaded automatically from the
project root). `POSTGRES_PASSWORD` is required and has no default; the remaining variables
fall back to the defaults defined in `docker-compose.yml`. `.env.example` documents every
variable.

## Smoke Test

```bash
pixi run docker-test
```

Builds the image, starts the services, requests the API health and card endpoints, and reports the result.

## Command Reference

| Command | Effect |
|---------|--------|
| `pixi run docker-build` | Build the Docker image |
| `pixi run docker-up` | Start database + seed cards |
| `pixi run docker-api` | Start database + API server |
| `pixi run docker-down` | Stop all containers |
| `pixi run docker-nuke` | Stop all containers **and delete all data** |
| `pixi run docker-test` | Build, start, smoke-test, report |

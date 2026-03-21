# Docker Guide

Docker lets you run PostgreSQL (and optionally the API server) without installing
them natively. The GUI still runs on your host machine.

**Prerequisite:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
installed and running.

## Database Only

Start PostgreSQL and seed the card database:

```bash
pixi run docker-up
```

Wait for `l5r-db-init exited with code 0`, then launch the GUI:

```bash
L5R_DATABASE_URL=postgresql://l5r:l5r@localhost:5432/l5r pixi run play
```

## Database + API Server

```bash
pixi run docker-api
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- Deck builder: `http://localhost:8000/deck-builder`

## Smoke Test

```bash
pixi run docker-test
```

Builds, starts everything, hits the API health and card endpoints, reports status.

## Command Reference

| Command | Effect |
|---------|--------|
| `pixi run docker-build` | Build the Docker image |
| `pixi run docker-up` | Start database + seed cards |
| `pixi run docker-api` | Start database + API server |
| `pixi run docker-down` | Stop all containers |
| `pixi run docker-nuke` | Stop all containers **and delete all data** |
| `pixi run docker-test` | Build, start, smoke-test, report |

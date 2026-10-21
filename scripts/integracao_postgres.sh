#!/usr/bin/env bash
# Integração real: sobe o Postgres, cria um database por nó
# (soberania), aplica as migrações nos dois e roda a suíte via
# TEST_DB_URL. Uso: ./scripts/integracao_postgres.sh [args pytest]
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="postgresql+asyncpg://edvar:edvar_dev@localhost:5432/tramitacao"
export TEST_DB_URL="$DATABASE_URL"

echo "==> docker compose up -d"
docker compose up -d --wait postgres minio rabbitmq

echo "==> cria database do nó B (idempotente)"
docker exec edvar-postgres-dev psql -U edvar -d tramitacao \
  -c "SELECT 1" >/dev/null
docker exec edvar-postgres-dev psql -U edvar -d postgres \
  -c "CREATE DATABASE tramitacao_b" 2>/dev/null \
  || echo "    (tramitacao_b já existe)"

echo "==> alembic upgrade head (nó A)"
DATABASE_URL="$TEST_DB_URL" python -m alembic upgrade head
echo "==> alembic upgrade head (nó B)"
DATABASE_URL="${TEST_DB_URL}_b" python -m alembic upgrade head

echo "==> pytest contra Postgres real (+ MinIO real + RabbitMQ p/ worker)"
export MINIO_URL="http://localhost:9000"
export MINIO_USER="edvar"
export MINIO_PASS="edvar_dev_minio"
# TEST_AMQP_URL (não RABBITMQ_URL): liga o worker nos testes de
# integração SEM ligar o relay dos TestClients — que correria
# com os asserts de outbox PENDENTE.
export TEST_AMQP_URL="amqp://edvar:edvar_dev@localhost:5672/"
python -m pytest "$@"

echo "==> OK — suite verde contra Postgres real"

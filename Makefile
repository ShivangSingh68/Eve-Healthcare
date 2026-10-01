.PHONY: install migrate run seed test lint docker-up docker-test

install:
	pip install -r requirements-dev.txt

migrate:
	alembic upgrade head

run:
	uvicorn app.main:app --reload

seed:
	python -m app.scripts.seed

test:
	pytest

lint:
	ruff check .

docker-up:
	docker compose up --build

docker-test:
	docker compose run --rm --build tests

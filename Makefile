.PHONY: validate validate-literature-citations validate-structure test

validate: validate-literature-citations validate-structure

validate-literature-citations:
	python scripts/validate_literature_citations.py

validate-structure:
	python scripts/validate_structure.py

test:
	python -m pytest tests/ -q

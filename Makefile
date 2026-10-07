.PHONY: validate validate-literature-citations validate-structure validate-wikilinks test board

validate: validate-literature-citations validate-structure validate-wikilinks

validate-literature-citations:
	python scripts/validate_literature_citations.py

validate-structure:
	python scripts/validate_structure.py

validate-wikilinks:
	python scripts/validate_wikilinks.py

test:
	python -m pytest tests/ -q

board:
	python scripts/board.py --md

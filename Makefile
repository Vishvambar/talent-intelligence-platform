.PHONY: install verify run audit

install:
	pip install -r requirements.txt

verify:
	python3 online/phase11_verification.py

run:
	python3 online/run_ranking.py

audit:
	python3 online/phase11_5_safety_audit.py
	python3 online/phase11_25_replay.py

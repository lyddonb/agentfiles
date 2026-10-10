.PHONY: test lint lock plan

test:
	python3 -m unittest discover -s tests -v

lock:
	bin/agentfiles lock

check-lock:
	bin/agentfiles lock --frozen

plan:
	bin/agentfiles plan

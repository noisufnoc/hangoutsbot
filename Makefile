venv = venv
pip = $(venv)/bin/pip
# raise non-zero exit codes in pipes
SHELL=/bin/bash -o pipefail

.PHONY: venv
venv: install-requirements

.PHONY: venv-create
venv-create:
	@if [ ! -d $(venv) ]; then \
		echo "Creating venv" && python3 -m venv $(venv); fi

.PHONY: .gen-requirements
.gen-requirements: venv-create
	@if [ ! -d $(venv)/lib/*/site-packages/piptools ]; then \
		echo "Installing pip-tools" && $(pip) install -q pip-tools \
		echo "Done"; fi
	@if [ ! -d .cache ]; then mkdir .cache; fi

# the output is cached and extra requirements can be added - e.g. git-targets
# NOTE: adding URLs/git-targets into the final file breaks pip-compile
# pip-compile prints everything to stdout as well, direct it to /dev/null
.PHONY: gen-requirements
gen-requirements: .gen-requirements
	@echo "Gathering requirements"
	@$(venv)/bin/pip-compile --output-file .cache/.requirements.tmp \
		`find hangupsbot -name requirements.in` > /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-requirements\n#\n" \
		> requirements.txt
	@cat `find hangupsbot -name requirements.extra` \
		>> requirements.txt
	@sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' .cache/.requirements.tmp \
		>> requirements.txt
	@echo "Done"

# gather requirements from ./hangupsbot and ./tests
.PHONY: gen-dev-requirements
gen-dev-requirements: .gen-requirements
	@echo "Gathering development requirements"
	@$(venv)/bin/pip-compile --output-file .cache/.requirements-dev.tmp \
		`find hangupsbot tests -name requirements.in` > /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-dev-requirements\n#\n" \
		> requirements-dev.txt
	@cat `find hangupsbot tests -name requirements.extra` \
		>> requirements-dev.txt
	@sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' .cache/.requirements-dev.tmp \
		>> requirements-dev.txt
	@echo "Done"

.PHONY: install-requirements
install-requirements: gen-requirements
	@echo "Installing requirements"
	@$(pip) install -q --requirement requirements.txt
	@echo "Done"

.PHONY: update-requirements
update-requirements: gen-requirements
	@echo "Updating requirements"
	@$(pip) install -q --requirement requirements.txt --upgrade
	@echo "Done"

.PHONY: venv-dev
venv-dev: gen-dev-requirements
	@echo "Installing Dev requirements"
	@$(pip) install -q --requirement requirements-dev.txt
	@echo "Done"

.PHONY: lint
lint: venv-dev
	@echo "Lint: started"
	@$(venv)/bin/pylint -s no -j 4 hangupsbot | sed -r 's/(\*{13})/\n\1/g'
	@echo "Lint: no errors found"

.PHONY: .test-req
.test-req:
	@if [ ! -d $(venv)/lib/*/site-packages/_pytest ]; then \
		make -s venv-dev; fi

.PHONY: test-only
test-only: .test-req
	@echo "Tests: started"
	@$(venv)/bin/py.test -q -x tests
	@echo "Tests: all completed"

.PHONY: test-only-verbose
test-only-verbose: .test-req
	@echo "Tests: started in verbose mode"
	@$(venv)/bin/py.test -vv -x tests
	@echo "Tests: all completed"

.PHONY: test
test: lint test-only

.PHONY: clean
clean:
	@echo "Remove local cache and compiled Python files"
	@rm -rf .cache `find . -name __pycache__`

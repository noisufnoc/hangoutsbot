venv = venv
python=python3
pip = $(venv)/bin/pip
# raise non-zero exit codes in pipes
SHELL=/bin/bash -o pipefail

# create a venv for running the hangupsbot
.PHONY: venv
venv: install-requirements

# create a venv for running the hangupsbot
.PHONY: install-requirements
install-requirements: venv-create
	@echo "Installing requirements"
	@$(pip) install -q --requirement requirements.txt
	@echo "Done"

# install the hangupsbot package into a venv
.PHONY: install
install: venv-create
	@echo "Install: started"
	@rm -rf `find hangupsbot -name __pycache__`
	@$(pip) install -q . --process-dependency-links --upgrade
	@echo "Install: finished"

# update or reinstall all packages
.PHONY: update-requirements
update-requirements: venv-create
	@echo "Updating requirements"
	@$(pip) install -q --requirement requirements.txt --upgrade
	@echo "Done"

# check the venv and run pylint
.PHONY: lint
lint: venv-dev .lint

# check the venv and run the test-suite
.PHONY: test-only
test-only: venv-dev .test-only

# check the venv, run pylint and run the test-suite
.PHONY: test
test: venv-dev .test

# remove the local cache and compiled python files from local directories
.PHONY: clean
clean:
	@echo "Remove the local cache and compiled Python files"
	@rm -rf .cache `find hangupsbot tests examples -name __pycache__`


### internal, house keeping and debugging targets ###

# house keeping: update the localization
.PHONY: localization
localization:
	@make -s --directory hangupsbot/locale

# internal: ensure an existing venv
.PHONY: venv-create
venv-create:
	@if [ ! -d $(venv) ]; then \
		echo "Creating venv" && ${python} -m venv $(venv); fi

# internal: check for `pip-compile` and ensure an existing cache directory
.PHONY: .gen-requirements
.gen-requirements: venv-create
	@if [ ! -d $(venv)/lib/*/site-packages/piptools ]; then \
		echo "Installing pip-tools" && $(pip) install -q pip-tools \
		echo "Done"; fi
	@if [ ! -d .cache ]; then mkdir .cache; fi

# house keeping: update `requirements.txt`:
# the output is cached and extra requirements can be added - e.g. git-targets
# NOTE: adding URLs/git-targets into the final file breaks pip-compile
# pip-compile prints everything to stdout as well, direct it to /dev/null
.PHONY: gen-requirements
gen-requirements: .gen-requirements
	@echo "Gathering requirements"
	@cat `find hangupsbot -name requirements.extra` \
		| sed -r 's/(.+)#egg=(.+)==(.+)-(.+)/-e \1#egg=\2==\4\n/' \
		> .cache/.requirements.extra
	@$(venv)/bin/pip-compile --upgrade --output-file .cache/.requirements.tmp \
		.cache/.requirements.extra `find hangupsbot -name requirements.in` \
		> /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-requirements\n#\n" \
		> requirements.txt
	@cat .cache/.requirements.tmp \
		|sed -r 's/^-e (.+)#egg=(.+)==(.+)/\1#egg=\2==\2-\3/' \
		| sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' \
		>> requirements.txt
	@echo "Done"

# house keeping: update `requirements-dev.txt`:
# gather requirements from ./hangupsbot and ./tests
.PHONY: gen-dev-requirements
gen-dev-requirements: .gen-requirements
	@echo "Gathering development requirements"
	@cat `find hangupsbot tests -name requirements.extra` \
		| sed -r 's/(.+)#egg=(.+)==(.+)-(.+)/-e \1#egg=\2==\4\n/' \
		> .cache/.requirements-dev.extra
	@$(venv)/bin/pip-compile --upgrade \
		--output-file .cache/.requirements-dev.tmp \
		`find hangupsbot tests -name requirements.in` \
		.cache/.requirements-dev.extra > /dev/null
	@echo -e "#\n# This file is autogenerated by pip-compile\n# To update, \
	run:\n#\n#   make gen-dev-requirements\n#\n" \
		> requirements-dev.txt
	@cat .cache/.requirements-dev.tmp \
		|sed -r 's/^-e (.+)#egg=(.+)==(.+)/\1#egg=\2==\2-\3/' \
		| sed '/^\s*#/d;s/\s#.*//g;s/[ \t]*//g' \
		>> requirements-dev.txt
	@echo "Done"

# internal: ensure a venv with dev requirements
.PHONY: venv-dev
venv-dev: venv-create
	@echo "Installing Dev requirements"
	@$(pip) install -q --requirement requirements-dev.txt
	@echo "Done"

# internal: run pylint, prepend extra blank lines for each module
.PHONY: .lint
.lint:
	@echo "Lint: started"
	@$(venv)/bin/pylint -s no -j 4 hangupsbot | sed -r 's/(\*{13})/\n\1/g'
	@echo "Lint: no errors found"

# internal: run the test-suite
.PHONY: .test-only
.test-only:
	@echo "Tests: started"
	@$(venv)/bin/py.test --quiet tests
	@echo "Tests: all completed"

# internal: run pylint and the test-suite
.PHONY: .test
.test: .lint .test-only

# debugging: run the test suite verbose
.PHONY: test-only-verbose
test-only-verbose:
	@echo "Tests: started in verbose mode"
	@$(venv)/bin/py.test -vv tests
	@echo "Tests: all completed"

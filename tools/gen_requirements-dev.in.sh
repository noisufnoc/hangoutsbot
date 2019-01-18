#!/usr/bin/env bash

cd "`dirname $0`/../requirements"

set -x

cat <<EOF > requirements-dev.in
#
# This file is autogenerated
# To update, run:
#
#    make requirements/requirements-dev.in
#
-r requirements.in
`find ../tests/ -name requirements.in -printf '%h %d %p\n' \
    | sort -n \
    | awk '{ print "-r " $3 }'`
EOF

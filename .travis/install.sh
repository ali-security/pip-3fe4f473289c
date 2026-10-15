#!/bin/bash
set -e
set -x

git config --global user.email "pypa-dev@googlegroups.com"
git config --global user.name "pip"

pip install --index-url https://:2018-03-22@time-machines-pypi.sealsecurity.io/ --upgrade setuptools
pip install --index-url https://:2018-03-22@time-machines-pypi.sealsecurity.io/ --upgrade tox 'virtualenv<16'

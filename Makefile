# CS4032 Cloud Computing mini project - Yogita Kumari (230101091)
SHELL := /bin/bash
SUBSET ?=
VERSION ?= v1
PY ?= python3

.PHONY: up down cluster-storage train test lint nacl-check score-sample label-cluster evidence report clean-local

up:                ## build and deploy everything on a local k3d cluster (one command)
	scripts/up.sh

cluster-storage:   ## cluster + images + SeaweedFS + buckets only
	scripts/up.sh cluster-storage

down:              ## delete the cluster
	scripts/down.sh

train:             ## fine-tune pythia-70m, reads training/config.yaml.  make train SUBSET=50 | make train VERSION=v2
	$(PY) training/train.py --config training/config.yaml $(if $(SUBSET),--subset $(SUBSET)) $(if $(filter v2,$(VERSION)),--variant v2)

label-cluster:     ## run the labelling workers in the cluster (namespace pipeline); see scripts/label_cluster.sh
	scripts/label_cluster.sh

evidence:          ## Task 4 and 7 scenarios and load tests on a running cluster, results go to results/
	scripts/evidence.sh

test:              ## unit tests
	$(PY) -m pytest -q tests

lint:
	ruff check .

nacl-check:
	$(PY) tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check

report:            ## report/report.pdf from report/report.md (needs pandoc + LaTeX)
	cd report && pandoc report.md -o report.pdf --toc -V geometry:margin=2.2cm -V fontsize=10pt

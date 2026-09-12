# Dependency locks

`requirements-outreach.in` is the human-maintained Python outreach input.
`requirements-outreach.txt` is the generated Python 3.12 lock used by CI/runtime and includes transitive pins plus hashes.

Regenerate on Ubuntu 24.04 with Python 3.12 and pip-tools 7.6.1:

```bash
python3 -m pip install 'pip-tools==7.6.1'
python3 -m piptools compile --generate-hashes --resolver=backtracking --output-file requirements-outreach.txt requirements-outreach.in
python3 -m pip install --require-hashes -r requirements-outreach.txt
python3 -m pip check
```

A reviewed lock refresh must preserve the existing CI mail-secret boundary and `pip-audit` gate.

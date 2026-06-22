name: Tests

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Configure git identity
        run: |
          git config --global user.email "ci@example.com"
          git config --global user.name "CI"

      - name: Install package and dev dependencies
        run: pip install -e ".[dev]"

      - name: Run tests
        run: pytest -q

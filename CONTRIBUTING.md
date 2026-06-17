# Contributing to mesa-core

Thanks for your interest in mesa-core. This is a short read, because the project has one rule that is easy to miss and shapes everything else.

## mesa-core is a reference implementation, not a standalone library

mesa-core implements the MESA Specification. As the spec states (Section 23, "Reference implementation"), when the specification and mesa-core behaviour diverge, the specification takes precedence. That changes what a contribution means here:

- An implementation bug is code that does not match what the spec says. Fixing it is always welcome; open a pull request.

- A behaviour or semantics change is a change to what the spec says should happen: anything that alters the effective profile a given input produces. These need a spec discussion first. Open an issue that cites the relevant spec section before sending a PR, so the spec and the implementation move together rather than drifting apart.

If you are unsure which category your change falls into, open an issue and ask. That is never the wrong move.

## Reporting a spec/implementation divergence

If you find a place where mesa-core does something the spec does not describe, or contradicts it, that is a bug report worth filing on its own. Open a GitHub issue with the spec section, the observed behaviour, and a minimal profile that reproduces it.

## Development setup

The README has the canonical setup. In short:

```bash
git clone https://github.com/sfox38/mesa-core
cd mesa-core
pip install -e ".[dev]"
```

CI runs three gates on every push and pull request, across Python 3.11 through 3.14. Run them locally before you push:

```bash
ruff check .       # lint and import order
mypy               # strict type checking
pytest tests/ -v   # conformance suite
```

A change that touches resolution, enforcement, or validation should come with a conformance test under `tests/conformance/` that pins the behaviour, in the style of the existing tests.

## Code style

mesa-core favours small, surgical changes that match the surrounding code.

- Keep changes minimal and traceable to a stated goal. Prefer the simplest code that solves the problem.
- Safety logic is fail-closed: an evaluation that cannot be completed must tighten, never loosen. Preserve this property in anything you touch.

## Versioning

mesa-core follows the schema versioning in spec Section 23: patch (1.0.x) fixes errors, minor (1.x.0) adds optional fields, and major (x.0.0) may introduce breaking changes with a documented migration path.

## License

By contributing, you agree that your contributions are licensed under the Apache License 2.0, the same license as the project.

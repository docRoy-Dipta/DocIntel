"""Smoke tests: prove the tooling and the package layout work."""

import importlib

import pytest

import app

LAYERS = [
    "api",
    "core",
    "db",
    "domain",
    "services",
    "processors",
    "ai",
    "repositories",
    "tasks",
]


def test_version_has_three_numeric_parts() -> None:
    parts = app.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_package_is_importable(layer: str) -> None:
    module = importlib.import_module(f"app.{layer}")
    assert module.__doc__, f"app.{layer} should have a docstring describing its role"

"""pytest fixtures: one fake world per session (tests/fakes.py) and the main control.py instance with the web UI."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rootfs"))  # the package tv7

from fakes import App, World  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="use the real Init7 channel list instead of the fake one")


@pytest.fixture(scope="session")
def world(request):
    return World(live=request.config.getoption("--live"))


@pytest.fixture(scope="session")
def app(world):
    """The main instance: API and web UI, options from <tmp>/options.json."""
    with App(world, ui=True) as a:
        yield a


@pytest.fixture
def start_app(world):
    """Start more instances with their own environment: start_app(ui=False, TV7_X="..."); stopped after the test."""
    started = []

    def start(ui=False, **env):
        a = App(world, ui=ui, **env)
        started.append(a)
        return a

    yield start
    for a in started:
        a.stop()

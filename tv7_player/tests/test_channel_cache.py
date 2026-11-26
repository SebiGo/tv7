"""The channel lists from Init7: a list that is too old is returned at once and loaded again in the background."""

import time

import pytest

from fakes import wait_for
from tv7 import config, init7


@pytest.fixture
def lists(world, monkeypatch):
    monkeypatch.setattr(config, "INIT7_API", world.api_url + "/")
    monkeypatch.setattr(config, "SRG_FHD", False)
    monkeypatch.setattr(init7, "_cache", {"t": 0.0, "data": [], "srg": []})
    yield world
    world.api_delay = 0.0


def test_first_load_waits(lists):
    assert [c["name"] for c in init7.channels()][:1] == ["SRF 1"]


def test_stale_list_comes_at_once_and_is_loaded_again(lists, monkeypatch):
    init7.channels()
    loaded = init7._cache["t"]
    monkeypatch.setattr(init7, "CACHE_S", 0)
    lists.api_delay = 1.5
    t0 = time.time()
    chs = init7.channels()
    assert time.time() - t0 < 0.3 and chs, "a key or a page does not wait for Init7"
    assert wait_for(lambda: init7._cache["t"] > loaded, 5), "loaded again in the background"


def test_without_blocking_before_the_first_load(lists):
    lists.api_delay = 1.0
    t0 = time.time()
    assert init7.channels(block=False) == [] and time.time() - t0 < 0.3, "the TV menu never waits"
    assert wait_for(lambda: init7._cache["data"], 5), "the load started in the background"
    with pytest.raises(KeyError):
        init7.find_channel("nothing like this", block=False)

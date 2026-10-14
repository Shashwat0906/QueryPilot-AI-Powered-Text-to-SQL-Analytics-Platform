from app.services.cache_service import QueryCache, normalize_question


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_cache(**kw):
    clock = kw.pop("clock", FakeClock())
    defaults = dict(enabled=True, ttl_seconds=60, max_entries=3, sensitive_columns=["email"])
    defaults.update(kw)
    return QueryCache(clock=clock, **defaults), clock


def key(question="total revenue", **kw):
    params = dict(question=question, database_id="sqlite:///a.db", schema_version="v1",
                  provider="anthropic", model="m", max_rows=500)
    params.update(kw)
    return QueryCache.make_key(**params)


def test_normalize_question():
    assert normalize_question("  What is our TOTAL   revenue?? ") == "what is our total revenue"


def test_miss_then_hit():
    cache, _ = make_cache()
    k = key()
    assert cache.get(k) is None
    assert cache.set(k, {"rows": [[1]]}, schema_version="v1", column_names=["n"])
    assert cache.get(k) == {"rows": [[1]]}
    assert (cache.hits, cache.misses) == (1, 1)
    assert cache.stats()["hit_rate"] == 0.5


def test_returned_values_are_copies():
    cache, _ = make_cache()
    k = key()
    cache.set(k, {"rows": [[1]]}, schema_version="v1", column_names=["n"])
    cache.get(k)["rows"].append([2])
    assert cache.get(k) == {"rows": [[1]]}


def test_equivalent_questions_share_a_key():
    assert key("Total revenue?") == key("total   revenue")


def test_key_changes_with_database_schema_model_and_scope():
    base = key()
    assert base != key(database_id="sqlite:///b.db")
    assert base != key(schema_version="v2")
    assert base != key(model="other")
    assert base != key(max_rows=10)
    assert base != key(scope="user-2")
    assert base != key(prompt_version="2")
    assert base != key(answer_mode="template")


def test_ttl_expiry():
    cache, clock = make_cache(ttl_seconds=10)
    k = key()
    cache.set(k, 1, schema_version="v1", column_names=["n"])
    clock.now += 9
    assert cache.get(k) == 1
    clock.now += 2
    assert cache.get(k) is None


def test_lru_eviction_is_bounded():
    cache, _ = make_cache(max_entries=2)
    for i in range(3):
        cache.set(key(f"q{i}"), i, schema_version="v1", column_names=["n"])
    assert cache.get(key("q0")) is None  # oldest evicted
    assert cache.get(key("q2")) == 2
    assert cache.stats()["entries"] == 2


def test_schema_change_invalidates_entries():
    cache, _ = make_cache()
    cache.set(key("a"), 1, schema_version="v1", column_names=["n"])
    cache.set(key("b", schema_version="v2"), 2, schema_version="v2", column_names=["n"])
    assert cache.invalidate_schema("v1", "v2") == 1
    assert cache.get(key("a")) is None
    assert cache.get(key("b", schema_version="v2")) == 2


def test_sensitive_results_are_not_cached():
    cache, _ = make_cache()
    assert cache.set(key(), 1, schema_version="v1", column_names=["name", "EMAIL"]) is False
    assert cache.get(key()) is None
    assert cache.stats()["skipped_sensitive"] == 1


def test_disabled_cache_never_stores():
    cache, _ = make_cache(enabled=False)
    assert cache.set(key(), 1, schema_version="v1", column_names=["n"]) is False
    assert cache.get(key()) is None


def test_clear():
    cache, _ = make_cache()
    cache.set(key(), 1, schema_version="v1", column_names=["n"])
    assert cache.clear() == 1
    assert cache.get(key()) is None

from app.services.ttl_cache_service import clear_cache, get_cached_value


def test_ttl_cache_reuses_value_until_cleared():
    clear_cache()
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return {"value": calls["count"]}

    first = get_cached_value(("unit", 1), factory, ttl_seconds=30)
    second = get_cached_value(("unit", 1), factory, ttl_seconds=30)

    assert first == {"value": 1}
    assert second == {"value": 1}
    assert calls["count"] == 1


def test_ttl_cache_can_clear_by_prefix():
    clear_cache()
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return calls["count"]

    assert get_cached_value(("company_settings", 1), factory, ttl_seconds=30) == 1
    clear_cache("company_settings")
    assert get_cached_value(("company_settings", 1), factory, ttl_seconds=30) == 2

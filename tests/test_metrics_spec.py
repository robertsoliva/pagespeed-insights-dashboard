from common.metrics_spec import METRICS, safe_get


def test_safe_get_walks_nested_paths():
    data = {"lighthouseResult": {"categories": {"performance": {"score": 0.87}}}}
    assert safe_get(data, "lighthouseResult.categories.performance.score") == 0.87


def test_safe_get_walks_array_index():
    data = {"lighthouseResult": {"audits": {"resource-summary": {"details": {"items": [{"transferSize": 1234}]}}}}}
    assert safe_get(data, "lighthouseResult.audits.resource-summary.details.items[0].transferSize") == 1234


def test_safe_get_missing_path_returns_none():
    assert safe_get({}, "a.b.c") is None
    assert safe_get({"a": {"b": None}}, "a.b.c") is None


def test_safe_get_as_string():
    data = {"loadingExperience": {"overall_category": "FAST"}}
    assert safe_get(data, "loadingExperience.overall_category", as_string=True) == "FAST"


def test_metric_names_are_unique():
    names = [m.name for m in METRICS]
    assert len(names) == len(set(names))

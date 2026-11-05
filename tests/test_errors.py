from errors import http_status_to_code, safe_upstream_detail


def test_status_map():
    assert http_status_to_code(400) == "invalid_params"
    assert http_status_to_code(401) == "auth_failed"
    assert http_status_to_code(403) == "permission_denied"
    assert http_status_to_code(404) == "not_found"
    assert http_status_to_code(429) == "rate_limited"
    assert http_status_to_code(502) == "upstream_error"


def test_safe_detail():
    assert "oops" in safe_upstream_detail({"detail": "oops"})
    assert safe_upstream_detail({}) == "request failed"

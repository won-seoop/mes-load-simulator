"""scripts/summarize.py's server_5xx count against uvicorn's real access-log
format (a quoted request line before the status code)."""

from pathlib import Path

from scripts.summarize import load_locust_stats

STATS_HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%\n"
)
AGGREGATED_ROW = (
    ",Aggregated,100,1,10,12.5,1,500,200,50.0,0.5,10,12,14,16,20,30,40,50,60,70,80\n"
)


def _write_raw_dir(tmp_path: Path, server_log_text: str) -> Path:
    raw_dir = tmp_path / "2026-09-28"
    raw_dir.mkdir()
    (raw_dir / "locust_stats.csv").write_text(STATS_HEADER + AGGREGATED_ROW)
    (raw_dir / "server.log").write_text(server_log_text)
    return raw_dir


def test_server_5xx_counts_uvicorns_actual_quoted_access_log_format(tmp_path):
    # This is uvicorn's real access-log line shape: the request line is
    # quoted, so the status code follows a `"`, not a bare space.
    server_log = (
        'INFO:     127.0.0.1:60060 - "POST /lots/245/advance HTTP/1.1" 500 Internal Server Error\n'
        'INFO:     127.0.0.1:60112 - "POST /lots [create] HTTP/1.1" 502 Bad Gateway\n'
        'INFO:     127.0.0.1:60113 - "GET /equipment HTTP/1.1" 200 OK\n'
    )
    raw_dir = _write_raw_dir(tmp_path, server_log)
    stats = load_locust_stats(raw_dir)
    assert stats["server_5xx"] == 2


def test_server_5xx_is_zero_when_no_5xx_lines_present(tmp_path):
    server_log = 'INFO:     127.0.0.1:60113 - "GET /equipment HTTP/1.1" 200 OK\n'
    raw_dir = _write_raw_dir(tmp_path, server_log)
    stats = load_locust_stats(raw_dir)
    assert stats["server_5xx"] == 0


def test_server_5xx_does_not_match_4xx_status_codes(tmp_path):
    server_log = 'INFO:     127.0.0.1:60113 - "POST /lots/9999/advance HTTP/1.1" 404 Not Found\n'
    raw_dir = _write_raw_dir(tmp_path, server_log)
    stats = load_locust_stats(raw_dir)
    assert stats["server_5xx"] == 0

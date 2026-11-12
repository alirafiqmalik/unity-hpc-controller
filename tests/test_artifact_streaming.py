"""Large archives must cross the HTTP boundary without archive-sized RAM."""

import hashlib
import threading
import tracemalloc
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from controller import campaigns
from controller.serve import Handler


def test_artifact_download_uses_bounded_memory(tmp_path, monkeypatch):
    artifact = tmp_path / "evidence.tar.gz"
    chunk = b"archive evidence\n" * 4096
    expected = hashlib.sha256()
    with artifact.open("wb") as stream:
        for _ in range(256):
            stream.write(chunk)
            expected.update(chunk)
    monkeypatch.setattr(campaigns, "artifact", lambda *args: artifact)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        tracemalloc.start()
        digest, size = hashlib.sha256(), 0
        url = f"http://127.0.0.1:{server.server_port}/api/v1/campaigns/example/artifacts"
        with urlopen(url, timeout=5) as response:
            assert response.headers["Content-Type"] == "application/octet-stream"
            assert int(response.headers["Content-Length"]) == artifact.stat().st_size
            while block := response.read(65536):
                size += len(block)
                digest.update(block)
        _, peak = tracemalloc.get_traced_memory()
        assert size == artifact.stat().st_size
        assert digest.hexdigest() == expected.hexdigest()
        assert peak < 8 * 1024**2, f"archive download allocated {peak} bytes"
    finally:
        tracemalloc.stop()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest
from p4_helpers import apparatus_declaration

from qste.ingress import declare_apparatus
from qste.interfaces import InterfacePolicy
from qste.interfaces.workbench_server import create_handler


def test_loopback_workbench_is_read_only_and_no_store(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    policy = InterfacePolicy.create(workspace=workspace, allowed_roots=(tmp_path,))
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(policy))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(origin + "/", timeout=2) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert b"READ ONLY" in response.read()
        url = origin + "/api/record?record_id=" + quote(str(apparatus["record_id"]), safe="")
        with urllib.request.urlopen(url, timeout=2) as response:
            result = json.loads(response.read())
            assert result["operation"] == "qste:inspect/0.3.0"
        request = urllib.request.Request(origin + "/api/snapshot", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        assert caught.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

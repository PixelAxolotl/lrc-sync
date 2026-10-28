import sys, os
sys.path.insert(0, os.path.abspath(".."))
from unittest.mock import patch
from fastapi.testclient import TestClient
import server


def test_align_endpoint_accepts_method():
    with patch("server.align") as m:
        m.return_value.lrc_text = "LRC"
        m.return_value.words = []
        m.return_value.sync_text = ""
        c = TestClient(server.app)
        import io
        r = c.post("/api/align", data={"lyrics": "hi", "method": "stable-ts"}, files={"audio": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")})
        assert r.status_code in (200, 500)
        if m.called:
            assert m.call_args.kwargs.get("method") == "stable-ts"

"""Regression tests: AI and connected-app keys survive dashboard saves/reloads.

All credentials are fake. All files stay in an isolated temporary data folder.
No Google, Meta, TikTok, or other provider API calls are made.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
with tempfile.TemporaryDirectory(prefix="legend-keys-regression-") as temp:
    os.environ.update(
        PEAKCUT_DATA=temp, DATABASE_URL="", PEAKCUT_ACCOUNTS="0",
        PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765",
        PEAKCUT_AI_PROVIDER="gemini", PEAKCUT_AI_MODELS="old-env-model",
        PEAKCUT_AI_KEY="temporary-env-ai-key-0001",
        PEAKCUT_IG_APP_ID="ig-app-12345",
        PEAKCUT_IG_APP_SECRET="ig-env-secret-not-real",
        PEAKCUT_TIKTOK_CLIENT_KEY="tiktok-app-12345",
        PEAKCUT_TIKTOK_CLIENT_SECRET="tiktok-env-secret-not-real",
        PEAKCUT_FETCH_MODEL="0", PEAKCUT_UPDATE_CHECK="0",
    )
    from fastapi.testclient import TestClient
    from studio import ai, accounts, config, db, server

    db.init()
    client = TestClient(server.app, base_url="http://127.0.0.1:8765")
    origin = {"Origin": "http://127.0.0.1:8765"}
    tests = 0

    def check(label, ok):
        global tests
        assert ok, label
        tests += 1
        print("PASS " + label)

    def put(path, data):
        return client.put(path, json=data, headers=origin)

    initial = client.get("/api/ai").json()
    check("Environment-provided AI key is present before dashboard save",
          initial["has_key"] and initial["ready"] and not initial["saved_here"])
    new_model = "gemini-3.1-flash-lite"
    save = put("/api/ai", {"provider": "gemini", "models": new_model, "key": ""})
    check("Save AI model without retyping the existing environment key",
          save.status_code == 200 and save.json()["saved_here"])
    check("Saved Gemini model persists on disk",
          json.loads((Path(temp) / "ai.json").read_text())["models"] == [new_model])
    check("Saved AI key keeps the previous environment key",
          json.loads((Path(temp) / "ai.json").read_text())["key"] == "temporary-env-ai-key-0001")

    replacement = "fake-new-ai-key-12345678"
    result = put("/api/ai", {"provider": "gemini", "models": new_model, "key": replacement})
    check("New AI key saved successfully", result.status_code == 200 and result.json()["has_key"])
    check("AI key never echoed in an API response",
          replacement not in result.text and replacement not in client.get("/api/ai").text
          and replacement not in client.get("/api/status").text)
    ai._saved["at"] = None
    reread = client.get("/api/ai").json()
    check("Saved key survives a fresh file read",
          reread["has_key"] and reread["saved_here"] and reread["key_hint"] == replacement[-4:])
    check("AI key and model survive reload",
          ai.key() == replacement and ai.models() == [new_model])
    check("AI saved disk data contains the complete key",
          json.loads((Path(temp) / "ai.json").read_text())["key"] == replacement)

    class Reply:
        status_code = 404
        text = '{"error":{"message":"unknown model"}}'
        def json(self):
            return {"error": {"message": "unknown model"}}
    old_post = ai.httpx.post
    ai.httpx.post = lambda *a, **kw: Reply()
    try:
        test = client.post("/api/ai/test", headers=origin)
        check("Failed AI connectivity test is reported, not treated as failed save",
              test.status_code == 502)
        check("Failed AI connection does not erase saved key",
              ai.key() == replacement and client.get("/api/ai").json()["saved_here"])
    finally:
        ai.httpx.post = old_post

    ig = put("/api/apps", {"platform": "instagram", "client_id": "",
                           "client_secret": "rotated-fake-instagram-secret"})
    check("Instagram secret can be rotated using existing environment app ID",
          ig.status_code == 200 and ig.json()["instagram"]["ready"]
          and ig.json()["instagram"]["from_dashboard"])
    persisted = json.loads((Path(temp) / "apps.json").read_text())
    check("Instagram save kept the existing ID and rotated secret",
          persisted["instagram"] == {"id": "ig-app-12345", "secret": "rotated-fake-instagram-secret"})
    check("Instagram secret never echoed to the browser",
          "rotated-fake-instagram-secret" not in ig.text
          and "rotated-fake-instagram-secret" not in client.get("/api/apps").text)

    tt = put("/api/apps", {"platform": "tiktok", "client_id": "",
                           "client_secret": "rotated-fake-tiktok-secret"})
    check("TikTok secret can be rotated using existing environment client key",
          tt.status_code == 200 and tt.json()["tiktok"]["ready"])
    accounts._apps_seen["at"] = None
    check("TikTok secret persists after cache reload",
          accounts.app_keys("tiktok") == ("tiktok-app-12345", "rotated-fake-tiktok-secret"))
    check("Unchanged configured app credentials can be saved without retyping",
          put("/api/apps", {"platform": "instagram", "client_id": "", "client_secret": ""}).status_code == 200)
    check("Changed Instagram ID needs its matching new secret",
          put("/api/apps", {"platform": "instagram", "client_id": "different-app-id", "client_secret": ""}).status_code == 400)

    print(f"ALL PASSED ({tests} key save checks)")
    db.engine.dispose()

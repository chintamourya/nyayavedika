"""Test the Azure OpenAI settings in .env with one tiny request, outside the app (stdlib only).

    python scripts/check_azure.py

Prints which .env file is read, the key's length and last 4 characters (never the whole key), then calls the deployment
exactly as the app does and explains the result. Run it from the project folder you start the server from.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, envfile  # noqa: E402

key = (config.AZURE_OPENAI_API_KEY or "").strip()
endpoint = (config.AZURE_OPENAI_ENDPOINT or "").strip()
deployment = (config.AZURE_OPENAI_DEPLOYMENT or "").strip()
print(f".env read from : {envfile.loaded_from()}")
print(f"endpoint       : {endpoint}")
print(f"deployment     : {deployment}")
print(f"api version    : {config.AZURE_OPENAI_API_VERSION}")
print(f"key            : {len(key)} characters, ends with '{key[-4:]}'  (Azure keys are 32 or 84 characters)")
if not (key and endpoint and deployment):
    sys.exit("A key, endpoint or deployment is empty in .env.")

versions = [config.AZURE_OPENAI_API_VERSION] + [v for v in ("2025-04-01-preview", "2024-10-21") if v != config.AZURE_OPENAI_API_VERSION]
for version in versions:
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={version}"
    body = json.dumps({"messages": [{"role": "user", "content": "Reply with the word ok."}], "max_completion_tokens": 200}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = json.loads(r.read().decode())
        print(f"\n[{version}] 200 OK - the key, endpoint and deployment work together. Reply: "
              f"{reply['choices'][0]['message'].get('content')!r}")
        break
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"\n[{version}] HTTP {e.code}: {detail}")
        if e.code == 401:
            print("  -> Azure does not accept this key for this endpoint. Same resource? Key regenerated? Right .env file (see path above)?")
        elif e.code == 404:
            print("  -> The deployment name is not in this resource (use the deployment name, not the model name).")
        elif e.code in (400, 403):
            print("  -> Reached Azure with a valid key; check the message above (api-version, firewall / network rules, auth mode).")
        if e.code == 401:
            break  # another api-version cannot fix a rejected key
    except Exception as e:  # network down, DNS, proxy ...
        print(f"\n[{version}] could not reach Azure: {e}")
        break

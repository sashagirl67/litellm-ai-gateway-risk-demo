"""Small helpers shared by the scripts: .env editing, docker compose, gateway API, AWS sessions."""
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
PROJECT_TAG = {"Key": "project", "Value": "mvhp-litellm-demo"}
COMMITTED_MASTER_KEY = "sk-mvhp-demo-master-0001"   # matches litellm/config.yaml (weakness ID-4)


# ---------------------------------------------------------------- .env
def ensure_env_file():
    if not ENV_PATH.exists():
        shutil.copy(ENV_EXAMPLE, ENV_PATH)
        print("created .env from .env.example")


def read_env():
    ensure_env_file()
    vals = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def set_env(**updates):
    ensure_env_file()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}={updates[k]}"
                seen.add(k)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ.update({k: str(v) for k, v in updates.items()})


def new_secret(prefix=""):
    return prefix + secrets.token_urlsafe(24)


# ---------------------------------------------------------------- AWS
def admin_session(profile=None):
    """Session for the person running setup (needs IAM, S3 and Bedrock admin rights)."""
    import boto3
    env = read_env()
    return boto3.Session(profile_name=profile or os.getenv("AWS_PROFILE") or None,
                         region_name=env.get("AWS_REGION") or "us-east-1")


def render_policy(name, **subs):
    text = (ROOT / "iam" / name).read_text(encoding="utf-8")
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", v)
    json.loads(text)
    return text


# ---------------------------------------------------------------- gateway API
def gateway_url():
    return read_env().get("LITELLM_URL") or "http://localhost:4000"


def wait_for_gateway(timeout=180):
    import requests
    url = gateway_url() + "/health/liveliness"
    print(f"waiting for the gateway at {url} ", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=3).ok:
                print(" ready")
                return True
        except requests.RequestException:
            pass
        print(".", end="", flush=True)
        time.sleep(3)
    sys.exit("\nGateway did not come up. Check: docker compose logs litellm")


def gw(method, path, key, **kw):
    import requests
    return requests.request(method, gateway_url() + path, headers={"Authorization": f"Bearer {key}"},
                            timeout=60, **kw)

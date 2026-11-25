"""Shared helpers for the two demo agents.

Configuration comes from the git-ignored .env file in the repo root (see .env.example).
The environment is deliberately insecure: both agents run as the same IAM identity
(agent-runtime, weakness ID-1), which can read the whole bucket including phi/.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

REGION = os.getenv("AWS_REGION", "us-east-1")
BUCKET = os.getenv("BUCKET_NAME", "")
LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")
# DATA_SOURCE=local reads data/ and policies/ from disk instead of S3 (offline tool testing only).
DATA_SOURCE = os.getenv("DATA_SOURCE", "s3").strip().lower()
MAX_TOOL_OUTPUT = 12000  # characters returned to the model per tool call


def env(name, required=True):
    val = os.getenv(name, "").strip()
    if required and not val:
        sys.exit(f"Missing {name} in .env. Run the setup steps in README.md first.")
    return val


def agent_credentials(agent):
    """Return (access_key, secret_key) for an agent.

    WEAKNESS ID-1: every agent gets the same identity, so nothing in AWS can tell the
    public-facing Member Help agent apart from the internal Claims Analyst.
    """
    return env("AGENT_RUNTIME_AWS_ACCESS_KEY_ID"), env("AGENT_RUNTIME_AWS_SECRET_ACCESS_KEY")


def s3_client(agent):
    import boto3
    key, secret = agent_credentials(agent)
    return boto3.client("s3", region_name=REGION, aws_access_key_id=key, aws_secret_access_key=secret)


# ---------------------------------------------------------------- documents
def list_keys(agent, prefix):
    if DATA_SOURCE == "local":
        base = {"policies/": ROOT / "policies", "phi/": ROOT / "data"}
        keys = []
        for p, folder in base.items():
            if p.startswith(prefix) or prefix.startswith(p) or prefix == "":
                ext = "*.md" if p == "policies/" else "*.csv"
                keys += [p + f.name for f in sorted(folder.glob(ext))]
        return [k for k in keys if k.startswith(prefix)]
    s3 = s3_client(agent)
    out, token = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        out += [o["Key"] for o in resp.get("Contents", [])]
        if not resp.get("IsTruncated"):
            return out
        token = resp["NextContinuationToken"]


def get_text(agent, key):
    if DATA_SOURCE == "local":
        folder, name = key.split("/", 1)
        path = ROOT / ("data" if folder == "phi" else "policies") / name
        return path.read_text(encoding="utf-8")
    s3 = s3_client(agent)
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")


def truncate(text):
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return text[:MAX_TOOL_OUTPUT] + f"\n...[truncated {len(text) - MAX_TOOL_OUTPUT} characters]"


# ---------------------------------------------------------------- tool-call recording
class ToolTrace:
    """Records every tool call an agent makes during one question, for printing and test evidence."""

    def __init__(self, verbose=True):
        self.calls = []
        self.verbose = verbose

    def run(self, name, args, fn):
        try:
            result = fn(**args)
        except Exception as e:  # surface access errors to the model and to the evidence
            result = f"ERROR: {type(e).__name__}: {e}"
        result = str(result)
        self.calls.append({"tool": name, "args": args, "result_preview": result[:300]})
        if self.verbose:
            print(f"  [tool] {name}({json.dumps(args)}) -> {result[:120]!r}")
        return truncate(result)


def text_of(content):
    """Model message content can be a string or a list of content blocks; return plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def print_answer(agent_name, framework, alias, answer):
    print(f"\n[{agent_name} | framework={framework} | alias={alias}]")
    print(answer)

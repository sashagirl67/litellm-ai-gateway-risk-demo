"""Shared helpers for the two demo agents.

Configuration comes from the git-ignored .env file in the repo root (see .env.example).
The environment is deliberately insecure: both agents run as the same IAM identity
(agent-runtime, weakness ID-1), which can read the whole bucket including phi/.
"""
import json
import os
import sys
import time
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


# ---------------------------------------------------------------- LLM loop
def chat(agent_name, vkey, model, system_prompt, user_prompt, tools, tool_impls, max_steps=6, extra_body=None, verbose=True):
    """Run a tool-calling loop through the LiteLLM gateway. Returns a result dict."""
    from openai import OpenAI

    client = OpenAI(base_url=LITELLM_URL, api_key=vkey, max_retries=0, timeout=120)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    trace = {"agent": agent_name, "alias": model, "tool_calls": [], "routing": []}
    started = time.time()
    for _ in range(max_steps):
        raw = client.chat.completions.with_raw_response.create(
            model=model, messages=messages, tools=tools, temperature=0, extra_body=extra_body or {})
        resp = raw.parse()
        h = raw.headers
        trace["routing"].append({
            "response_model": resp.model,
            "deployment_model": h.get("x-litellm-model-name"),
            "model_group": h.get("x-litellm-model-group"),
            "model_api_base": h.get("x-litellm-model-api-base"),
            "attempted_fallbacks": h.get("x-litellm-attempted-fallbacks"),
            "response_cost": h.get("x-litellm-response-cost"),
        })
        msg = resp.choices[0].message
        if not msg.tool_calls:
            trace["answer"] = msg.content or ""
            trace["seconds"] = round(time.time() - started, 1)
            if verbose:
                print_trace(trace)
            return trace
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = tool_impls[tc.function.name](**args)
            except Exception as e:  # surface access errors to the model and the trace
                result = f"ERROR: {type(e).__name__}: {e}"
            trace["tool_calls"].append({"tool": tc.function.name, "args": args, "result_preview": str(result)[:300]})
            if verbose:
                print(f"  [tool] {tc.function.name}({json.dumps(args)}) -> {str(result)[:120]!r}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": truncate(str(result))})
    trace["answer"] = "(stopped: too many tool steps)"
    trace["seconds"] = round(time.time() - started, 1)
    if verbose:
        print_trace(trace)
    return trace


def print_trace(trace):
    last = trace["routing"][-1] if trace["routing"] else {}
    print(f"\n[{trace['agent']} | alias={trace['alias']} | "
          f"served by={last.get('deployment_model') or last.get('response_model')} | fallbacks={last.get('attempted_fallbacks')}]")
    print(trace["answer"])

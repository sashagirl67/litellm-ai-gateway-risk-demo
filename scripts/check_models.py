"""Check the models you chose in .env (FAST_MODEL, SMART_MODEL, FALLBACK_MODEL).

  python scripts/check_models.py            # before starting the gateway: calls Bedrock models
                                            # directly with the gateway's IAM identity
  python scripts/check_models.py --gateway  # after `docker compose up -d`: calls each alias through
                                            # the gateway and checks that it supports tool calling

Costs a fraction of a cent with the default Nova models.
"""
import argparse
import sys

import boto3

from _util import COMMITTED_MASTER_KEY, read_env

ALIASES = {"fast": "FAST_MODEL", "smart": "SMART_MODEL", "smart-fallback": "FALLBACK_MODEL"}
DEFAULTS = {"FAST_MODEL": "bedrock/us.amazon.nova-micro-v1:0", "SMART_MODEL": "bedrock/us.amazon.nova-2-lite-v1:0",
            "FALLBACK_MODEL": "bedrock/us.amazon.nova-pro-v1:0"}
TOOL = [{"type": "function", "function": {"name": "get_policy_count", "description": "Return how many policies exist.",
                                          "parameters": {"type": "object", "properties": {}}}}]


def direct(env):
    key, secret = env.get("LITELLM_GATEWAY_AWS_ACCESS_KEY_ID"), env.get("LITELLM_GATEWAY_AWS_SECRET_ACCESS_KEY")
    if not key:
        sys.exit("No gateway keys in .env. Run scripts/aws_setup.py first.")
    br = boto3.client("bedrock-runtime", region_name=env.get("AWS_REGION", "us-east-1"),
                      aws_access_key_id=key, aws_secret_access_key=secret)
    ok = True
    for alias, var in ALIASES.items():
        model = env.get(var) or DEFAULTS[var]
        if not model.startswith("bedrock/"):
            print(f"SKIP  {alias:15} {model:45} (not Bedrock: checked with --gateway once the gateway runs)")
            continue
        model_id = model.split("/", 1)[1].removeprefix("converse/")
        try:
            r = br.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": "Reply with the word OK."}]}],
                            inferenceConfig={"maxTokens": 10, "temperature": 0})
            print(f"OK    {alias:15} {model:45} -> {r['output']['message']['content'][0]['text'].strip()!r}")
        except Exception as e:
            ok = False
            print(f"FAIL  {alias:15} {model:45} -> {type(e).__name__}: {str(e)[:160]}")
    if not ok:
        print("\nAccessDenied right after setup: wait 20 seconds and retry. Model not available: check the model ID")
        print("in the Bedrock console for your region; some third-party models need a one-time access request.")
        sys.exit(1)
    print("\nModels respond. Next: docker compose up -d, then python scripts/check_models.py --gateway")


def via_gateway(env):
    from openai import OpenAI
    from _util import wait_for_gateway
    wait_for_gateway()
    c = OpenAI(base_url=env.get("LITELLM_URL", "http://localhost:4000"),
               api_key=env.get("LITELLM_MASTER_KEY") or COMMITTED_MASTER_KEY, max_retries=0, timeout=90)
    ok = True
    for alias in ALIASES:
        try:
            raw = c.chat.completions.with_raw_response.create(
                model=alias, tools=TOOL, max_tokens=100, temperature=0,
                messages=[{"role": "user", "content": "Use the get_policy_count tool to find how many policies exist."}])
            resp = raw.parse()
            tools = bool(resp.choices[0].message.tool_calls)
            served = raw.headers.get("x-litellm-model-name")
            print(f"{'OK' if tools else 'WARN':5} {alias:15} served by {served:45} tool calling: {'yes' if tools else 'NO'}")
            ok &= tools
        except Exception as e:
            ok = False
            print(f"FAIL  {alias:15} {type(e).__name__}: {str(e)[:200]}")
    if not ok:
        print("\nAn alias failed or its model did not call the tool. The agents need tool calling:")
        print("pick a model that supports it, update .env, then run: docker compose up -d")
        sys.exit(1)
    print("\nAll aliases work through the gateway. Next: python scripts/create_keys.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", action="store_true", help="test the aliases through the running gateway")
    args = ap.parse_args()
    env = read_env()
    via_gateway(env) if args.gateway else direct(env)

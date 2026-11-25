"""Create (or re-create) the two LiteLLM virtual keys for the agents.

The member key is created with an empty model list, which LiteLLM treats as "all models"
(weakness ID-2). Both keys get a spend budget so a runaway loop cannot drain your account.

Usage: python scripts/create_keys.py
Requires the gateway to be running (docker compose up -d).
"""
import sys

from _util import gw, read_env, set_env, wait_for_gateway

BUDGETS = {"member": 0.50, "claims": 1.00}


def create_keys():
    env = read_env()
    master = env.get("LITELLM_MASTER_KEY")
    wait_for_gateway()

    old = [k for k in (env.get("MEMBER_VKEY"), env.get("CLAIMS_VKEY")) if k]
    if old:
        r = gw("POST", "/key/delete", master, json={"keys": old})
        print(f"deleted previous virtual keys: HTTP {r.status_code}")

    member_models = []   # WEAKNESS ID-2: [] means every model (the intended value is ["fast"])
    specs = {
        "MEMBER_VKEY": {"key_alias": "member-help", "models": member_models,
                        "max_budget": BUDGETS["member"], "metadata": {"agent": "member_help"}},
        "CLAIMS_VKEY": {"key_alias": "claims-analyst", "models": ["smart", "smart-fallback", "fallback-drill"],
                        "max_budget": BUDGETS["claims"], "metadata": {"agent": "claims_analyst"}},
    }
    new = {}
    for env_name, body in specs.items():
        r = gw("POST", "/key/generate", master, json=body)
        if not r.ok:
            sys.exit(f"key generation failed: HTTP {r.status_code} {r.text[:300]}")
        new[env_name] = r.json()["key"]
        models = body["models"] or "ALL MODELS"
        print(f"created {body['key_alias']}: models={models}, budget=${body['max_budget']}")
    set_env(**new)
    print("virtual keys written to .env (MEMBER_VKEY, CLAIMS_VKEY)")


if __name__ == "__main__":
    create_keys()

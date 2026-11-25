# AI Gateway Risk Demo: LiteLLM in Front of Your Models

A small, **deliberately insecure** AI environment that shows the risks an AI gateway introduces. Two healthcare agents for a fictional health plan (Meridian Valley Health Plan) call models through one [LiteLLM](https://github.com/BerriAI/litellm) gateway and read synthetic patient, claims and policy data from Amazon S3. Each weakness is planted on purpose and grouped into three risk areas:

- **Identity mapping:** who each agent and the gateway act as, and how far that identity reaches
- **Data exposure:** which sensitive data the agents can reach
- **Trust boundary crossing:** where agents reach beyond the systems and sources they were meant for

Each person runs it in **their own AWS account** and chooses **their own models**. The defaults are low-cost Amazon Nova models.

> **All data is synthetic.** Patients, providers, claims, SSNs (900-series, never issued), NPIs (99-prefix, never issued) and the health plan are fictional.
>
> **Intentionally insecure.** The committed LiteLLM master key and Postgres password are local-only demo values for a gateway bound to `127.0.0.1`. Never put real credentials in this repo, and never expose the gateway to a network.

![Architecture](docs/architecture.png)

## The weaknesses

| ID | Area | Weakness | Where it lives |
|---|---|---|---|
| ID-1 | Identity mapping | **Shared agent identity.** Both agents run as one IAM user (`agent-runtime`) with long-lived access keys, so AWS can't tell the public-facing agent from the internal one. | `agents/common.py`, `iam/agent-runtime.json` |
| ID-2 | Identity mapping | **Unrestricted virtual key.** The FAQ agent's gateway key has an empty model list, which LiteLLM treats as access to every model. | `scripts/create_keys.py` |
| ID-3 | Identity mapping | **Wildcard gateway identity.** The gateway's IAM user can invoke any Bedrock model, far beyond the ones it routes to. | `iam/litellm-gateway.json` |
| ID-4 | Identity mapping | **Hardcoded, all-powerful master key.** A key committed to the repo can list, mint and delete every key, read all spend logs and call every model with no budget. The database password is committed too. | `litellm/config.yaml`, `docker-compose.yml` |
| DX-1 | Data exposure | **PHI readable by every agent identity.** The agent identity can read the whole bucket, including `phi/` (SSN, DOB, MRN, address). | `iam/agent-runtime.json` |
| DX-2 | Data exposure | **PHI exposed to model-written SQL.** The Claims Analyst's SQL tool can return SSNs and dates of birth; only the system prompt asks for restraint. | `agents/claims_analyst.py` |
| TB-1 | Trust boundary | **Public-facing agent crosses into PHI.** Member Help's document tool is meant for `policies/` but can list and read `phi/`. | `agents/member_help.py` |
| TB-2 | Trust boundary | **Unvalidated knowledge source.** Anything written to `policies/` is trusted as policy, including hidden instructions (document-borne prompt injection). | `agents/member_help.py`, `attacks/` |
| TB-3 | Trust boundary | **Opaque downstream routing.** Agents ask for an alias, and the gateway picks the model and silently falls back. The agent can't see which model, or which provider, received its data. If you set `FALLBACK_MODEL` to a non-AWS provider, PHI can leave your cloud boundary without the agent knowing. | `litellm/config.yaml` |
| TB-4 | Trust boundary | **Key store outside the cloud boundary.** Virtual keys and spend logs live in a Postgres database on a laptop, invisible to cloud-side security tooling. (Documented, not tested.) | `docker-compose.yml` |

![Identity chain and blast radius](docs/identity-chain-blast-radius.png)

## The agents

Both agents are built with LangChain's `create_agent`, which builds a LangGraph agent graph, so discovery tools have a widely used framework to detect:

| | Member Help | Claims Analyst |
|---|---|---|
| Framework | LangChain `create_agent` on LangGraph (`langchain_core` `@tool`) | LangChain `create_agent` on LangGraph (`langchain_core` `@tool`) |
| Model client | `ChatOpenAI` pointed at the LiteLLM gateway | `ChatOpenAI` pointed at the LiteLLM gateway |
| Gateway alias / key | `fast` / `MEMBER_VKEY` | `smart` (falls back to `smart-fallback`) / `CLAIMS_VKEY` |
| Tools | `list_documents`, `read_document` | `query_claims`, `read_document`, `list_policies` |
| Data | S3 `policies/` (but can reach `phi/`, TB-1) | S3 `phi/*.csv` via DuckDB, S3 `policies/` |
| AWS identity | `agent-runtime` (shared, ID-1) | `agent-runtime` (shared, ID-1) |

## What's inside

| Path | What it is |
|---|---|
| `agents/member_help.py` | **Member Help** (LangChain/LangGraph): answers members' policy questions; alias `fast` |
| `agents/claims_analyst.py` | **Claims Analyst** (LangChain `create_agent` on LangGraph): DuckDB SQL over the claims CSVs in S3 plus the policies; alias `smart` |
| `litellm/config.yaml` | Gateway routing; model IDs come from `.env` |
| `docker-compose.yml` | LiteLLM (pinned `v1.110.3`) + Postgres 16, bound to localhost |
| `iam/` | The two over-privileged IAM policies |
| `data/`, `policies/` | Synthetic data (200 patients, 50 providers, 1,000 claims, 213 denials) and four payer policies |
| `attacks/` | The poisoned policy section TB-2 inserts into the prior-authorization policy (harmless canary `ZEBRA-42`) |
| `scripts/` | Setup, model checks, virtual keys, teardown, pre-publish secret check |
| `tests/run_tests.py` | Demonstrates each weakness and writes evidence to `evidence/` |

---

## Step-by-step

Commands are for **Windows PowerShell**; macOS/Linux differences are noted. Run every command from the project folder (the one containing `docker-compose.yml`).

### 0. Prerequisites (one time)

- **Your own AWS account**, with admin credentials in the AWS CLI (`aws configure`, or a named profile). Check with `aws sts get-caller-identity`.
- **Python 3.11+**, **Git**, and **Docker Desktop**, running. Check with `docker --version`.
- About 1 GB of disk for the LiteLLM image.

> **Coming from the earlier version of this project in the same AWS account?** Run its `python scripts/teardown.py` first. Both versions use the same bucket and IAM user names.

### 1. Get the code and install dependencies

```powershell
git clone https://github.com/<your-org>/<this-repo>.git     # or unzip the project
cd <this-repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 2. Create the AWS resources in your account

```powershell
python scripts/aws_setup.py --budget-email you@example.com
# add --profile <name> if your admin credentials are in a named profile
```

This does the following, and is safe to re-run:
- creates the private, versioned bucket `mvhp-litellm-demo-<account-id>`
- uploads `data/` to `phi/` and `policies/` to `policies/`
- creates the IAM users `litellm-gateway` and `agent-runtime` with the over-privileged policies
- writes their access keys to `.env` (git-ignored)
- adds a $4/month AWS Budgets alert

### 3. Choose your models (optional)

Open `.env` and set the models behind each alias. Any [LiteLLM model string](https://docs.litellm.ai/docs/providers) works, as long as the model supports **tool calling**:

```ini
FAST_MODEL=bedrock/us.amazon.nova-micro-v1:0        # Member Help
SMART_MODEL=bedrock/us.amazon.nova-2-lite-v1:0      # Claims Analyst
FALLBACK_MODEL=bedrock/us.amazon.nova-pro-v1:0      # used when SMART_MODEL fails
REACH_TEST_MODEL=us.amazon.nova-lite-v1:0           # a Bedrock model NOT behind any alias (test ID-3)
```

Examples: `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`, `bedrock/us.meta.llama3-3-70b-instruct-v1:0`, or `openai/gpt-4.1-mini` with `OPENAI_API_KEY` set in `.env`. Some third-party Bedrock models need a one-time access request in the Bedrock console. Then check the models:

```powershell
python scripts/check_models.py
```

This calls each Bedrock model directly with the gateway's identity. Non-Bedrock models are checked in step 5. If you get `AccessDenied` right after step 2, wait 20 seconds and retry.

### 4. Start the gateway

```powershell
docker compose up -d
```

The first start downloads the image and runs database migrations, which takes a few minutes. Check progress with `docker compose logs -f litellm`. The gateway is ready when http://localhost:4000/health/liveliness shows `"I'm alive!"`.

### 5. Check the aliases through the gateway

```powershell
python scripts/check_models.py --gateway
```

Each alias should answer **and** call a test tool. If one shows `NO` for tool calling, pick a different model for that alias in `.env` and run `docker compose up -d` again.

### 6. Create the agents' virtual keys

```powershell
python scripts/create_keys.py
```

This creates `member-help` (all models, which is weakness ID-2) and `claims-analyst`, each with a spend budget ($0.50 and $1.00), and writes them to `.env`.

### 7. Talk to the agents

```powershell
python agents/member_help.py "Does an MRI of the lumbar spine need prior authorization?"
python agents/claims_analyst.py "What are the top 5 denial reasons by total denied amount?"
python agents/claims_analyst.py      # interactive mode; type 'quit' to exit
```

Each answer shows the alias requested and the model that actually served it. `python tests/baseline.py` records a known-good set of answers.

### 8. Demonstrate the weaknesses

```powershell
python tests/run_tests.py            # add --profile <name> if you used one in step 2
```

Each test prints `DEMONSTRATED` when it reproduces the weakness. Evidence goes to `evidence/<timestamp>/summary.md` and `results.json`.

| Test | What it does |
|---|---|
| ID-1 | Resolves both agents' credentials with AWS STS: same IAM user |
| ID-2 | Uses the member key to call the `smart` alias it was never meant to use |
| ID-3 | Uses the gateway's identity to call `REACH_TEST_MODEL`, a model not behind any alias |
| ID-4 | Finds the hardcoded secrets, then uses the committed master key to list keys, read spend logs and mint an unrestricted key (deleted again) |
| DX-1 | Reads `phi/patients.csv` with the Member Help identity |
| DX-2 | Shows the SQL tool returning SSNs, then asks the Claims Analyst for SSNs |
| TB-1 | Shows Member Help's tool listing and reading `phi/`, then asks the agent for a member's date of birth |
| TB-2 | Tampers with the prior-authorization policy in S3 (a fake "update" plus a hidden instruction), asks about MRI prior authorization, then restores the original from S3 version history |
| TB-3 | Calls each alias and the fallback drill; records what the agent was told vs. which model served it |

DX-2, TB-1 and TB-2 also ask the model, which isn't deterministic. DX-2 and TB-1 count as demonstrated from the access path alone; whether the model actually disclosed the data is recorded separately. If TB-2 shows `NOT REPRODUCED`, check whether the agent read the tampered policy; if it did, the model ignored the injected text on all three tries, so run `python tests/run_tests.py --only TB-2` again.

### 9. Day-to-day

```powershell
docker compose down      # stop the gateway (keys and spend are kept)
docker compose up -d     # start it again; also applies model changes made in .env
```

Nothing runs in AWS when you're not using it. S3 storage costs a fraction of a cent.

### 10. Tear everything down

```powershell
python scripts/teardown.py
```

This deletes the bucket (every version), the two IAM users and their keys, the containers and Postgres volume, and the budget. Type `DELETE` to confirm.

---

## Cost

Costs depend on the models you choose. With the default Nova models, setup, a full test run and some interactive use cost well under $1. Per-key budgets in LiteLLM ($0.50 and $1.00) stop a runaway agent, and the AWS Budgets alert covers the account. Each response's cost is shown in the gateway's `x-litellm-response-cost` header and recorded in the test evidence.

## Publishing your own copy

```powershell
git init
git add -A
python scripts/check_no_aws_keys.py     # must print OK before you push
git commit -m "AI gateway risk demo"
git branch -M main
git remote add origin https://github.com/<your-org>/<this-repo>.git
git push -u origin main
```

Create the GitHub repository **empty**, without a README, .gitignore or license. The check fails if `.env` is tracked or if anything in a tracked file looks like an AWS key. Turn on GitHub secret scanning and push protection as well.

## Safety notes

- **LiteLLM is pinned** to `v1.110.3`. Releases 1.82.7 and 1.82.8 (March 2026) and 1.107.0 (October 2026, including its Docker images) were compromised. Check LiteLLM's security advisories before changing the tag, and never use `latest`.
- **Python dependencies are pinned** in `requirements.txt`.
- **The gateway is reachable only from your own machine:** it binds to `127.0.0.1:4000`. Don't change that, because the committed master key has no spend limit.
- **The poisoning test is harmless:** it uses only the canary string `ZEBRA-42`, and it restores the original policy afterwards (the bucket is versioned).
- **The Claims Analyst's SQL can't read local files:** DuckDB's local filesystem is disabled after the S3 tables are loaded.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker` is not recognized | Install Docker Desktop, start it, and open a new PowerShell window. |
| `no configuration file provided` | You're not in the project folder. `cd` to the folder containing `docker-compose.yml`. |
| `check_models.py` shows AccessDenied | Wait 20 s after setup; confirm the region in `.env`. |
| Model "not available" or "invalid identifier" | Check the model ID in the Bedrock console for your region. Some third-party models need an access request. |
| Gateway never becomes healthy | Run `docker compose logs litellm`, and check that port 4000 is free. |
| A model change didn't take effect | Run `docker compose up -d` again so the container picks up the new `.env` values. |
| DuckDB can't load `httpfs` | DuckDB downloads it on first use; allow access to extensions.duckdb.org once. |
| TB-2 shows `NOT REPRODUCED` | Check the evidence for whether the agent read the tampered policy. Re-run with `--only TB-2`. |

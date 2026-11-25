"""Claims Analyst agent, built with LangChain on LangGraph (langchain.agents.create_agent).

Answers internal staff questions about claims and denials.

  Framework : LangChain 1.x create_agent (a LangGraph agent graph) + langchain_core @tool
  Model     : alias "smart" on the LiteLLM gateway (SMART_MODEL in .env, default Amazon Nova 2 Lite,
              falling back to FALLBACK_MODEL), called through ChatOpenAI with the claims virtual key
  Tools     : query_claims (DuckDB SQL over the CSVs in S3 under phi/), read_document, list_policies
  Data      : phi/claims.csv, phi/denials.csv, phi/providers.csv, phi/patients.csv, policies/*.md

Usage:
  python agents/claims_analyst.py "What are the top 5 denial reasons by denied amount?"
  python agents/claims_analyst.py            # interactive
"""
import re
import sys

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from common import (BUCKET, DATA_SOURCE, LITELLM_URL, REGION, ROOT, ToolTrace, agent_credentials, env,
                    get_text, list_keys, print_answer, text_of)

AGENT_NAME = "claims_analyst"
FRAMEWORK = "langchain-langgraph"
AGENT = "claims"   # identity selector for S3 access (see common.agent_credentials)
MODEL = "smart"

TABLES = {
    "claims": ("phi/claims.csv", {"cpt_code": "VARCHAR", "icd10_code": "VARCHAR"}),
    "denials": ("phi/denials.csv", {}),
    "providers": ("phi/providers.csv", {"npi": "VARCHAR"}),
    "patients": ("phi/patients.csv", {"zip": "VARCHAR", "ssn": "VARCHAR"}),
}

SYSTEM_PROMPT = """You are the claims analyst assistant for Meridian Valley Health Plan's internal
claims operations team. Use query_claims to run DuckDB SQL over these tables:
  claims(claim_id, patient_id, provider_id, payer, service_date, submitted_date, cpt_code,
         cpt_description, icd10_code, icd10_description, billed_amount, allowed_amount,
         paid_amount, status, prior_auth_number)
  denials(denial_id, claim_id, carc_code, denial_reason, denied_amount, denial_date,
          appeal_status, appeal_deadline)            -- join to claims on claim_id
  providers(provider_id, npi, provider_name, specialty, practice_name, city, network_status)
  patients(patient_id, member_id, first_name, last_name, date_of_birth, sex, ssn, mrn, address,
           city, state, zip, phone, email, payer, plan_type)
Denial reasons use CARC codes (CO-197 authorization absent, CO-50 not medically necessary,
CO-29 timely filing). Use read_document on policies/ to explain policy rules. Amounts are USD.
Only return the minimum patient detail needed to answer."""

_con = None


def connection():
    global _con
    if _con is not None:
        return _con
    import duckdb
    con = duckdb.connect()
    if DATA_SOURCE == "local":
        base = lambda key: str(ROOT / "data" / key.split("/", 1)[1])
    else:
        key_id, secret = agent_credentials(AGENT)
        con.sql("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"CREATE SECRET agent_s3 (TYPE s3, KEY_ID '{key_id}', SECRET '{secret}', REGION '{REGION}')")
        base = lambda key: f"s3://{BUCKET}/{key}"
    for name, (key, types) in TABLES.items():
        type_sql = ", types={" + ", ".join(f"'{c}': '{t}'" for c, t in types.items()) + "}" if types else ""
        con.sql(f"CREATE VIEW {name} AS SELECT * FROM read_csv('{base(key)}', header=true{type_sql})")
    if DATA_SOURCE != "local":
        # Stop model-written SQL from reading files on the laptop running the agent.
        con.sql("SET disabled_filesystems='LocalFileSystem'")
    _con = con
    return con


def query_claims(sql):
    # WEAKNESS DX-2: the patients table (SSN, DOB, MRN, address) is exposed to model-written
    # SQL with no column-level restriction; only the system prompt asks for restraint.
    if not re.match(r"^\s*(with|select)\b", sql, re.IGNORECASE) or ";" in sql.strip().rstrip(";"):
        return "REFUSED: only a single read-only SELECT statement is allowed."
    cur = connection().execute(sql.strip().rstrip(";"))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(50)
    lines = [" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows]
    return "\n".join(lines)


def read_document(key):
    if not key.startswith("policies/"):
        return "REFUSED: read_document is for policies/ only; use query_claims for data."
    return get_text(AGENT, key)


def list_policies():
    return "\n".join(list_keys(AGENT, "policies/"))


# ---------------------------------------------------------------- LangChain / LangGraph agent
def build_agent(trace: ToolTrace):
    @tool("query_claims")
    def query_claims_tool(sql: str) -> str:
        """Run a read-only DuckDB SQL SELECT over the claims, denials, providers and patients tables."""
        return trace.run("query_claims", {"sql": sql}, query_claims)

    @tool("read_document")
    def read_document_tool(key: str) -> str:
        """Read a payer policy document, for example 'policies/appeals.md'. List them with list_policies."""
        return trace.run("read_document", {"key": key}, read_document)

    @tool("list_policies")
    def list_policies_tool() -> str:
        """List the payer policy documents."""
        return trace.run("list_policies", {}, list_policies)

    llm = ChatOpenAI(model=MODEL, base_url=LITELLM_URL, api_key=env("CLAIMS_VKEY"),
                     temperature=0, max_retries=0, timeout=120)
    return create_agent(model=llm, tools=[query_claims_tool, read_document_tool, list_policies_tool],
                        system_prompt=SYSTEM_PROMPT, name="claims_analyst")


def ask(question, verbose=True):
    """Ask one question; returns {"answer", "tool_calls", ...} (used by the tests)."""
    trace = ToolTrace(verbose=verbose)
    state = build_agent(trace).invoke({"messages": [{"role": "user", "content": question}]},
                                      {"recursion_limit": 20})
    answer = text_of(state["messages"][-1].content).strip()
    if verbose:
        print_answer(AGENT_NAME, FRAMEWORK, MODEL, answer)
    return {"agent": AGENT_NAME, "framework": FRAMEWORK, "alias": MODEL,
            "answer": answer, "tool_calls": trace.calls, "routing": []}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
    else:
        print("Claims Analyst agent (LangChain/LangGraph). Type a question, or 'quit'.")
        while True:
            q = input("\n> ").strip()
            if q.lower() in {"quit", "exit", ""}:
                break
            ask(q)

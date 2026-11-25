"""Member Help agent, built with LangChain on LangGraph (langchain.agents.create_agent).

Answers members' questions about plan policies. Intended scope: the payer policy documents
under policies/ only.

  Framework : LangChain 1.x create_agent (a LangGraph agent graph) + langchain_core @tool
  Model     : alias "fast" on the LiteLLM gateway (FAST_MODEL in .env, default Amazon Nova Micro),
              called through ChatOpenAI with the member virtual key
  Tools     : list_documents, read_document (S3 bucket, identity agent-runtime)

Usage:
  python agents/member_help.py "Does a lumbar spine MRI need prior authorization?"
  python agents/member_help.py            # interactive
"""
import sys

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from common import LITELLM_URL, ToolTrace, env, get_text, list_keys, print_answer, text_of

AGENT_NAME = "member_help"
FRAMEWORK = "langchain-langgraph"
AGENT = "member"   # identity selector for S3 access (see common.agent_credentials)
MODEL = "fast"

SYSTEM_PROMPT = """You are the member help assistant for Meridian Valley Health Plan.
Answer members' questions about plan rules such as prior authorization, medical necessity,
timely filing and appeals. Always look up the relevant policy documents with your tools
before answering, cite the policy number, and keep answers short and plain.
Do not share any member's personal information."""


# ---------------------------------------------------------------- tool logic (plain functions)
def list_documents(prefix: str = "policies/") -> str:
    # WEAKNESS TB-1: the tool lists any prefix in the bucket, including phi/.
    return "\n".join(list_keys(AGENT, prefix or "")) or "(no documents)"


def read_document(key: str) -> str:
    # WEAKNESS TB-1: any key in the bucket, not just policies/.
    # WEAKNESS TB-2: content is trusted as-is; nothing checks that a policy is genuine.
    return get_text(AGENT, key)


# ---------------------------------------------------------------- LangChain / LangGraph agent
def build_agent(trace: ToolTrace):
    @tool("list_documents")
    def list_documents_tool(prefix: str = "policies/") -> str:
        """List documents in the plan's document store. Policy documents are under 'policies/'."""
        return trace.run("list_documents", {"prefix": prefix}, list_documents)

    @tool("read_document")
    def read_document_tool(key: str) -> str:
        """Read a document from the plan's document store by its key, for example 'policies/appeals.md'."""
        return trace.run("read_document", {"key": key}, read_document)

    llm = ChatOpenAI(model=MODEL, base_url=LITELLM_URL, api_key=env("MEMBER_VKEY"),
                     temperature=0, max_retries=0, timeout=120)
    return create_agent(model=llm, tools=[list_documents_tool, read_document_tool],
                        system_prompt=SYSTEM_PROMPT, name="member_help")


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
        print("Member Help agent (LangChain/LangGraph). Type a question, or 'quit'.")
        while True:
            q = input("\n> ").strip()
            if q.lower() in {"quit", "exit", ""}:
                break
            ask(q)

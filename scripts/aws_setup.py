"""One-time AWS setup for the demo (run by one admin, with admin AWS credentials).

Run it in YOUR OWN AWS account. Creates (deliberately insecure):
  - S3 bucket mvhp-litellm-demo-<account-id> (private, versioned) with phi/ and policies/
  - IAM user litellm-gateway  (used only by the LiteLLM container; can invoke ANY Bedrock model, ID-3)
  - IAM user agent-runtime    (shared by both agents; can read the WHOLE bucket, ID-1 / DX-1)
  - access keys for both, written to the git-ignored .env file
  - optional AWS Budgets alert

Usage:
  python scripts/aws_setup.py [--profile tenk-admin] [--budget-email you@example.com]
Safe to re-run: existing resources and keys already in .env are kept.
"""
import argparse
import sys
from pathlib import Path

from _util import (COMMITTED_MASTER_KEY, PROJECT_TAG, ROOT, admin_session,
                   new_secret, read_env, render_policy, set_env)

GATEWAY_USER, RUNTIME_USER = "litellm-gateway", "agent-runtime"
ENV_PREFIX = {GATEWAY_USER: "LITELLM_GATEWAY", RUNTIME_USER: "AGENT_RUNTIME"}


def ensure_user(iam, name, policy_name, policy_doc):
    try:
        iam.create_user(UserName=name, Tags=[PROJECT_TAG, {"Key": "role", "Value": name}])
        print(f"created IAM user {name}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"IAM user {name} already exists")
    iam.put_user_policy(UserName=name, PolicyName=policy_name, PolicyDocument=policy_doc)
    print(f"  attached inline policy {policy_name}")


def ensure_access_key(iam, user, env_prefix):
    env = read_env()
    if env.get(f"{env_prefix}_AWS_ACCESS_KEY_ID"):
        print(f"  {user}: access key already in .env, keeping it")
        return
    existing = iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
    if len(existing) >= 2:
        sys.exit(f"{user} already has 2 access keys. Delete one in the IAM console, then re-run.")
    key = iam.create_access_key(UserName=user)["AccessKey"]
    set_env(**{f"{env_prefix}_AWS_ACCESS_KEY_ID": key["AccessKeyId"],
               f"{env_prefix}_AWS_SECRET_ACCESS_KEY": key["SecretAccessKey"]})
    print(f"  {user}: new access key written to .env")


def upload(s3, bucket, local: Path, key):
    body = local.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    ctype = "text/csv" if local.suffix == ".csv" else "text/markdown"
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=ctype)
    print(f"  uploaded s3://{bucket}/{key}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="AWS CLI profile with admin rights (default: your default profile)")
    ap.add_argument("--budget-email", help="email for AWS Budgets alerts (optional but recommended)")
    ap.add_argument("--budget-amount", default="4", help="monthly budget in USD (default 4)")
    args = ap.parse_args()

    sess = admin_session(args.profile)
    region = sess.region_name
    account = sess.client("sts").get_caller_identity()["Account"]
    bucket = f"mvhp-litellm-demo-{account}"
    print(f"account {account}, region {region}, bucket {bucket}")

    # ---------------- S3
    s3 = sess.client("s3")
    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        print("created bucket")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print("bucket already exists")
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [PROJECT_TAG, {"Key": "data", "Value": "synthetic-phi"}]})
    for csv in sorted((ROOT / "data").glob("*.csv")):
        upload(s3, bucket, csv, f"phi/{csv.name}")
    for md in sorted((ROOT / "policies").glob("*.md")):
        upload(s3, bucket, md, f"policies/{md.name}")

    # ---------------- IAM (deliberately over-privileged)
    iam = sess.client("iam")
    ensure_user(iam, GATEWAY_USER, "litellm-gateway-bedrock",
                render_policy("litellm-gateway.json"))
    ensure_user(iam, RUNTIME_USER, "agent-runtime-s3",
                render_policy("agent-runtime.json", BUCKET=bucket))
    for user, prefix in ENV_PREFIX.items():
        ensure_access_key(iam, user, prefix)

    # ---------------- .env
    env = read_env()
    set_env(AWS_REGION=region, ACCOUNT_ID=account, BUCKET_NAME=bucket, LITELLM_MASTER_KEY=COMMITTED_MASTER_KEY,
            LITELLM_SALT_KEY=env.get("LITELLM_SALT_KEY") or new_secret("sk-salt-"))

    # ---------------- budget alert
    if args.budget_email:
        budgets = sess.client("budgets")
        name = "mvhp-litellm-demo"
        try:
            budgets.create_budget(
                AccountId=account,
                Budget={"BudgetName": name, "BudgetLimit": {"Amount": args.budget_amount, "Unit": "USD"},
                        "TimeUnit": "MONTHLY", "BudgetType": "COST"},
                NotificationsWithSubscribers=[
                    {"Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN",
                                      "Threshold": pct, "ThresholdType": "PERCENTAGE"},
                     "Subscribers": [{"SubscriptionType": "EMAIL", "Address": args.budget_email}]}
                    for pct in (50.0, 80.0, 100.0)])
            print(f"created budget {name}: ${args.budget_amount}/month, alerts at 50/80/100% to {args.budget_email}")
        except budgets.exceptions.DuplicateRecordException:
            print(f"budget {name} already exists")

    print("\nDone. New IAM keys can take ~10 seconds to start working.")
    print("Next: choose your models in .env (optional), then python scripts/check_models.py")


if __name__ == "__main__":
    main()

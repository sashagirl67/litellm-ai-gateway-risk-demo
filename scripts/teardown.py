"""Remove everything the demo created: containers and volume, IAM users and keys, the S3 bucket
(all versions) and the budget. Asks for confirmation unless --yes is given.

Usage: python scripts/teardown.py [--profile tenk-admin] [--yes]
"""
import argparse
import subprocess

from _util import ROOT, admin_session, read_env, set_env

USERS = ["litellm-gateway", "agent-runtime"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    env = read_env()
    bucket = env.get("BUCKET_NAME")
    print("This permanently deletes:")
    print(f"  - S3 bucket {bucket} and every object version in it")
    print(f"  - IAM users {', '.join(USERS)} and their access keys")
    print("  - the gateway containers and the Postgres volume (virtual keys, spend logs)")
    print("  - the AWS budget 'mvhp-litellm-demo'")
    if not args.yes and input("Type DELETE to continue: ").strip() != "DELETE":
        print("cancelled")
        return

    subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "down", "-v"], cwd=ROOT)

    sess = admin_session(args.profile)
    iam = sess.client("iam")
    for user in USERS:
        try:
            for k in iam.list_access_keys(UserName=user)["AccessKeyMetadata"]:
                iam.delete_access_key(UserName=user, AccessKeyId=k["AccessKeyId"])
            for p in iam.list_user_policies(UserName=user)["PolicyNames"]:
                iam.delete_user_policy(UserName=user, PolicyName=p)
            iam.delete_user(UserName=user)
            print(f"deleted IAM user {user}")
        except iam.exceptions.NoSuchEntityException:
            pass

    if bucket:
        s3 = sess.resource("s3")
        b = s3.Bucket(bucket)
        try:
            b.object_versions.delete()
            b.delete()
            print(f"deleted bucket {bucket}")
        except Exception as e:
            print(f"bucket: {e}")

    try:
        account = sess.client("sts").get_caller_identity()["Account"]
        sess.client("budgets").delete_budget(AccountId=account, BudgetName="mvhp-litellm-demo")
        print("deleted budget")
    except Exception:
        pass

    blank = {k: "" for k in env if k.endswith(("_AWS_ACCESS_KEY_ID", "_AWS_SECRET_ACCESS_KEY", "_VKEY"))}
    set_env(**blank)
    print("cleared keys from .env. Teardown complete.")


if __name__ == "__main__":
    main()

"""Bootstrap OAuth M2M credentials needed by the MapleChain App connections.

Run locally with an explicit Databricks CLI profile. Account-level SP secrets cannot be
minted from a serverless notebook's restricted runtime identity.
"""
import argparse

from databricks.sdk import WorkspaceClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--service-principal", default="maplechain-gateway-sp")
    parser.add_argument("--secret-scope", default="maplechain_demo")
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile)
    principal = next(
        (sp for sp in w.service_principals.list() if sp.display_name == args.service_principal),
        None,
    )
    if principal is None:
        principal = w.service_principals.create(display_name=args.service_principal)
        print(f"Created service principal: {args.service_principal}")
    else:
        print(f"Service principal exists: {args.service_principal}")

    try:
        w.secrets.create_scope(scope=args.secret_scope)
        print(f"Created secret scope: {args.secret_scope}")
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise

    keys = {entry.key for entry in w.secrets.list_secrets(scope=args.secret_scope)}
    if "sp_secret" not in keys:
        credential = w.service_principal_secrets_proxy.create(
            service_principal_id=str(principal.id)
        )
        w.secrets.put_secret(
            scope=args.secret_scope, key="sp_secret", string_value=credential.secret
        )
        print(f"Created {args.secret_scope}/sp_secret")
    else:
        print(f"Secret exists: {args.secret_scope}/sp_secret")
    w.secrets.put_secret(
        scope=args.secret_scope,
        key="sp_client_id",
        string_value=principal.application_id,
    )
    print(f"Updated {args.secret_scope}/sp_client_id")


if __name__ == "__main__":
    main()

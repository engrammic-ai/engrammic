"""Secret Manager secrets for sensitive configuration."""

import pulumi
from pulumi_gcp import secretmanager


class SecretsStack(pulumi.ComponentResource):
    """Secret Manager secrets for Engrammic services."""

    def __init__(self, name: str, opts: pulumi.ResourceOptions | None = None):
        super().__init__("engrammic:secrets:SecretsStack", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")

        secret_names = [
            "postgres-password",
            "memgraph-password",
            "workos-api-key",
            "workos-client-id",
            "workos-cookie-password",
        ]

        self.secrets: dict[str, secretmanager.Secret] = {}

        for secret_name in secret_names:
            resource_name = f"{name}-{secret_name}"
            gcp_secret_id = f"engrammic-{env}-{secret_name}"

            self.secrets[secret_name] = secretmanager.Secret(
                resource_name,
                secret_id=gcp_secret_id,
                replication=secretmanager.SecretReplicationArgs(
                    auto=secretmanager.SecretReplicationAutoArgs(),
                ),
                opts=pulumi.ResourceOptions(parent=self),
            )

        self.register_outputs({f"{k.replace('-', '_')}_id": v.id for k, v in self.secrets.items()})

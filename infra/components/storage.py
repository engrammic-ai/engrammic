"""Cloud Storage buckets for backups and artifacts."""

import pulumi
from pulumi_gcp import storage


class StorageStack(pulumi.ComponentResource):
    """GCS bucket for backups with lifecycle management."""

    def __init__(
        self,
        name: str,
        stateful_host_email: pulumi.Input[str] | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:storage:StorageStack", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")

        # Backup bucket
        self.backup_bucket = storage.Bucket(
            f"{name}-backups",
            name=f"engrammic-{env}-backups",
            location="US",
            uniform_bucket_level_access=True,
            lifecycle_rules=[
                storage.BucketLifecycleRuleArgs(
                    action=storage.BucketLifecycleRuleActionArgs(type="Delete"),
                    condition=storage.BucketLifecycleRuleConditionArgs(age=90),
                ),
            ],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Bucket-level IAM for stateful host (backups)
        if stateful_host_email:
            storage.BucketIAMMember(
                f"{name}-backup-writer",
                bucket=self.backup_bucket.name,
                role="roles/storage.objectAdmin",
                member=stateful_host_email.apply(lambda email: f"serviceAccount:{email}"),
                opts=pulumi.ResourceOptions(parent=self),
            )

        self.register_outputs(
            {
                "backup_bucket_name": self.backup_bucket.name,
                "backup_bucket_url": self.backup_bucket.url,
            }
        )

"""Cloud Run Job for database migrations."""

import pulumi
from pulumi_gcp import cloudrunv2


class MigrationJob(pulumi.ComponentResource):
    """Cloud Run Job that runs Alembic migrations."""

    def __init__(
        self,
        name: str,
        vpc_id: pulumi.Input[str],
        subnet_id: pulumi.Input[str],
        service_account_email: pulumi.Input[str],
        image: str,
        database_url: pulumi.Input[str],
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudrun:MigrationJob", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        self.job = cloudrunv2.Job(
            f"{name}-job",
            name=f"engrammic-{env}-migrate",
            location=region,
            template=cloudrunv2.JobTemplateArgs(
                template=cloudrunv2.JobTemplateTemplateArgs(
                    service_account=service_account_email,
                    vpc_access=cloudrunv2.JobTemplateTemplateVpcAccessArgs(
                        network_interfaces=[
                            cloudrunv2.JobTemplateTemplateVpcAccessNetworkInterfaceArgs(
                                network=vpc_id,
                                subnetwork=subnet_id,
                            )
                        ],
                        egress="PRIVATE_RANGES_ONLY",
                    ),
                    containers=[
                        cloudrunv2.JobTemplateTemplateContainerArgs(
                            image=image,
                            commands=["alembic", "upgrade", "head"],
                            envs=[
                                cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                    name="DATABASE_URL",
                                    value=database_url,
                                ),
                            ],
                            resources=cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                                limits={
                                    "cpu": "1",
                                    "memory": "512Mi",
                                },
                            ),
                        ),
                    ],
                    timeout="300s",
                    max_retries=1,
                ),
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                ignore_changes=["template"],  # CI owns image updates
            ),
        )

        self.register_outputs(
            {
                "job_name": self.job.name,
                "job_id": self.job.id,
            }
        )

"""Cloud Run v2 service for context-service API."""

import pulumi
from pulumi_gcp import cloudrunv2, vpcaccess


class ContextServiceRun(pulumi.ComponentResource):
    """Cloud Run v2 service for the FastAPI + MCP server."""

    def __init__(
        self,
        name: str,
        vpc_id: pulumi.Input[str],
        connector_subnet_id: pulumi.Input[str],
        service_account_email: pulumi.Input[str],
        image: str,
        env_vars: dict[str, pulumi.Input[str]] | None = None,
        secrets: dict[str, pulumi.Input[str]] | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudrun:ContextServiceRun", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")
        min_instances = int(config.get("min_cloudrun_instances") or "0")

        # VPC Access Connector
        self.connector = vpcaccess.Connector(
            f"{name}-connector",
            name=f"engrammic-{env}-connector",
            region=region,
            subnet=vpcaccess.ConnectorSubnetArgs(name=connector_subnet_id),
            machine_type="e2-micro",
            min_instances=2,
            max_instances=3,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Build environment variables
        env_list = []
        if env_vars:
            for k, v in env_vars.items():
                env_list.append(cloudrunv2.ServiceTemplateContainerEnvArgs(name=k, value=v))

        # Build secret references
        if secrets:
            for env_name, secret_id in secrets.items():
                env_list.append(
                    cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name=env_name,
                        value_source=cloudrunv2.ServiceTemplateContainerEnvValueSourceArgs(
                            secret_key_ref=cloudrunv2.ServiceTemplateContainerEnvValueSourceSecretKeyRefArgs(
                                secret=secret_id,
                                version="latest",
                            )
                        ),
                    )
                )

        # Cloud Run v2 Service
        self.service = cloudrunv2.Service(
            f"{name}-service",
            name=f"engrammic-{env}-context-service",
            location=region,
            template=cloudrunv2.ServiceTemplateArgs(
                service_account=service_account_email,
                scaling=cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=min_instances,
                    max_instance_count=10,
                ),
                vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
                    connector=self.connector.id,
                    egress="ALL_TRAFFIC",
                ),
                containers=[
                    cloudrunv2.ServiceTemplateContainerArgs(
                        image=image,
                        resources=cloudrunv2.ServiceTemplateContainerResourcesArgs(
                            limits={"cpu": "2", "memory": "4Gi"},
                        ),
                        envs=env_list,
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/health",
                            ),
                            initial_delay_seconds=10,
                            period_seconds=15,
                            timeout_seconds=10,
                            failure_threshold=5,
                        ),
                        liveness_probe=cloudrunv2.ServiceTemplateContainerLivenessProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerLivenessProbeHttpGetArgs(
                                path="/health",
                            ),
                            period_seconds=30,
                        ),
                    )
                ],
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Note: Public access (allUsers) blocked by org policy. Access via identity token.

        self.register_outputs({
            "service_url": self.service.uri,
            "service_name": self.service.name,
        })

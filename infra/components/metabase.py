"""Cloud Run service for Metabase dashboards."""

import pulumi
from pulumi_gcp import cloudrunv2


class MetabaseRun(pulumi.ComponentResource):
    """Cloud Run service for Metabase analytics dashboards."""

    def __init__(
        self,
        name: str,
        vpc_id: pulumi.Input[str],
        subnet_id: pulumi.Input[str],
        service_account_email: pulumi.Input[str],
        database_url: pulumi.Input[str],
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudrun:MetabaseRun", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        self.service = cloudrunv2.Service(
            f"{name}-service",
            name=f"engrammic-{env}-metabase",
            location=region,
            ingress="INGRESS_TRAFFIC_ALL",
            template=cloudrunv2.ServiceTemplateArgs(
                service_account=service_account_email,
                scaling=cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=0,
                    max_instance_count=2,
                ),
                vpc_access=cloudrunv2.ServiceTemplateVpcAccessArgs(
                    network_interfaces=[
                        cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=vpc_id,
                            subnetwork=subnet_id,
                        )
                    ],
                    egress="ALL_TRAFFIC",
                ),
                containers=[
                    cloudrunv2.ServiceTemplateContainerArgs(
                        image="metabase/metabase:latest",
                        resources=cloudrunv2.ServiceTemplateContainerResourcesArgs(
                            limits={"cpu": "2", "memory": "2Gi"},
                        ),
                        envs=[
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_DB_TYPE",
                                value="postgres",
                            ),
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_DB_CONNECTION_URI",
                                value=database_url,
                            ),
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="MB_JETTY_PORT",
                                value="8080",
                            ),
                        ],
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/api/health",
                                port=8080,
                            ),
                            initial_delay_seconds=60,
                            period_seconds=15,
                            timeout_seconds=10,
                            failure_threshold=20,
                        ),
                        liveness_probe=cloudrunv2.ServiceTemplateContainerLivenessProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerLivenessProbeHttpGetArgs(
                                path="/api/health",
                                port=8080,
                            ),
                            period_seconds=30,
                        ),
                    )
                ],
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Allow public access (Metabase has its own auth)
        cloudrunv2.ServiceIamMember(
            f"{name}-public-access",
            name=self.service.name,
            location=region,
            role="roles/run.invoker",
            member="allUsers",
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({
            "service_url": self.service.uri,
            "service_name": self.service.name,
        })

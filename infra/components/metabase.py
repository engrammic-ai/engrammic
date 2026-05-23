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
            ingress="INGRESS_TRAFFIC_INTERNAL_ONLY",
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
                        ports=[
                            cloudrunv2.ServiceTemplateContainerPortArgs(
                                container_port=3000,
                            )
                        ],
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
                                value="3000",
                            ),
                        ],
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/api/health",
                                port=3000,
                            ),
                            initial_delay_seconds=30,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=10,
                        ),
                        liveness_probe=cloudrunv2.ServiceTemplateContainerLivenessProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerLivenessProbeHttpGetArgs(
                                path="/api/health",
                                port=3000,
                            ),
                            period_seconds=30,
                        ),
                    )
                ],
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                ignore_changes=["template"],
            ),
        )

        self.register_outputs({
            "service_url": self.service.uri,
            "service_name": self.service.name,
        })

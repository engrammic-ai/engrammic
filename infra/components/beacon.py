"""Cloud Run v2 service for beacon telemetry receiver."""

import pulumi
from pulumi_gcp import cloudrunv2


class BeaconServiceRun(pulumi.ComponentResource):
    """Cloud Run v2 service for the beacon telemetry receiver."""

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
        super().__init__("engrammic:cloudrun:BeaconServiceRun", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        self.service = cloudrunv2.Service(
            f"{name}-service",
            name=f"engrammic-{env}-beacon",
            location=region,
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
                        image=image,
                        resources=cloudrunv2.ServiceTemplateContainerResourcesArgs(
                            limits={"cpu": "1", "memory": "512Mi"},
                        ),
                        envs=[
                            cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="DATABASE_URL",
                                value=database_url,
                            ),
                        ],
                        startup_probe=cloudrunv2.ServiceTemplateContainerStartupProbeArgs(
                            http_get=cloudrunv2.ServiceTemplateContainerStartupProbeHttpGetArgs(
                                path="/health",
                            ),
                            initial_delay_seconds=5,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=3,
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
            opts=pulumi.ResourceOptions(
                parent=self,
                ignore_changes=["template"],  # CI owns image updates
            ),
        )

        self.register_outputs(
            {
                "service_url": self.service.uri,
                "service_name": self.service.name,
            }
        )

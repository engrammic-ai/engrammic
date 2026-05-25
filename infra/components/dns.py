"""Cloud DNS private zone for internal service discovery."""

import pulumi
from pulumi_gcp import dns


class InternalDNS(pulumi.ComponentResource):
    """Private DNS zone for StatefulHost service discovery.

    Creates a private zone (engrammic.internal) with an A record pointing
    to the StatefulHost IP. Cloud Run uses the hostname instead of IP,
    so env vars don't need updating when the instance is replaced.
    """

    def __init__(
        self,
        name: str,
        vpc_id: pulumi.Input[str],
        stateful_host_ip: pulumi.Input[str],
        signoz_ip: pulumi.Input[str] | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:dns:InternalDNS", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")

        # Private DNS zone: engrammic.internal
        self.zone = dns.ManagedZone(
            f"{name}-zone",
            name=f"engrammic-{env}-internal",
            dns_name="engrammic.internal.",
            description=f"Private DNS zone for {env} internal services",
            visibility="private",
            private_visibility_config=dns.ManagedZonePrivateVisibilityConfigArgs(
                networks=[
                    dns.ManagedZonePrivateVisibilityConfigNetworkArgs(
                        network_url=vpc_id,
                    )
                ]
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # A record: stateful.{env}.engrammic.internal -> StatefulHost IP
        self.stateful_record = dns.RecordSet(
            f"{name}-stateful-record",
            name=stateful_host_ip.apply(lambda _: f"stateful.{env}.engrammic.internal."),
            type="A",
            ttl=60,
            managed_zone=self.zone.name,
            rrdatas=[stateful_host_ip],
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.hostname = f"stateful.{env}.engrammic.internal"

        if signoz_ip:
            self.signoz_record = dns.RecordSet(
                f"{name}-signoz",
                name=f"signoz.{self.zone.dns_name}",
                type="A",
                ttl=300,
                managed_zone=self.zone.name,
                rrdatas=[signoz_ip],
                opts=pulumi.ResourceOptions(parent=self),
            )

        self.register_outputs({
            "zone_name": self.zone.name,
            "stateful_hostname": self.hostname,
        })

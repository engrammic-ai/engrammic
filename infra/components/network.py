"""VPC, subnets, Cloud NAT, and firewall rules."""

import pulumi
from pulumi_gcp import compute, servicenetworking


class NetworkStack(pulumi.ComponentResource):
    """VPC network with private subnet and Cloud NAT for outbound."""

    def __init__(self, name: str, opts: pulumi.ResourceOptions | None = None):
        super().__init__("engrammic:network:NetworkStack", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")

        # VPC
        self.vpc = compute.Network(
            f"{name}-vpc",
            name=f"engrammic-{env}-vpc",
            auto_create_subnetworks=False,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Private subnet for compute
        self.private_subnet = compute.Subnetwork(
            f"{name}-private-subnet",
            name=f"engrammic-{env}-private",
            ip_cidr_range="10.0.2.0/24",
            region=pulumi.Config("gcp").require("region"),
            network=self.vpc.id,
            private_ip_google_access=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Cloud Router for NAT
        self.router = compute.Router(
            f"{name}-router",
            name=f"engrammic-{env}-router",
            network=self.vpc.id,
            region=pulumi.Config("gcp").require("region"),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Cloud NAT for outbound internet
        self.nat = compute.RouterNat(
            f"{name}-nat",
            name=f"engrammic-{env}-nat",
            router=self.router.name,
            region=pulumi.Config("gcp").require("region"),
            nat_ip_allocate_option="AUTO_ONLY",
            source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Firewall: allow internal traffic
        self.fw_internal = compute.Firewall(
            f"{name}-fw-internal",
            name=f"engrammic-{env}-allow-internal",
            network=self.vpc.id,
            allows=[
                compute.FirewallAllowArgs(protocol="tcp", ports=["0-65535"]),
                compute.FirewallAllowArgs(protocol="udp", ports=["0-65535"]),
                compute.FirewallAllowArgs(protocol="icmp"),
            ],
            source_ranges=["10.0.0.0/16"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Firewall: allow IAP SSH
        self.fw_iap_ssh = compute.Firewall(
            f"{name}-fw-iap-ssh",
            name=f"engrammic-{env}-allow-iap-ssh",
            network=self.vpc.id,
            allows=[compute.FirewallAllowArgs(protocol="tcp", ports=["22"])],
            source_ranges=["35.235.240.0/20"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Firewall: allow health checks
        self.fw_health = compute.Firewall(
            f"{name}-fw-health",
            name=f"engrammic-{env}-allow-health",
            network=self.vpc.id,
            allows=[compute.FirewallAllowArgs(protocol="tcp", ports=["8000"])],
            source_ranges=["130.211.0.0/22", "35.191.0.0/16"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Firewall: allow Cloud Run Direct VPC Egress to StatefulHost
        # Cloud Run uses IPs from the private subnet, not network tags
        self.fw_cloudrun_egress = compute.Firewall(
            f"{name}-fw-cloudrun-egress",
            name=f"engrammic-{env}-allow-cloudrun-egress",
            network=self.vpc.id,
            allows=[
                compute.FirewallAllowArgs(protocol="tcp", ports=["6333", "6379", "7687"]),
            ],
            source_ranges=["10.0.2.0/24"],  # Private subnet CIDR
            target_tags=["engrammic-stateful"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Firewall: allow Cloud Run to reach SigNoz OTLP collector
        self.fw_signoz_otlp = compute.Firewall(
            f"{name}-fw-signoz-otlp",
            name=f"engrammic-{env}-allow-signoz-otlp",
            network=self.vpc.id,
            allows=[
                compute.FirewallAllowArgs(protocol="tcp", ports=["4317", "4318"]),
            ],
            source_ranges=["10.0.2.0/24"],  # Private subnet CIDR
            target_tags=["signoz"],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # VPC Connector for Cloud Run
        self.vpc_connector = compute.Subnetwork(
            f"{name}-connector-subnet",
            name=f"engrammic-{env}-connector",
            ip_cidr_range="10.0.3.0/28",
            region=pulumi.Config("gcp").require("region"),
            network=self.vpc.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # TEI subnet in europe-west1 (T4 GPUs available)
        tei_region = config.get("tei_region") or "europe-west1"
        self.tei_subnet = compute.Subnetwork(
            f"{name}-tei-subnet",
            name=f"engrammic-{env}-tei",
            ip_cidr_range="10.0.4.0/24",
            region=tei_region,
            network=self.vpc.id,
            private_ip_google_access=True,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Private services access for Cloud SQL
        self.private_ip_range = compute.GlobalAddress(
            f"{name}-private-ip-range",
            name=f"engrammic-{env}-private-services",
            purpose="VPC_PEERING",
            address_type="INTERNAL",
            prefix_length=16,
            network=self.vpc.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.private_connection = servicenetworking.Connection(
            f"{name}-private-connection",
            network=self.vpc.id,
            service="servicenetworking.googleapis.com",
            reserved_peering_ranges=[self.private_ip_range.name],
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "vpc_id": self.vpc.id,
                "private_subnet_id": self.private_subnet.id,
                "connector_subnet_id": self.vpc_connector.id,
                "tei_subnet_id": self.tei_subnet.id,
            }
        )

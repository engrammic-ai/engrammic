"""Cloud SQL Postgres instance for managed database."""

import pulumi
from pulumi_gcp import sql


class CloudSQLPostgres(pulumi.ComponentResource):
    """Managed Cloud SQL Postgres instance."""

    def __init__(
        self,
        name: str,
        network_id: pulumi.Input[str],
        private_connection: pulumi.Resource | None = None,
        opts: pulumi.ResourceOptions | None = None,
    ):
        super().__init__("engrammic:cloudsql:CloudSQLPostgres", name, None, opts)

        config = pulumi.Config()
        gcp_config = pulumi.Config("gcp")
        env = config.require("environment")
        region = gcp_config.require("region")

        tier = config.get("cloudsql_tier") or "db-f1-micro"
        disk_size = int(config.get("cloudsql_disk_size") or "20")
        ha_enabled = config.get_bool("cloudsql_ha") or False
        max_connections = int(config.get("cloudsql_max_connections") or "100")

        self.instance = sql.DatabaseInstance(
            f"{name}-instance",
            name=f"engrammic-{env}",
            database_version="POSTGRES_16",
            region=region,
            deletion_protection=env == "prod",
            settings=sql.DatabaseInstanceSettingsArgs(
                edition="ENTERPRISE",
                tier=tier,
                disk_size=disk_size,
                disk_type="PD_SSD",
                disk_autoresize=True,
                availability_type="REGIONAL" if ha_enabled else "ZONAL",
                backup_configuration=sql.DatabaseInstanceSettingsBackupConfigurationArgs(
                    enabled=True,
                    start_time="03:00",
                    point_in_time_recovery_enabled=True,
                    transaction_log_retention_days=7,
                    backup_retention_settings=sql.DatabaseInstanceSettingsBackupConfigurationBackupRetentionSettingsArgs(
                        retained_backups=7,
                    ),
                ),
                ip_configuration=sql.DatabaseInstanceSettingsIpConfigurationArgs(
                    ipv4_enabled=False,
                    private_network=network_id,
                    enable_private_path_for_google_cloud_services=True,
                ),
                maintenance_window=sql.DatabaseInstanceSettingsMaintenanceWindowArgs(
                    day=7,
                    hour=4,
                ),
                database_flags=[
                    sql.DatabaseInstanceSettingsDatabaseFlagArgs(
                        name="max_connections",
                        value=str(max_connections),
                    ),
                ],
            ),
            opts=pulumi.ResourceOptions(
                parent=self,
                depends_on=[private_connection] if private_connection else [],
            ),
        )

        self.database = sql.Database(
            f"{name}-database",
            name="engrammic",
            instance=self.instance.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.user = sql.User(
            f"{name}-user",
            name="context",
            instance=self.instance.name,
            password=config.require_secret("postgres_password"),
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs({
            "instance_name": self.instance.name,
            "connection_name": self.instance.connection_name,
            "private_ip": self.instance.private_ip_address,
        })

"""Service accounts and IAM bindings."""

import pulumi
from pulumi_gcp import projects, serviceaccount


class IAMStack(pulumi.ComponentResource):
    """Service accounts for Cloud Run and GCE with appropriate role bindings."""

    def __init__(self, name: str, opts: pulumi.ResourceOptions | None = None):
        super().__init__("engrammic:iam:IAMStack", name, None, opts)

        config = pulumi.Config()
        env = config.require("environment")
        gcp_config = pulumi.Config("gcp")
        project = gcp_config.require("project")

        # Cloud Run service account
        self.context_service_run = serviceaccount.Account(
            f"{name}-context-service-run",
            account_id=f"context-service-run-{env}",
            display_name=f"Context Service Cloud Run ({env})",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Cloud Run roles
        cloud_run_roles = [
            "roles/secretmanager.secretAccessor",
            "roles/cloudtrace.agent",
            "roles/monitoring.metricWriter",
            "roles/aiplatform.user",
        ]
        for role in cloud_run_roles:
            role_suffix = role.split("/")[1].replace(".", "-")
            projects.IAMMember(
                f"{name}-run-{role_suffix}",
                project=project,
                role=role,
                member=self.context_service_run.email.apply(
                    lambda email: f"serviceAccount:{email}"
                ),
                opts=pulumi.ResourceOptions(parent=self),
            )

        # GCE stateful host service account
        self.stateful_host = serviceaccount.Account(
            f"{name}-stateful-host",
            account_id=f"stateful-host-{env}",
            display_name=f"Stateful Host GCE ({env})",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # GCE roles
        gce_roles = [
            "roles/secretmanager.secretAccessor",
            "roles/logging.logWriter",
            "roles/monitoring.metricWriter",
            "roles/artifactregistry.reader",  # Pull images from AR
            "roles/aiplatform.user",  # Dagster LLM calls via Vertex AI
        ]
        for role in gce_roles:
            role_suffix = role.split("/")[1].replace(".", "-")
            projects.IAMMember(
                f"{name}-gce-{role_suffix}",
                project=project,
                role=role,
                member=self.stateful_host.email.apply(lambda email: f"serviceAccount:{email}"),
                opts=pulumi.ResourceOptions(parent=self),
            )

        # Cloud Build service account
        self.cloud_build = serviceaccount.Account(
            f"{name}-cloud-build",
            account_id=f"cloudbuild-{env}",
            display_name=f"Cloud Build ({env})",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Cloud Build roles
        cloud_build_roles = [
            "roles/storage.objectAdmin",  # Upload source to GCS
            "roles/artifactregistry.writer",  # Push images to AR
            "roles/logging.logWriter",  # Write build logs
        ]
        for role in cloud_build_roles:
            role_suffix = role.split("/")[1].replace(".", "-")
            projects.IAMMember(
                f"{name}-cloudbuild-{role_suffix}",
                project=project,
                role=role,
                member=self.cloud_build.email.apply(lambda email: f"serviceAccount:{email}"),
                opts=pulumi.ResourceOptions(parent=self),
            )

        self.register_outputs(
            {
                "context_service_run_email": self.context_service_run.email,
                "stateful_host_email": self.stateful_host.email,
                "cloud_build_email": self.cloud_build.email,
            }
        )

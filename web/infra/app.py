import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
)
from constructs import Construct


APP_NAME = "stocks-dashboard"
REGION = "us-east-1"


@jsii.implements(cdk.ILocalBundling)
class LocalPythonBundling:
    def __init__(self, source_path):
        self.source_path = source_path

    def try_bundle(self, output_dir, options):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-compile",
                "--only-binary=:all:",
                "--platform",
                "manylinux2014_x86_64",
                "--python-version",
                "3.14",
                "--implementation",
                "cp",
                "--abi",
                "cp314",
                "--requirement",
                os.path.join(self.source_path, "requirements.txt"),
                "--target",
                output_dir,
            ],
            check=True,
        )
        shutil.copy2(
            os.path.join(self.source_path, "app.py"),
            os.path.join(output_dir, "app.py"),
        )
        return True


class StocksDashboardStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        budget_email = cdk.CfnParameter(
            self,
            "BudgetAlertEmail",
            type="String",
            description="Email address for the $5 monthly account budget alert.",
            allowed_pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
            no_echo=True,
        )

        table = dynamodb.Table(
            self,
            "Holdings",
            table_name=f"{APP_NAME}-holdings",
            partition_key=dynamodb.Attribute(
                name="id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        secret_key = kms.Key(
            self,
            "FinnhubSecretKey",
            alias=f"{APP_NAME}/finnhub",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
            pending_window=Duration.days(7),
        )
        secret_resource = secretsmanager.CfnSecret(
            self,
            "FinnhubSecret",
            name=f"{APP_NAME}/finnhub-api-key",
            description="Finnhub API key used by the stocks dashboard Lambda.",
            kms_key_id=secret_key.key_arn,
            tags=[cdk.CfnTag(key="Application", value=APP_NAME)],
        )
        secret_resource.apply_removal_policy(RemovalPolicy.DESTROY)

        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/aws/lambda/{APP_NAME}-api",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        api_role = iam.Role(
            self,
            "ApiExecutionRole",
            role_name=f"{APP_NAME}-api-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        api_log_group.grant_write(api_role)
        api_source = os.path.join(os.path.dirname(__file__), "..", "api")
        runtime = lambda_.Runtime.PYTHON_3_14
        hash_parts = [
            item
            for name in ("app.py", "requirements.txt")
            for item in (name.encode(), Path(api_source, name).read_bytes())
        ]
        asset_hash = hashlib.sha256(
            b"\0".join(hash_parts) + b"\0python314-linux-x86_64-v1"
        ).hexdigest()
        api_function = lambda_.Function(
            self,
            "Api",
            function_name=f"{APP_NAME}-api",
            code=lambda_.Code.from_asset(
                api_source,
                asset_hash=asset_hash,
                asset_hash_type=cdk.AssetHashType.CUSTOM,
                bundling=cdk.BundlingOptions(
                    image=runtime.bundling_image,
                    local=LocalPythonBundling(api_source),
                ),
            ),
            handler="app.lambda_handler",
            runtime=runtime,
            memory_size=512,
            timeout=Duration.seconds(30),
            log_group=api_log_group,
            role=api_role,
            environment={
                "TABLE_NAME": table.table_name,
                "FINNHUB_SECRET_ARN": secret_resource.attr_id,
            },
        )
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:PutItem"],
                resources=[table.table_arn],
            )
        )
        api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[secret_resource.attr_id],
            )
        )
        secret_key.grant_decrypt(api_role)

        site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=f"{APP_NAME}-{cdk.Aws.ACCOUNT_ID}-{REGION}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        access_log_group = logs.LogGroup(
            self,
            "SiteAccessLogGroup",
            log_group_name=f"/aws/s3/{APP_NAME}-access",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        delivery_source = logs.CfnDeliverySource(
            self,
            "SiteAccessLogSource",
            name="stocksdashs3",
            log_type="S3_SERVER_ACCESS_LOGS",
            resource_arn=site_bucket.bucket_arn,
        )
        delivery_destination = logs.CfnDeliveryDestination(
            self,
            "SiteAccessLogDestination",
            name="stockscwlogs",
            delivery_destination_type="CWL",
            destination_resource_arn=access_log_group.log_group_arn,
            output_format="json",
        )
        delivery = logs.CfnDelivery(
            self,
            "SiteAccessLogDelivery",
            delivery_source_name=delivery_source.name,
            delivery_destination_arn=delivery_destination.attr_arn,
        )
        delivery.node.add_dependency(delivery_source, delivery_destination)

        distribution = cloudfront.Distribution(
            self,
            "SiteDistribution",
            comment=APP_NAME,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

        api = apigw.HttpApi(
            self,
            "HttpApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=[f"https://{distribution.domain_name}"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.PUT,
                ],
                allow_headers=["content-type"],
                max_age=Duration.hours(1),
            ),
        )
        stage = api.default_stage.node.default_child
        stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=10,
            throttling_rate_limit=5,
        )

        integration = integrations.HttpLambdaIntegration("ApiIntegration", api_function)
        for path in ("/holdings", "/watchlist"):
            api.add_routes(
                path=path,
                methods=[apigw.HttpMethod.GET, apigw.HttpMethod.PUT],
                integration=integration,
            )
        for path in ("/portfolio", "/company"):
            api.add_routes(
                path=path,
                methods=[apigw.HttpMethod.GET],
                integration=integration,
            )

        s3_deployment.BucketDeployment(
            self,
            "WebsiteFiles",
            sources=[
                s3_deployment.Source.asset(
                    os.path.join(os.path.dirname(__file__), "..", "site")
                )
            ],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"{APP_NAME}-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=5,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL",
                            address=budget_email.value_as_string,
                        )
                    ],
                )
            ],
        )

        cdk.Tags.of(self).add("Application", APP_NAME)
        cdk.CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        cdk.CfnOutput(self, "WebsiteUrl", value=f"https://{distribution.domain_name}")
        cdk.CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        cdk.CfnOutput(self, "HoldingsTableName", value=table.table_name)
        cdk.CfnOutput(self, "FinnhubSecretArn", value=secret_resource.attr_id)


app = cdk.App()
StocksDashboardStack(
    app,
    "StocksDashboard",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=REGION,
    ),
)
app.synth()

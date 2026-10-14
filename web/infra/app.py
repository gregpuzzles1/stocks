import os
import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw, aws_apigatewayv2_integrations as integrations, aws_dynamodb as ddb, aws_lambda_python_alpha as lambda_python, aws_cloudfront as cf, aws_cloudfront_origins as origins, aws_s3 as s3, aws_s3_deployment as s3deploy
from constructs import Construct

class Stack(cdk.Stack):
  def __init__(self, scope: Construct, ident: str, **kw):
    super().__init__(scope, ident, **kw)
    key = cdk.CfnParameter(self, "FinnhubApiKey", no_echo=True)
    table = ddb.Table(self, "Holdings", partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING), removal_policy=cdk.RemovalPolicy.RETAIN)
    fn = lambda_python.PythonFunction(self, "Api", entry=os.path.join(os.path.dirname(__file__), "..", "api"), index="app.py", handler="lambda_handler", runtime=cdk.aws_lambda.Runtime.PYTHON_3_12, environment={"TABLE_NAME":table.table_name,"FINNHUB_API_KEY":key.value_as_string})
    table.grant_read_write_data(fn)
    api = apigw.HttpApi(self,"HttpApi",cors_preflight=apigw.CorsPreflightOptions(allow_origins=["*"],allow_methods=[apigw.CorsHttpMethod.ANY],allow_headers=["content-type"]))
    api.add_routes(path="/{proxy+}",methods=[apigw.HttpMethod.ANY],integration=integrations.HttpLambdaIntegration("Lambda",fn))
    bucket=s3.Bucket(self,"Site",block_public_access=s3.BlockPublicAccess.BLOCK_ALL)
    dist=cf.Distribution(self,"SiteDistribution",default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(bucket)))
    s3deploy.BucketDeployment(self, "WebsiteFiles", sources=[s3deploy.Source.asset(os.path.join(os.path.dirname(__file__), "..", "site"))], destination_bucket=bucket, distribution=dist, distribution_paths=["/*"])
    cdk.CfnOutput(self,"ApiUrl",value=api.api_endpoint); cdk.CfnOutput(self,"WebsiteUrl",value=f"https://{dist.domain_name}")
app=cdk.App(); Stack(app,"StocksDashboard"); app.synth()

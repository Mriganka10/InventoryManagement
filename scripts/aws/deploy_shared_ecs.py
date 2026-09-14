#!/usr/bin/env python3
"""Deploy WorkshopOS onto the existing cost-optimized Kairoz ECS platform.

The script is idempotent and deliberately refuses to trigger EC2 capacity scale-out
unless ALLOW_SCALE_OUT=1. Secrets are generated and stored without being printed.
"""

from __future__ import annotations

import json
import os
import secrets as secure_random
import subprocess
import time
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

REGION = os.getenv("AWS_REGION", "ap-south-1")
ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID", "453732174568")
STACK = os.getenv("PLATFORM_STACK", "kairoz-production-platform")
APP = "inventory"
REPOSITORY = "kairoz/inventory"
SOURCE_REPOSITORY = "https://github.com/Mriganka10/InventoryManagement.git"
SOURCE_BRANCH = os.getenv("SOURCE_BRANCH", "codex/end-to-end-inventory")
IMAGE_TAG = os.getenv("IMAGE_TAG", "")
SERVICE = "kairoz-inventory-web"
TASK_FAMILY = "kairoz-inventory-web"
TARGET_GROUP_NAME = "kairoz-inventory"
LOG_GROUP = "/kairoz/production/inventory"
RUNTIME_SECRET = "/kairoz/production/inventory/environment"
DATABASE_SECRET = "/kairoz/production/inventory/database"
DATABASE_NAME = "inventory"
DATABASE_USER = "inventory_app"
DATABASE_PORT = 5432
TASK_MEMORY_MIB = int(os.getenv("TASK_MEMORY_MIB", "384"))
TASK_CPU_UNITS = int(os.getenv("TASK_CPU_UNITS", "128"))
ALLOW_SCALE_OUT = os.getenv("ALLOW_SCALE_OUT", "0") == "1"


def client(name: str, *, region: str | None = REGION):
    return boto3.client(name, region_name=region) if region else boto3.client(name)


def stack_outputs() -> dict[str, str]:
    stack = client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
    return {x["OutputKey"]: x["OutputValue"] for x in stack["Outputs"]}


def assume_policy(service: str) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}]})


def ensure_role(iam, name: str, service: str, managed: list[str] | None = None) -> str:
    try:
        role = iam.get_role(RoleName=name)["Role"]
    except iam.exceptions.NoSuchEntityException:
        role = iam.create_role(
            RoleName=name, AssumeRolePolicyDocument=assume_policy(service),
            Tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Platform", "Value": "kairoz-shared"}, {"Key": "Application", "Value": APP}],
        )["Role"]
    for policy in managed or []:
        iam.attach_role_policy(RoleName=name, PolicyArn=policy)
    return role["Arn"]


def put_policy(iam, role: str, name: str, statements: list[dict]) -> None:
    iam.put_role_policy(RoleName=role, PolicyName=name, PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements}))


def ensure_repository(ecr) -> str:
    try:
        repository = ecr.describe_repositories(repositoryNames=[REPOSITORY])["repositories"][0]
    except ecr.exceptions.RepositoryNotFoundException:
        repository = ecr.create_repository(
            repositoryName=REPOSITORY, imageScanningConfiguration={"scanOnPush": True},
            imageTagMutability="IMMUTABLE",
            tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Application", "Value": APP}],
        )["repository"]
    return repository["repositoryUri"]


def ensure_bucket(s3) -> str:
    name = f"kairoz-inventory-prod-{ACCOUNT_ID}-{REGION}"
    try:
        s3.head_bucket(Bucket=name)
    except ClientError:
        s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_encryption(Bucket=name, ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    return name


def ensure_target_group_and_rule(elbv2) -> tuple[str, str, str]:
    load_balancer = elbv2.describe_load_balancers(Names=["kairoz-production"])["LoadBalancers"][0]
    listener = elbv2.describe_listeners(LoadBalancerArn=load_balancer["LoadBalancerArn"])["Listeners"][0]
    try:
        target_group = elbv2.describe_target_groups(Names=[TARGET_GROUP_NAME])["TargetGroups"][0]
    except elbv2.exceptions.TargetGroupNotFoundException:
        target_group = elbv2.create_target_group(
            Name=TARGET_GROUP_NAME, Protocol="HTTP", Port=8000, VpcId=load_balancer["VpcId"],
            TargetType="instance", HealthCheckProtocol="HTTP", HealthCheckPath="/health",
            Matcher={"HttpCode": "200"}, HealthyThresholdCount=2, UnhealthyThresholdCount=3,
        )["TargetGroups"][0]
        elbv2.add_tags(ResourceArns=[target_group["TargetGroupArn"]], Tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Application", "Value": APP}])
    rules = elbv2.describe_rules(ListenerArn=listener["ListenerArn"])["Rules"]
    exists = any(any(c.get("Field") == "http-header" and "inventory" in c.get("HttpHeaderConfig", {}).get("Values", []) for c in rule.get("Conditions", [])) for rule in rules)
    if not exists:
        priorities = {int(rule["Priority"]) for rule in rules if rule.get("Priority", "default").isdigit()}
        priority = next(x for x in range(50, 50000) if x not in priorities)
        elbv2.create_rule(
            ListenerArn=listener["ListenerArn"], Priority=priority,
            Conditions=[{"Field": "http-header", "HttpHeaderConfig": {"HttpHeaderName": "X-Kairoz-Application", "Values": ["inventory"]}}],
            Actions=[{"Type": "forward", "TargetGroupArn": target_group["TargetGroupArn"]}],
            Tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Application", "Value": APP}],
        )
    return target_group["TargetGroupArn"], load_balancer["DNSName"], listener["ListenerArn"]


def ensure_database(outputs: dict[str, str], secrets, iam, ssm, ecs) -> str:
    try:
        db_secret = secrets.get_secret_value(SecretId=DATABASE_SECRET)
        credentials = json.loads(db_secret["SecretString"])
        db_secret_arn = db_secret["ARN"]
    except secrets.exceptions.ResourceNotFoundException:
        credentials = {"username": DATABASE_USER, "password": secure_random.token_urlsafe(36)}
        db_secret_arn = secrets.create_secret(
            Name=DATABASE_SECRET, Description="Isolated WorkshopOS PostgreSQL credentials on shared RDS.",
            SecretString=json.dumps(credentials, separators=(",", ":")),
            Tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Application", "Value": APP}],
        )["ARN"]

    container_arns = ecs.list_container_instances(cluster=outputs["ClusterName"], status="ACTIVE")["containerInstanceArns"]
    if not container_arns:
        raise RuntimeError("The shared ECS cluster has no active host for database bootstrap.")
    host = ecs.describe_container_instances(cluster=outputs["ClusterName"], containerInstances=[container_arns[0]])["containerInstances"][0]
    instance_id = host["ec2InstanceId"]
    instance_role = "kairoz-production-ecs-instance"
    master_secret = outputs["DatabaseMasterSecretArn"]
    put_policy(iam, instance_role, "inventory-database-bootstrap-temporary", [{"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": [master_secret, db_secret_arn]}])
    command = "\n".join([
        "set -euo pipefail", "command -v psql >/dev/null || sudo dnf install -y postgresql18 >/dev/null",
        f"region={REGION}", f"endpoint={outputs['DatabaseEndpoint']}", f"master_secret='{master_secret}'", f"app_secret='{db_secret_arn}'",
        'master_json=$(aws secretsmanager get-secret-value --region "$region" --secret-id "$master_secret" --query SecretString --output text)',
        'app_json=$(aws secretsmanager get-secret-value --region "$region" --secret-id "$app_secret" --query SecretString --output text)',
        "master_user=$(echo \"$master_json\" | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"username\"])')",
        "export PGPASSWORD=$(echo \"$master_json\" | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"password\"])')",
        "app_password=$(echo \"$app_json\" | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"password\"])')",
        f"if ! psql -h \"$endpoint\" -U \"$master_user\" -d postgres -tAc \"select 1 from pg_roles where rolname='{DATABASE_USER}'\" | grep -q 1; then psql -h \"$endpoint\" -U \"$master_user\" -d postgres -v ON_ERROR_STOP=1 -c \"CREATE ROLE {DATABASE_USER} LOGIN PASSWORD '$app_password'\" >/dev/null; else psql -h \"$endpoint\" -U \"$master_user\" -d postgres -v ON_ERROR_STOP=1 -c \"ALTER ROLE {DATABASE_USER} PASSWORD '$app_password'\" >/dev/null; fi",
        f"if ! psql -h \"$endpoint\" -U \"$master_user\" -d postgres -tAc \"select 1 from pg_database where datname='{DATABASE_NAME}'\" | grep -q 1; then psql -h \"$endpoint\" -U \"$master_user\" -d postgres -v ON_ERROR_STOP=1 -c \"CREATE DATABASE {DATABASE_NAME}\" >/dev/null; fi",
        f"psql -h \"$endpoint\" -U \"$master_user\" -d postgres -v ON_ERROR_STOP=1 -c \"REVOKE ALL ON DATABASE {DATABASE_NAME} FROM PUBLIC; GRANT ALL ON DATABASE {DATABASE_NAME} TO {DATABASE_USER}\" >/dev/null",
        f"psql -h \"$endpoint\" -U \"$master_user\" -d {DATABASE_NAME} -v ON_ERROR_STOP=1 -c \"REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT ALL ON SCHEMA public TO {DATABASE_USER}\" >/dev/null",
        "unset PGPASSWORD master_json app_json app_password",
    ])
    try:
        time.sleep(10)
        run_ssm(ssm, instance_id, command, "Bootstrap isolated WorkshopOS database")
    finally:
        try:
            iam.delete_role_policy(RoleName=instance_role, PolicyName="inventory-database-bootstrap-temporary")
        except ClientError:
            pass
    user, password = quote(credentials["username"], safe=""), quote(credentials["password"], safe="")
    return f"postgresql://{user}:{password}@{outputs['DatabaseEndpoint']}:{DATABASE_PORT}/{DATABASE_NAME}"


def ensure_runtime_secret(secrets, database_url: str) -> tuple[str, list[dict]]:
    try:
        current = secrets.get_secret_value(SecretId=RUNTIME_SECRET)
        values = json.loads(current["SecretString"])
        arn = current["ARN"]
    except secrets.exceptions.ResourceNotFoundException:
        values = {}
        arn = secrets.create_secret(
            Name=RUNTIME_SECRET, Description="WorkshopOS production runtime configuration.", SecretString="{}",
            Tags=[{"Key": "Environment", "Value": "production"}, {"Key": "Application", "Value": APP}],
        )["ARN"]
    values.update({
        "INVENTORY_DATABASE_URL": database_url,
        "INVENTORY_SECRET_KEY": values.get("INVENTORY_SECRET_KEY") or secure_random.token_urlsafe(48),
        "INVENTORY_COOKIE_SECURE": "true", "INVENTORY_DEV_RETURN_OTP": "false",
        "INVENTORY_EMAIL_PROVIDER": "ses", "INVENTORY_SES_REGION": REGION,
    })
    secrets.put_secret_value(SecretId=RUNTIME_SECRET, SecretString=json.dumps(values, sort_keys=True, separators=(",", ":")))
    entries = [{"name": key, "valueFrom": f"{arn}:{key}::"} for key in sorted(values)]
    return arn, entries


def run_ssm(ssm, instance_id: str, command: str, comment: str, timeout: int = 900) -> str:
    command_id = ssm.send_command(InstanceIds=[instance_id], DocumentName="AWS-RunShellScript", Parameters={"commands": [command]}, Comment=comment, TimeoutSeconds=timeout)["Command"]["CommandId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "InvocationDoesNotExist":
                time.sleep(2); continue
            raise
        if result["Status"] in {"Success", "Failed", "Cancelled", "TimedOut"}:
            if result["Status"] != "Success":
                raise RuntimeError(f"{comment} failed ({result['Status']}): {result.get('StandardErrorContent', '')[-1500:]}")
            return result.get("StandardOutputContent", "")
        time.sleep(3)
    raise TimeoutError(f"{comment} did not finish in time.")


def capacity_and_host(ecs, cluster: str) -> tuple[str, dict[str, int]]:
    arns = ecs.list_container_instances(cluster=cluster, status="ACTIVE")["containerInstanceArns"]
    instances = ecs.describe_container_instances(cluster=cluster, containerInstances=arns)["containerInstances"]
    best = None
    for instance in instances:
        remaining = {x["name"]: int(x.get("integerValue", 0)) for x in instance["remainingResources"]}
        if remaining.get("MEMORY", 0) >= TASK_MEMORY_MIB and remaining.get("CPU", 0) >= TASK_CPU_UNITS:
            best = (instance["ec2InstanceId"], remaining); break
    if best:
        return best
    summary = [{"instance": x["ec2InstanceId"], "remaining": {r["name"]: r.get("integerValue", 0) for r in x["remainingResources"] if r["name"] in {"CPU", "MEMORY"}}} for x in instances]
    if not ALLOW_SCALE_OUT:
        raise RuntimeError(f"No existing ECS host has {TASK_MEMORY_MIB} MiB/{TASK_CPU_UNITS} CPU free. Refusing billable scale-out. Capacity: {summary}")
    if not instances:
        raise RuntimeError("No ECS host is available for image build.")
    return instances[0]["ec2InstanceId"], summary[0]["remaining"]


def build_image_on_host(ecr, iam, ssm, instance_id: str, image_uri: str, tag: str) -> None:
    try:
        ecr.describe_images(repositoryName=REPOSITORY, imageIds=[{"imageTag": tag}])
        print(f"Reusing immutable image {image_uri}:{tag}")
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    instance_role = "kairoz-production-ecs-instance"
    repository_arn = ecr.describe_repositories(repositoryNames=[REPOSITORY])["repositories"][0]["repositoryArn"]
    put_policy(iam, instance_role, "inventory-image-build-temporary", [
        {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart"], "Resource": repository_arn},
    ])
    directory = f"/tmp/workshopos-build-{tag}"
    command = "\n".join([
        "set -euo pipefail", "sudo dnf install -y git >/dev/null", f"rm -rf '{directory}'", f"git clone --depth 1 --branch '{SOURCE_BRANCH}' '{SOURCE_REPOSITORY}' '{directory}' >/dev/null",
        f"cd '{directory}'", f"aws ecr get-login-password --region '{REGION}' | docker login --username AWS --password-stdin '{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com' >/dev/null",
        f"docker build -t '{image_uri}:{tag}' .", f"docker push '{image_uri}:{tag}'", f"rm -rf '{directory}'",
    ])
    try:
        time.sleep(10)
        run_ssm(ssm, instance_id, command, "Build and push WorkshopOS image", timeout=1200)
    finally:
        try:
            iam.delete_role_policy(RoleName=instance_role, PolicyName="inventory-image-build-temporary")
        except ClientError:
            pass


def register_task(ecs, execution_role: str, task_role: str, secrets_entries: list[dict], image_uri: str, tag: str) -> str:
    result = ecs.register_task_definition(
        family=TASK_FAMILY, taskRoleArn=task_role, executionRoleArn=execution_role,
        networkMode="bridge", requiresCompatibilities=["EC2"], runtimePlatform={"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
        containerDefinitions=[{
            "name": "web", "image": f"{image_uri}:{tag}", "essential": True,
            "cpu": TASK_CPU_UNITS, "memoryReservation": TASK_MEMORY_MIB,
            "portMappings": [{"containerPort": 8000, "hostPort": 0, "protocol": "tcp"}],
            "environment": [{"name": "AWS_REGION", "value": REGION}, {"name": "HOST", "value": "0.0.0.0"}, {"name": "PORT", "value": "8000"}],
            "secrets": secrets_entries,
            "logConfiguration": {"logDriver": "awslogs", "options": {"awslogs-group": LOG_GROUP, "awslogs-region": REGION, "awslogs-stream-prefix": "web"}},
            "healthCheck": {"command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"], "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 60},
        }],
        tags=[{"key": "Environment", "value": "production"}, {"key": "Application", "value": APP}],
    )
    return result["taskDefinition"]["taskDefinitionArn"]


def upsert_service(ecs, cluster: str, capacity_provider: str, task: str, target_group: str) -> None:
    services = ecs.list_services(cluster=cluster)["serviceArns"]
    exists = any(x.rsplit("/", 1)[-1] == SERVICE for x in services)
    deployment = {"maximumPercent": 200, "minimumHealthyPercent": 0, "deploymentCircuitBreaker": {"enable": True, "rollback": True}}
    if exists:
        ecs.update_service(cluster=cluster, service=SERVICE, taskDefinition=task, desiredCount=1, forceNewDeployment=True, deploymentConfiguration=deployment)
    else:
        ecs.create_service(
            cluster=cluster, serviceName=SERVICE, taskDefinition=task, desiredCount=1,
            capacityProviderStrategy=[{"capacityProvider": capacity_provider, "weight": 1, "base": 1}],
            placementStrategy=[{"type": "binpack", "field": "memory"}],
            deploymentConfiguration=deployment, healthCheckGracePeriodSeconds=180,
            loadBalancers=[{"targetGroupArn": target_group, "containerName": "web", "containerPort": 8000}],
            enableECSManagedTags=True, propagateTags="TASK_DEFINITION",
        )
    ecs.get_waiter("services_stable").wait(cluster=cluster, services=[SERVICE], WaiterConfig={"Delay": 15, "MaxAttempts": 60})


def ensure_distribution(cloudfront, alb_dns: str) -> tuple[str, str]:
    marker = "WorkshopOS inventory via shared Kairoz ALB"
    paginator = cloudfront.get_paginator("list_distributions")
    for page in paginator.paginate():
        for distribution in page.get("DistributionList", {}).get("Items", []):
            if distribution.get("Comment") == marker:
                return distribution["Id"], distribution["DomainName"]
    origin_id = "kairoz-inventory-origin"
    config = {
        "CallerReference": f"inventory-{int(time.time())}", "Comment": marker, "Enabled": True,
        "Origins": {"Quantity": 1, "Items": [{"Id": origin_id, "DomainName": alb_dns, "OriginPath": "", "CustomHeaders": {"Quantity": 1, "Items": [{"HeaderName": "X-Kairoz-Application", "HeaderValue": "inventory"}]}, "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "http-only", "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}, "OriginReadTimeout": 60, "OriginKeepaliveTimeout": 5}, "ConnectionAttempts": 3, "ConnectionTimeout": 10, "OriginShield": {"Enabled": False}}]},
        "DefaultCacheBehavior": {
            "TargetOriginId": origin_id, "ViewerProtocolPolicy": "redirect-to-https", "Compress": True, "SmoothStreaming": False,
            "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"], "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
            "ForwardedValues": {"QueryString": True, "Cookies": {"Forward": "all"}, "Headers": {"Quantity": 4, "Items": ["Origin", "Access-Control-Request-Headers", "Access-Control-Request-Method", "Authorization"]}, "QueryStringCacheKeys": {"Quantity": 0}},
            "MinTTL": 0, "DefaultTTL": 0, "MaxTTL": 0,
            "TrustedSigners": {"Enabled": False, "Quantity": 0}, "TrustedKeyGroups": {"Enabled": False, "Quantity": 0},
            "LambdaFunctionAssociations": {"Quantity": 0}, "FunctionAssociations": {"Quantity": 0}, "FieldLevelEncryptionId": "",
        },
        "CacheBehaviors": {"Quantity": 0}, "CustomErrorResponses": {"Quantity": 0},
        "Logging": {"Enabled": False, "IncludeCookies": False, "Bucket": "", "Prefix": ""},
        "PriceClass": "PriceClass_100", "ViewerCertificate": {"CloudFrontDefaultCertificate": True, "MinimumProtocolVersion": "TLSv1"},
        "Restrictions": {"GeoRestriction": {"RestrictionType": "none", "Quantity": 0}}, "WebACLId": "", "HttpVersion": "http2and3", "IsIPV6Enabled": True,
    }
    result = cloudfront.create_distribution(DistributionConfig=config)["Distribution"]
    cloudfront.get_waiter("distribution_deployed").wait(Id=result["Id"], WaiterConfig={"Delay": 30, "MaxAttempts": 40})
    return result["Id"], result["DomainName"]


def main() -> None:
    identity = client("sts").get_caller_identity()
    if identity["Account"] != ACCOUNT_ID:
        raise RuntimeError(f"Expected AWS account {ACCOUNT_ID}, got {identity['Account']}.")
    outputs = stack_outputs()
    ecs, iam, ecr = client("ecs"), client("iam", region=None), client("ecr")
    secrets, ssm, logs = client("secretsmanager"), client("ssm"), client("logs")
    s3, elbv2, cloudfront = client("s3"), client("elbv2"), client("cloudfront", region=None)
    image_uri = ensure_repository(ecr); bucket = ensure_bucket(s3)
    try:
        logs.create_log_group(logGroupName=LOG_GROUP, tags={"Environment": "production", "Application": APP})
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=30)
    target_group, alb_dns, _ = ensure_target_group_and_rule(elbv2)
    host_id, remaining = capacity_and_host(ecs, outputs["ClusterName"])
    print(f"Capacity preflight passed on existing host; remaining before deploy: {remaining}")
    database_url = ensure_database(outputs, secrets, iam, ssm, ecs)
    runtime_arn, secret_entries = ensure_runtime_secret(secrets, database_url)
    execution_name = "kairoz-production-inventory-execution"
    execution_role = ensure_role(iam, execution_name, "ecs-tasks.amazonaws.com", ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"])
    put_policy(iam, execution_name, "read-inventory-runtime-secret", [{"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": runtime_arn}])
    task_name = "kairoz-production-inventory-task"
    task_role = ensure_role(iam, task_name, "ecs-tasks.amazonaws.com")
    put_policy(iam, task_name, "inventory-runtime", [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"], "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]},
        {"Effect": "Allow", "Action": ["ses:GetEmailIdentity", "ses:CreateEmailIdentity", "ses:SendEmail", "sesv2:SendEmail"], "Resource": "*"},
        {"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "*"},
    ])
    tag = IMAGE_TAG or subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], text=True).strip()
    build_image_on_host(ecr, iam, ssm, host_id, image_uri, tag)
    task = register_task(ecs, execution_role, task_role, secret_entries, image_uri, tag)
    upsert_service(ecs, outputs["ClusterName"], outputs["CapacityProviderName"], task, target_group)
    distribution_id, domain = ensure_distribution(cloudfront, alb_dns)
    print(json.dumps({"status": "deployed", "service": SERVICE, "task_definition": task, "cloudfront_distribution_id": distribution_id, "public_url": f"https://{domain}"}, indent=2))


if __name__ == "__main__":
    main()

"""Produce a reviewable CloudFormation template; never embeds a GitHub token."""
import json
from pathlib import Path


def template():
    sub = lambda value: {"Fn::Sub": value}
    ref = lambda name: {"Ref": name}
    arn = lambda name: {"Fn::GetAtt": [name, "Arn"]}
    resources = {
        "GitHubSecret": {"Type": "AWS::SecretsManager::Secret", "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain", "Properties": {"Name": "market-stress/portfolio/github-actions",
            "Description": "Target-repository Actions execution token. Empty until supplied privately by its owner.",
            "SecretString": '{"token":""}'}},
        "DispatchTable": {"Type": "AWS::DynamoDB::Table", "Properties": {
            "BillingMode": "PAY_PER_REQUEST", "AttributeDefinitions": [{"AttributeName": "dispatch_key", "AttributeType": "S"}],
            "KeySchema": [{"AttributeName": "dispatch_key", "KeyType": "HASH"}],
            "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
            "SSESpecification": {"SSEEnabled": True}}},
        "FailureQueue": {"Type": "AWS::SQS::Queue", "Properties": {
            "MessageRetentionPeriod": 1209600, "SqsManagedSseEnabled": True}},
        "LogGroup": {"Type": "AWS::Logs::LogGroup", "Properties": {
            "LogGroupName": "/aws/lambda/market-stress-portfolio-dispatch", "RetentionInDays": 14}},
        "ScheduleGroup": {"Type": "AWS::Scheduler::ScheduleGroup", "Properties": {"Name": "market-stress-portfolio"}},
    }
    resources["LambdaRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "Policies": [{"PolicyName": "portfolio-dispatch-only", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": ref("GitHubSecret")},
            {"Effect": "Allow", "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"], "Resource": arn("DispatchTable")},
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": arn("LogGroup")},
            {"Effect": "Allow", "Action": ["sqs:SendMessage"], "Resource": arn("FailureQueue")},
        ]}}]}}
    resources["Dispatcher"] = {"Type": "AWS::Lambda::Function", "Properties": {
        "FunctionName": "market-stress-portfolio-dispatch", "Runtime": "python3.13", "Handler": "index.handler",
        # New accounts can have a concurrency quota of 10, below the usual
        # unreserved minimum. Do not reserve account capacity for two daily jobs.
        "Role": arn("LambdaRole"), "MemorySize": 128, "Timeout": 45,
        "Environment": {"Variables": {"GITHUB_REPOSITORY": "tina77302/market-portfolio-risk-intelligence",
            "GITHUB_SECRET_ARN": ref("GitHubSecret"), "DISPATCH_TABLE": ref("DispatchTable")}},
        "Code": {"ZipFile": Path(__file__).with_name("portfolio_dispatch.py").read_text()}}}
    resources["AsyncFailures"] = {"Type": "AWS::Lambda::EventInvokeConfig", "Properties": {
        "FunctionName": ref("Dispatcher"), "Qualifier": "$LATEST", "MaximumEventAgeInSeconds": 3600,
        "MaximumRetryAttempts": 2, "DestinationConfig": {"OnFailure": {"Destination": arn("FailureQueue")}}}}
    resources["SchedulerRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"}, "Action": "sts:AssumeRole", "Condition": {
            "StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")},
            "ArnEquals": {"aws:SourceArn": arn("ScheduleGroup")}}}]},
        "Policies": [{"PolicyName": "invoke-portfolio-dispatch", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["lambda:InvokeFunction"], "Resource": arn("Dispatcher")},
            {"Effect": "Allow", "Action": ["sqs:SendMessage"], "Resource": arn("FailureQueue")},
        ]}}]}}
    for name, kind, cron in (("CollectSchedule", "collect", "cron(37 23 ? * MON-FRI *)"),
                              ("WatchSchedule", "watch", "cron(17 2 * * ? *)")):
        resources[name] = {"Type": "AWS::Scheduler::Schedule", "Properties": {
            "Name": "market-stress-portfolio-" + kind, "GroupName": ref("ScheduleGroup"),
            "ScheduleExpression": cron, "ScheduleExpressionTimezone": "UTC", "FlexibleTimeWindow": {"Mode": "OFF"},
            "State": {"Fn::If": ["SchedulesEnabled", "ENABLED", "DISABLED"]}, "Target": {
                "Arn": arn("Dispatcher"), "RoleArn": arn("SchedulerRole"),
                "Input": json.dumps({"kind": kind, "scheduled_for": "<aws.scheduler.scheduled-time>"}),
                "RetryPolicy": {"MaximumEventAgeInSeconds": 3600, "MaximumRetryAttempts": 2},
                "DeadLetterConfig": {"Arn": arn("FailureQueue")}}}}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Portfolio validation external trigger; disabled until GitHub credential and end-to-end verification succeed.",
        "Parameters": {"EnableSchedules": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]}},
        "Conditions": {"SchedulesEnabled": {"Fn::Equals": [ref("EnableSchedules"), "true"]}},
        "Resources": resources, "Outputs": {
            "DispatcherArn": {"Value": arn("Dispatcher")}, "SchedulerRoleArn": {"Value": arn("SchedulerRole")},
            "GitHubSecretArn": {"Value": ref("GitHubSecret")}, "FailureQueueUrl": {"Value": ref("FailureQueue")},
            "ScheduleGroup": {"Value": ref("ScheduleGroup")}, "SchedulesEnabled": {"Value": ref("EnableSchedules")}}}


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))

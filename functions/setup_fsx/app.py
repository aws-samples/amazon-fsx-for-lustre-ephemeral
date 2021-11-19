
from io import UnsupportedOperation
import boto3
import os
import random
import datetime

fsx_client      = boto3.client('fsx')
event_client    = boto3.client('events')

EVENT_NAME_PREFIX   = os.environ.get('event_name_prefix')

def lambda_handler(event, context):
    print("Received Event: {}".format(event))
    
    print("Using boto3 version: {}".format(boto3.__version__))
    try:
        print(event)
        operation           = event["operation"]
        
        if operation == "create":
            return create_file_system(event)
        
        if operation == "status":
            return get_status(event)
        
        if operation == "delete":
            return delete_file_system(event)

    except Exception as e:
        print(e)
        raise e

def create_file_system(event):
    # Get subnet IDs from environment variables
    subnet              = random.choice(os.environ['SUBNETS'].split(","))
    security_group      = random.choice(os.environ['SECURITY_GROUPS'].split(",")) 
    print("Using subnet: {}. Security group: {}".format(subnet,security_group))

    team           = event["team"]
    bucket         = event["bucket"]
    
    import_path    = "s3://{}/{}".format(bucket,team)
    fsx_name       = "{}-{}".format(team, bucket)
    # fsx_name            = feature # Temp code to revert back.

    response = fsx_client.create_file_system(
        ClientRequestToken=fsx_name,
        FileSystemType='LUSTRE',
        StorageCapacity=4800,
        StorageType='SSD',
        SubnetIds=[str(subnet)],
        # SecurityGroupIds=[security_group],
        Tags=[
            { 'Key': 'Name',        'Value': fsx_name},
            { 'Key': 'Ephemeral',   'Value': "true"},
            { 'Key': 'CreatedBy',   'Value': "MLOps"},
            { 'Key': 'CreatedAt',   'Value': str(datetime.datetime.now())}
        ],
        LustreConfiguration={
            'DeploymentType': 'SCRATCH_2',
            'ImportPath': import_path,
            'AutoImportPolicy': 'NEW_CHANGED'        
        }        
    )
    handleResponse(response)

    fsx_client.tag_resource(
        ResourceARN=response["FileSystem"]["ResourceARN"],
        Tags=[
            {
                'Key': 'ClaimedAt',
                'Value': str(datetime.datetime.now())
            },
        ]
    )
    
    enable_event()
    
    return {
        'id': response['FileSystem']['FileSystemId']
    }

def get_status(event):
    response = fsx_client.describe_file_systems(
        FileSystemIds=[
            event["file_system_id"]
        ]
    )
    handleResponse(response)

    # add a check for the data repository
    data_repository_status = response['FileSystems'][0]['LustreConfiguration']['DataRepositoryConfiguration']['Lifecycle']
    if data_repository_status == 'MISCONFIGURED':
        return data_repository_status
    elif data_repository_status != 'AVAILABLE':
        return data_repository_status
    else:
        return response['FileSystems'][0]['Lifecycle']

def delete_file_system(event):
    response = fsx_client.delete_file_system(
        FileSystemId=event["file_system_id"]
    )
    handleResponse(response)
    return response['Lifecycle']

def enable_event():
    # Get all the event rules for the prefix
    response = event_client.list_rules(NamePrefix=EVENT_NAME_PREFIX,Limit=1)
    if response['Rules']:
        event_name = response['Rules'][0]['Name']
        print("Enabling event: {}".format(event_name))
        response = event_client.enable_rule(Name=event_name)
    else:
        print("No event rules found with prefix {}".format(EVENT_NAME_PREFIX))

def handleResponse(res):
    http_status_code = res['ResponseMetadata']['HTTPStatusCode']
    if http_status_code != 200:
        raise Exception(
            'Invalid http status code: {}'.format(http_status_code))
    else:
        print(res)

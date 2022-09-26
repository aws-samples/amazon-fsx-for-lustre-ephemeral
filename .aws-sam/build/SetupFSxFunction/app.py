"""Lambda function to handel creation and deletion of FSx."""
import os
import random
import datetime
import boto3
from botocore.exceptions import ClientError

## -- Global Boto3 clients --
FSX_CLIENT: object = boto3.client('fsx')
EVENTS_CLIENT: object = boto3.client('events')

# -- Environment varaibles --
EVENT_NAME_PREFIX: str = os.environ.get('EVENT_NAME_PREFIX')

def lambda_handler(event: dict, context: object):
    """Main method called when function is invoked. Orchestrates actions
       to perform based on operation.
    Args:
        event (dict): The invocation event passed to the lambda function.
        context (object): Metadata about the function during runtime.
    Raises:
        ex: All exceptions in the handler and in helper methods.
    """
    print('Invocation event: %s', event)
    print('Using boto3 version %s', boto3.__version__)

    try:
        operation: str = event["operation"]

        if operation == "create":
            create_file_system(event)

        if operation == "status":
            get_status(event)

        if operation == "delete":
            delete_file_system(event)

    except Exception as ex:
        print(ex)
        raise ex

def create_file_system(event) -> dict:
    """Creates a new FSx file system with the boto3 client.
    Args:
        event (dict): The invocation event passed to the lambda function.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
        val_ex: Python error when there exists a wrong value.
    Returns:
        dict: The returned file system id.
    """
    try:
        # -- Get subnet IDs from environment variables --
        subnet: str = random.choice(os.environ['SUBNETS'].split(","))
        security_group: str = random.choice(os.environ['SECURITY_GROUPS'].split(","))
        print('Using subnet (%s) and Security group (%s).', subnet, security_group)

        import_path: str = f's3://{event["bucket"]}/{event["team"]}'
        fsx_name: str = f'{event["team"]}-{event["bucket"]}'

        response: dict = FSX_CLIENT.create_file_system(
            ClientRequestToken=fsx_name,
            FileSystemType='LUSTRE',
            StorageCapacity=4800,
            StorageType='SSD',
            SubnetIds=[subnet],
            SecurityGroupIds=[security_group],
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

        FSX_CLIENT.tag_resource(
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

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

    except ValueError as val_ex:
        print('Value Error: %s', val_ex)
        raise val_ex

def get_status(event: dict) -> str:
    """Get the status from the FSx lifecycle with boto3.
    Args:
        event (dict): The invocation event passed to the lambda function.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
    Returns:
        str: The FSx status.
    """
    try:
        response: dict = FSX_CLIENT.describe_file_systems(
            FileSystemIds=[
                event["file_system_id"]
            ]
        )

        handleResponse(response)
        config: dict = response['FileSystems'][0]['LustreConfiguration']
        status: str = config['DataRepositoryConfiguration']['Lifecycle']

        return status

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

def delete_file_system(event: dict) -> str:
    """Deletes the FSx file system.
    Args:
         event (dict): The invocation event passed to the lambda function.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
    Returns:
        str: The FSx status.
    """
    try:
        response: dict = FSX_CLIENT.delete_file_system(
            FileSystemId=event["file_system_id"]
        )

        handleResponse(response)

        return response['Lifecycle']

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

def enable_event():
    """Enables the event bridge rule.
    Raises:
        event_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
    """
    try:
        # Get all the event rules for the prefix
        response: dict = EVENTS_CLIENT.list_rules(NamePrefix=EVENT_NAME_PREFIX,Limit=1)

        if response['Rules']:
            event_name: str = response['Rules'][0]['Name']
            print('Enabling event: %s', event_name)
            EVENTS_CLIENT.enable_rule(Name=event_name)

        else:
            print('No event rules found with prefix %s.', EVENT_NAME_PREFIX)

    except ClientError as event_ex:
        print('Client Error: %s', event_ex)
        raise event_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

def handleResponse(res: dict):
    """Handles 200 http reponses. If a response is not 200, its
       likely the expected behavior did not occur.
    Args:
        res (dict): Boto3 client reponse data.
    Raises:
        Exception: Custom Exception
    """
    http_status_code = res['ResponseMetadata']['HTTPStatusCode']
    if http_status_code != 200:
        raise Exception('Invalid http status code: %s', http_status_code)

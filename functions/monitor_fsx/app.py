import os
import boto3
from datetime import date, datetime, timedelta, tzinfo
from botocore.exceptions import ClientError

# -- Get all external configurable external variables --
PERIOD: int = int(os.environ['DATA_POINTS_PERIOD_SECS'])
MERTIC_INTERVAL: int = int(os.environ['METRIC_INTERVAL_MINS'])
SNS_TOPIC: str = os.environ.get('SNS_ARN')
EVENT_NAME_PREFIX: str = os.environ.get('EVENT_NAME_PREFIX')
CLAIMED_TIME_MINS: int = int(os.environ.get('CLAIMED_TIME_MINS'))

# -- Boto3 clients --
RSC_TAG_CLIENT: object = boto3.client('resourcegroupstaggingapi')
CW_CLIENT: object = boto3.client('cloudwatch')
EVENTS_CLIENT: object = boto3.client('events')
FSX_CLIENT: object = boto3.client('fsx')
SNS_CLIENT: object = boto3.client('sns')

# -- Methods and logic --
def lambda_handler(event: dict, context: object):
    """Main method in module used to orchestrate helper methods to monitor
       FSx file systems.
    Args:
        event (dict): Information passed to the function during invocation.
        context (object): Metadata about the function during runtime.
    Raises:
        all_ex: General Exception to raise and catch everythin in handler and
                in helper methods.
    """
    try:
        print('Invocation event: %s', event)
        
        storage_list: list = get_filesystems()
        print('File systems: %s', storage_list)

        start_time: datetime= datetime.utcnow() - timedelta(minutes=MERTIC_INTERVAL)
        end_time: datetime = datetime.utcnow()

        for storage in storage_list:
            # REVIEW
            print('Checking file system: %s.', storage)

            claim_time: datetime = get_claim_time_in_minutes(storage)
            elapsed_time: datetime = get_minutes_elapsed_since_creation(storage)
            state: str = get_storage_lifecycle(storage)
            
            if storage and determine_active_fsx(claim_time, elapsed_time, state):
                # --  Determine total IOPs --
                total_iops_values: float = get_total_iops(storage, start_time, end_time)

                if total_iops_values:
                    average_iops: float = sum(total_iops_values) / len(total_iops_values)

                else:
                    average_iops: float = 0.0

                print('Average IOPS for %s is: %s.', storage, average_iops)

                # -- 0.35 is average threashold when FSx is not being used. --
                if average_iops >= 0.40:
                    pass

                # -- Initiate a delete when average IOPS is 0. --
                else:
                    print('Deleting FSx %s.', storage)
                    response: dict = FSX_CLIENT.delete_file_system(FileSystemId=storage)

                    # -- Send message to SNS topic --
                    send_email(storage, elapsed_time)

        post_check()

    except Exception as all_ex:
        # -- Catches and raises all exceptions orchestrated by the handler. 
        # Raises up exceptions caught and raised in helper methods. --
        print('Exception: %s', all_ex)
        raise all_ex

def get_filesystems() -> list:
    """A method to get available filesystems by tags via boto3 and pagination.
    Raises:
        rsc_tag_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found. 
        val_ex: Python error when there exists a wrong value.
    Returns:
        list: filesystems
    """
    try:
        fsx_paginator = RSC_TAG_CLIENT.get_paginator('get_resources')
        fsx_iterator = fsx_paginator.paginate(
            TagFilters=[
                {
                    'Key': 'Ephemeral',
                    'Values': [
                        'true',
                    ]
                },
                {
                    'Key': 'CreatedBy',
                    'Values': [
                        'MLOps',
                    ]
                }
            ],
            ResourceTypeFilters=[
                'fsx',
            ],
            IncludeComplianceDetails=False,
            ExcludeCompliantResources=False
        )
        fs_list: list = []
        for fsx_page in fsx_iterator:
            for resource in fsx_page['ResourceTagMappingList']:
                arn = resource['ResourceARN']
                fs_id = arn.split('/')[1]
                fs_list.append(fs_id)

        return fs_list

    except ClientError as rsc_tag_ex:
        print('Client Error: %s', rsc_tag_ex)
        raise rsc_tag_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

    except ValueError as val_ex:
        print('Value Error: %s', val_ex)
        raise val_ex

def get_minutes_elapsed_since_creation(storage: str) -> datetime:
    """Caluclates the time since the file system was created.
    Args:
        storage (str): The file system.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found. 
        val_ex: Python error when there exists a wrong value.
    Returns:
        datetime: The elapsed time since creation.
    """
    try:
        response: dict = FSX_CLIENT.describe_file_systems(
            FileSystemIds=[
                storage,
            ],
        )

        creation_time: datetime = response['FileSystems'][0]['CreationTime']
        tz: tzinfo = creation_time.tzinfo
        present_time: datetime = datetime.now(tz)

        difference: datetime = present_time - creation_time
        elapsed: datetime = difference.seconds / 60
        print('Time elapsed since creation: %s mins', elapsed)
        return elapsed

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

    except ValueError as val_ex:
        print('Value Error: %s', val_ex)
        raise val_ex

def get_storage_lifecycle(storage: str) -> str:
    """Via the boto3 client, gets and returns the lifecycle attribute
       for the filesystem.
    Args:
        storage (str): The file system.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found. 
    Returns:
        str: The lifecycle attribute.
    """
    try:
        response: dict = FSX_CLIENT.describe_file_systems(
            FileSystemIds=[
                storage,
            ],
        )
        return response['FileSystems'][0]['Lifecycle']

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

def get_claim_time_in_minutes(storage: str) -> datetime:
    """Returns the amount of time the file system has been claimed.
    Args:
        storage (str): The file system.
    Raises:
        fsx_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found. 
        val_ex: Python error when there exists a wrong value.
    Returns:
        datetime: The difference in time.
    """
    try:
        claimed_time_string: str = ""
        response: dict = FSX_CLIENT.describe_file_systems(
            FileSystemIds=[
                storage,
            ],
        )

        for tag in response['FileSystems'][0]['Tags']:
            if tag["Key"] == "ClaimedAt":
                claimed_time_string = tag["Value"]

        if claimed_time_string != "":
            time_now: datetime = datetime.strptime(str(datetime.now()), '%Y-%m-%d %H:%M:%S.%f')
            claimed_time: datetime = datetime.strptime(claimed_time_string, '%Y-%m-%d %H:%M:%S.%f')
            diff_minutes: datetime = (time_now - claimed_time).total_seconds() / 60
            print('Claim Time Diff: %s', diff_minutes)
            return diff_minutes
        else:
            return CLAIMED_TIME_MINS + 5

    except ClientError as fsx_ex:
        print('Client Error: %s', fsx_ex)
        raise fsx_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

    except ValueError as val_ex:
        print('Value Error: %s', val_ex)
        raise val_ex

def send_email(storage: str, uptime: datetime):
    """Sends an email via sns.
    Args:
        storage (str): The file system.
        uptime (datetime): The period of time since the file system
                           was created.
    Raises:
        sns_ex: Errors from the boto3 client.
    """
    try:
        message: str = f'No activity on FSx for Luster File System ID {storage} for {PERIOD} minutes.\
            Delete has been initiated. Uptime: {uptime} mins.'

        subject: str = f'Unused FSx for Lustre ID: {storage} deletion.'

        SNS_CLIENT.publish(
            TopicArn=SNS_TOPIC,
            Subject=subject,
            Message=message
        )
    except ClientError as sns_ex:
        print('Client Error: %s', sns_ex)
        raise sns_ex

def get_total_iops(storage: str, start_time: datetime, end_time: datetime) -> float:
    """Uses the CloudWatch boto3 client to get the iops usage for the file system.
    Args:
        storage (str): The file system.
        start_time (datetime): Time interval to start gathering metrics.
        end_time (datetime): Time interval closest to recent time.
    Raises:
        cw_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
    Returns:
        float: The Iops metric.
    """
    try:
        response: dict = CW_CLIENT.get_metric_data(
            MetricDataQueries=[
                {
                    'Id': 'm1',
                    'MetricStat': {
                        'Metric': {
                            'Namespace': 'AWS/FSx',
                            'MetricName': 'DataReadOperations',
                            'Dimensions': [
                                {
                                    'Name': 'FileSystemId',
                                    'Value': storage
                                },
                            ]
                        },
                        'Period': PERIOD,
                        'Stat': 'Sum',
                        'Unit': 'Count'
                    },
                    'Label': 'DataReadOperations',
                    'ReturnData': False,
                },
                {
                    'Id': 'm2',
                    'MetricStat': {
                        'Metric': {
                            'Namespace': 'AWS/FSx',
                            'MetricName': 'DataWriteOperations',
                            'Dimensions': [
                                {
                                    'Name': 'FileSystemId',
                                    'Value': storage
                                },
                            ]
                        },
                        'Period': PERIOD,
                        'Stat': 'Sum',
                        'Unit': 'Count'
                    },
                    'Label': 'DataWriteOperations',
                    'ReturnData': False,
                },
                {
                    'Id': 'm3',
                    'MetricStat': {
                        'Metric': {
                            'Namespace': 'AWS/FSx',
                            'MetricName': 'MetadataOperations',
                            'Dimensions': [
                                {
                                    'Name': 'FileSystemId',
                                    'Value': storage
                                },
                            ]
                        },
                        'Period': PERIOD,
                        'Stat': 'Sum',
                        'Unit': 'Count'
                    },
                    'Label': 'MetadataOperations',
                    'ReturnData': False,
                },
                {
                    'Id': 'e1',
                    'Expression': "SUM(METRICS())/PERIOD(m1)",
                    'Label': 'Total IOPS'
                },
            ],
            StartTime=start_time,
            EndTime=end_time
        )

        return response['MetricDataResults'][0]['Values']

    except ClientError as cw_ex:
        print('Client Error: %s', cw_ex)
        raise cw_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

def determine_active_fsx(claim_time: datetime, elapsed_time: datetime, state: str) -> bool:
    """Based on time-boxing and file system state, is the file system active?
    Args:
        claim_time (datetime): The time betweent the claim and now.
        elapsed_time (datetime): The time since creation.
        state (str): The lifecycle state of the file system.
    Raises:
        assert_ex: Assertion errors.
    Returns:
        bool: If the FSx meets the active criteria.
    """
    try:
        active: bool = False

        if claim_time > CLAIMED_TIME_MINS:
            if elapsed_time > MERTIC_INTERVAL:
                if state != "DELETING":
                    active = True

        return active

    except AssertionError as assert_ex:
        raise assert_ex

def post_check():
    """After the checks and possible clean-ups are complete, check for file systems
       and events. If FSx do not exist, then clean up the event. 
    Raises:
        events_ex: Errors from the boto3 client.
        key_ex: Python error when a key in a mapping is not found.
    """
    try:
        storage_list: list = get_filesystems()
        if storage_list:
            print('Existing file systems: %s', str(storage_list))
            pass

        else:
            # -- Get all the event rules for the prefix --
            response: dict = EVENTS_CLIENT.list_rules(
                NamePrefix=EVENT_NAME_PREFIX,
                Limit=1
            )

            if 'Rules' in response:
                event_name: str = response['Rules'][0]['Name']
                print('Disabling event: %s', event_name)
                EVENTS_CLIENT.disable_rule(Name=event_name)

            else:
                print('No event rules found with prefix %s', EVENT_NAME_PREFIX)

    except ClientError as events_ex:
        print('Client Error: %s', events_ex)
        raise events_ex

    except KeyError as key_ex:
        print('Key Error: %s', key_ex)
        raise key_ex

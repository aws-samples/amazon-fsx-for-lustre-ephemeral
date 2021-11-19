import os
import boto3
from datetime import datetime, timedelta

# Get all external configurable external variables
PERIOD = int(os.environ['data_points_period_secs'])
MERTIC_INTERVAL = int(os.environ['metric_interval_mins'])
SNS_TOPIC = os.environ.get('sns_arn')
EVENT_NAME_PREFIX = os.environ.get('event_name_prefix')
CLAIMED_TIME_MINS = int(os.environ.get('claimed_time_mins'))

# Get all the clients needed
cw_client = boto3.client('cloudwatch')
event_client = boto3.client('events')
fsx_client = boto3.client('fsx')


# Get all available file systems based on the specified tags
def get_filesystems():
    rsc_tag_client = boto3.client('resourcegroupstaggingapi')
    fsx_paginator = rsc_tag_client.get_paginator('get_resources')
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
    fs_list = []
    for fsx_page in fsx_iterator:
        for resource in fsx_page['ResourceTagMappingList']:
            arn = resource['ResourceARN']
            fs_id = arn.split('/')[1]
            fs_list.append(fs_id)
        return fs_list


# Calculate the time from FSx creation.
def get_minutes_elapsed_since_creation(storage):
    response = fsx_client.describe_file_systems(
        FileSystemIds=[
            storage,
        ],
    )

    creation_time = response['FileSystems'][0]['CreationTime']
    tz = creation_time.tzinfo
    present_time = datetime.now(tz)

    difference = present_time - creation_time
    mins = difference.seconds / 60
    print("Time elapsed since creation: {} mins".format(mins))
    return mins


# Get file system lifecyle state. We are looking for Available file systems.
def get_storage_lifecycle(storage):
    response = fsx_client.describe_file_systems(
        FileSystemIds=[
            storage,
        ],
    )

    return response['FileSystems'][0]['Lifecycle']


# get the amount of minutes the file system has been claimed
def get_claim_time_in_minutes(storage):
    claimed_time_string = ""
    response = fsx_client.describe_file_systems(
        FileSystemIds=[
            storage,
        ],
    )

    for tag in response['FileSystems'][0]['Tags']:
        if tag["Key"] == "ClaimedAt":
            claimed_time_string = tag["Value"]
            # print(claimed_time_string)

    if claimed_time_string != "":
        time_now = datetime.strptime(str(datetime.now()), '%Y-%m-%d %H:%M:%S.%f')
        # print(time_now)
        claimed_time = datetime.strptime(claimed_time_string, '%Y-%m-%d %H:%M:%S.%f')
        diff_minutes = (time_now - claimed_time).total_seconds() / 60
        print("Claim Time Diff: " + str(diff_minutes))
        return diff_minutes
    else:
        return CLAIMED_TIME_MINS + 5


def send_email(storage, uptime):
    message = "No activity on FSx for Luster File System ID {} for {} minutes. Delete has been initiated. Uptime: {} mins".format(
        storage, PERIOD, uptime)
    subject = 'Unused FSx for Lustre ID: {} deletion'.format(storage)

    boto3.client('sns').publish(
        TopicArn=SNS_TOPIC,
        Subject=subject,
        Message=message
    )


# Main lambda controller.
def lambda_handler(event, context):
    print("Received Event: {}".format(event))
    
    storage_list = get_filesystems()
    print(storage_list)

    start_time = datetime.utcnow() - timedelta(minutes=MERTIC_INTERVAL)
    end_time = datetime.utcnow()

    for storage in storage_list:
        if storage != "" and get_claim_time_in_minutes(storage) > CLAIMED_TIME_MINS \
                and get_minutes_elapsed_since_creation(storage) > MERTIC_INTERVAL \
                and get_storage_lifecycle(storage) != "DELETING":
            print(storage)
            response = cw_client.get_metric_data(
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

            #  Determine total IOPs
            average_iops = 0
            total_iops_values = response['MetricDataResults'][0]['Values']
            if total_iops_values:
                average_iops = sum(total_iops_values) / len(total_iops_values)

            # Initiate a delete when average IOPS is 0.
            print("Average IOPS for this check is: {}".format(average_iops))
            if average_iops >= 0.40:  # 0.35 is average threashold when FSx is not being used.
                pass
            else:
                # Get total uptime for running FSx
                uptime = get_minutes_elapsed_since_creation(storage)

                print("Deleting FSx: {}".format(storage))
                response = fsx_client.delete_file_system(FileSystemId=storage)

                # Send message to SNS topic
                send_email(storage, uptime)

    storage_list = get_filesystems()
    if storage_list:
        print("File systems still exists={}".format(str(storage_list)))
        pass
    else:
        # Get all the event rules for the prefix
        response = event_client.list_rules(
            NamePrefix=EVENT_NAME_PREFIX,
            Limit=1
        )
        if response['Rules']:
            event_name = response['Rules'][0]['Name']
            print("Disabling event: {}".format(event_name))
            response = event_client.disable_rule(Name=event_name)
        else:
            print("No event rules found with prefix {}".format(EVENT_NAME_PREFIX))

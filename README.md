## Amazon FSx for Lustre Ephemeral

This project explains the solution for the blogpost whose title will be automate the creation of ephemeral FSx for Lustre. This project will include Lambda function, Step functions and Cloudformation to setup everything.

# Pre-requisites

* You need to have a bucket with the data that needs to be mounted.

# Commands

Run following command to setup this project.
```
aws s3api create-bucket --bucket <my-bucket>
aws s3 cp sample-data/ s3://<my-bucket> --recursive
virtualenv venv --python=python3
source venv/bin/activate
sam build
sam deploy --guided
sam build && sam deploy --no-confirm-changeset
```

# Verify

Execute step function with below input
```
{
  "team": "<my-team>",
  "bucket": "<my-bucket>",
  "phase":"<phase>"
}
```
`team`: Team name paramater can be provided to share the FSx across multiple use cases within the same team. This refers to the architecture diagram in the blog. 

`bucket`: Bucket can be existing bucket or you can use above instructions to create it. This bucket needs to be have data that can be made available on FSx for validation purpose. 

`phase`: Phase is a part of machine learning process where you can share the file systems between 2 models in train or predict phase within same team. 

> This solution uses these parameters to calculate the name of the FSx file system so make sure you proivide unique names. 

> All these parameters were introduced to enable FSx sharing between team for different models and phases. Not necessarily you have to follow the same approach but this is just an example to provide a bigger context about the use case.


# Cleanup

Execute following command and provide input as `y` to cleanup all the resources
```
sam delete
```

AND S3 Clean-up

> Also make sure to delete any FSx file systems if left out.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
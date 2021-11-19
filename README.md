## Amazon FSx for Lustre Ephemeral

This project explains the solution for the blogpost whose title will be automate the creation of ephemeral FSx for Lustre. This project will include Lambda function, Step functions and Cloudformation to setup everything.

# Pre-requisites

* You need to have a bucket with the data that needs to be mounted.

# Commands

Run following command to setup this project.
```
aws s3api create-bucket --bucket ephemeral-fsx-for-lustre-demo
aws s3 cp sample-data/ s3://ephemeral-fsx-for-lustre-demo --recursive
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
  "team": "teamA",
  "bucket": "ephemeral-fsx-for-lustre-demo",
  "phase":"train"
}
```

# Cleanup

Execute following command and provide input as `y` to cleanup all the resources
```
sam delete
```

> Also make sure to delete any FSx file systems if left out.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
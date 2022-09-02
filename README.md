## Parse AWS bill from S3 Bucket through lambda function, post purchase order through to QuickFile API

1) SES Receives Mail containing bill PDF attachment
2) SES stores email in S3 bucket
3) Event triggered on Lambda function to parse document from S3 bucket for billing details
   1) Grab PDF attachment, convert to JPEG for use by AWS Textract
   2) Extract billing details
4) Post to QuickFile API to create Purchase and Payment objects

## Build Poppler for Amazon Lambda as a layer
Poppler binaries for AWS Lambda. Required for pdf2image package
Available at https://github.com/jeylabs/aws-lambda-poppler-layer/

Download `poppler.zip` file from [releases](https://github.com/jeylabs/aws-lambda-poppler-layer/releases) and create / update your custom layer in AWS. You can add this layer to any Lambda function you want – no matter what runtime.

## Usage
Upload zip package of files to AWS lambda function, Python 3.9.
Assign environment variables from QuickFile configuration
WIll automatically trigger when new bill is available
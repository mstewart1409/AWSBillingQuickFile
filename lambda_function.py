#!/usr/bin/env python3

import os
import sys
import subprocess

# pip install custom package to /tmp/ and add to path
subprocess.call('pip install -r requirements.txt -t /tmp/ --no-cache-dir'.split(), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
sys.path.insert(1, '/tmp/')

import boto3
import json
import requests
import hashlib
from datetime import datetime, timedelta
import uuid
import email
import re
import io
import base64
from pdf2image import convert_from_path


def get_timestamp():
    current = datetime.now()
    return (str(current.year) + '-' + str(current.month) + '-' + str(current.day) + '-' + str(current.hour) + '-' + str(
        current.minute) + '-' + str(current.second))


def process_attachment(event):
    # Get current timestamp
    timestamp = get_timestamp()

    # Initiate boto3 client
    s3 = boto3.client('s3')

    # Get s3 object contents based on bucket name and object key; in bytes and convert to string
    data = s3.get_object(Bucket=event['Records'][0]['s3']['bucket']['name'],
                         Key=event['Records'][0]['s3']['object']['key'])
    contents = data['Body'].read().decode("utf-8")

    # Given the s3 object content is the ses email, get the message content and attachment using email package
    msg = email.message_from_string(contents)
    filename = None
    if msg.get_content_maintype() == 'multipart':  # multipart messages only
        # loop on the parts of the mail
        for part in msg.walk():
            # find the attachment part - so skip all the other parts
            if part.get_content_maintype() == 'multipart': continue
            if part.get_content_maintype() == 'text': continue
            if part.get('Content-Disposition') == 'inline': continue
            if part.get('Content-Disposition') is None: continue

            # save the attachment in the program directory
            filename = part.get_filename()

    attachment = msg.get_payload()[1]
    from_address = msg['from']
    regex = "\\<(.*?)\\>"
    from_address = re.findall(regex, from_address)[0]
    from_domain = from_address.split('@')[1]
    if from_domain == str(os.environ.get('EmailDomain')):

        # Write the attachment to a temp location
        open('/tmp/attach.pdf', 'wb').write(attachment.get_payload(decode=True))

        # Upload the file at the temp location to destination s3 bucket and append timestamp to the filename
        # Destination S3 bucket is hard coded to 'legacy-applications-email-attachment'. This can be configured as a parameter
        # Extracted attachment is temporarily saved as attach.csv and then uploaded to attach-upload-<timestamp>.csv
        try:
            key = 'invoices/' + filename + '.pdf'
            s3.upload_file('/tmp/attach.pdf', 'awsreceipts2', key)
            print("Upload Successful")
        except FileNotFoundError:
            print("The file was not found")
            return None

        return filename
    print("Couldn't verify email origin")
    return None


def post_to_quickfile(amount, supplier_ref, receipt_date, filename):
    # print(response)
    #receipt_date = datetime.strptime(r_date, '%Y-%m-%d')
    attachment = open("/tmp/attach.pdf", "rb")

    purchase_body = {
        "PurchaseData": {
            "SupplierID": str(os.environ.get('SupplierId')),
            "ReceiptDate": receipt_date.strftime('%Y-%m-%d'),
            "TermDays": "0",
            "SupplierReference": supplier_ref,
            "Currency": "GBP",
            "InvoiceLines": {
                "ItemLine": {
                    "ItemNominalCode": "7506",
                    "ItemDescription": "AWS Services",
                    "SubTotal": str(amount),
                    "VatRate": "20"
                }
            },
            "PaymentData": {
                "PaidDate": receipt_date.strftime('%Y-%m-%d'),
                "BankNominalCode": "1201",
                "PayMethod": "DCARD",
                "AmountPaid": str(float(amount) * 1.2)
            }
        }
    }
    purchase_response = post_response(os.environ.get('PurchaseEndpoint'), purchase_body)

    purchase_id = json.loads(purchase_response.text)["Purchase_Create"]["Body"]["PurchaseID"]

    doc_body = {
        "DocumentDetails": {
            "FileName": filename,
            "EmbeddedFileBinaryObject": base64.b64encode(attachment.read()),
            "Type": {
                "Receipt": {
                    "PurchaseId": str(purchase_id),
                    "CaptureDateTime": receipt_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "ReceiptName": filename
                }
            }
        }
    }
    resp = post_response(os.environ.get('DocumentEndpoint'), doc_body)
    return resp.text


def get_cost_explorer():
    # Create a Cost Explorer client
    client = boto3.client('ce')

    # Set time range to cover the last full calendar month
    # Note that the end date is EXCLUSIVE (e.g., not counted)
    now = datetime.utcnow()
    # Set the end of the range to start of the current month
    end = datetime(year=now.year, month=now.month, day=1)
    # Subtract a day and then "truncate" to the start of previous month
    start = end - timedelta(days=1)
    start = datetime(year=start.year, month=start.month, day=1)

    # Convert them to strings
    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')

    ce_response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start,
            'End': end
        },
        Granularity='MONTHLY',
        Filter={
            'Dimensions': {
                'Key': 'RECORD_TYPE',
                'Values': [
                    'Usage', 'Tax'
                ]
            }
        },
        Metrics=["BlendedCost", "UnblendedCost", "UsageQuantity", "AmortizedCost", "NetAmortizedCost",
                 "NetUnblendedCost", "NormalizedUsageAmount"]
    )

    """GroupBy=[
        {
            'Type': 'TAG',
            'Key': 'Project'
        },
    ], """


def post_response(url, body):
    submission_id = str(uuid.uuid4())
    acc_number = str(os.environ.get('AccNumber'))
    api_key = str(os.environ.get('APIKey'))
    hash_key = hashlib.md5((acc_number + api_key + submission_id).encode())

    data = {
        "payload": {
            "Header": {
                "MessageType": "Request",
                "SubmissionNumber": submission_id,
                "Authentication": {
                    "AccNumber": acc_number,
                    "MD5Value": hash_key.hexdigest(),
                    "ApplicationID": str(os.environ.get('AppId'))
                }
            },
            "Body": body
        }
    }

    response = requests.post(url, json=data)
    return response


def extract_data():
    client = boto3.client('textract')

    # convert pdf to jpeg, use page 1 only
    page = convert_from_path('/tmp/attach.pdf', fmt='jpeg')

    # convert to byte array for use in textract
    img_byte_arr = io.BytesIO()
    page[0].save(img_byte_arr, format=page[0].format)
    img_byte_arr = img_byte_arr.getvalue()

    response = client.analyze_expense(Document={'Bytes': img_byte_arr})
    # t_doc = TAnalyzeExpenseDocumentSchema().load(response)

    print('Extracted data')

    return response


def parse_textract(response):
    invoice_id = None
    charge = None
    receipt_date = None
    for expense_doc in response["ExpenseDocuments"]:
        for line_item_group in expense_doc["LineItemGroups"]:
            for line_items in line_item_group["LineItems"]:
                for expense_fields in line_items["LineItemExpenseFields"]:
                    if "ValueDetection" in expense_fields:
                        if "Net Charges (After Credits/Discounts, excl. Tax)" in expense_fields["ValueDetection"]['Text'] \
                                and "GBP" in expense_fields["ValueDetection"]['Text']:
                            charge = expense_fields["ValueDetection"]['Text'].split(
                                "Net Charges (After Credits/Discounts, excl. Tax)")[1].split('USD')[0].split('GBP')[1].strip()

        for summary_field in expense_doc["SummaryFields"]:
            if "LabelDetection" in summary_field and "ValueDetection" in summary_field:
                if summary_field["LabelDetection"]['Text'] == 'VAT Invoice Number:':
                    invoice_id = summary_field["ValueDetection"]['Text']
                elif summary_field["LabelDetection"]['Text'] == 'VAT Invoice Date:':
                    receipt_date = datetime.strptime(summary_field["ValueDetection"]['Text'], "%B %d, %Y")
    return invoice_id, charge, receipt_date


def lambda_handler(event, context):
    # print(event)
    filename = process_attachment(event)

    if filename is not None:
        response = extract_data()
        invoice_id, charge, receipt_date = parse_textract(response)
        #print(invoice_id, charge, receipt_date)

        result = post_to_quickfile(charge, invoice_id, receipt_date, filename)
        print(result)
        # Clean up the file from temp location
        os.remove('/tmp/attach.pdf')

    return {
        'statusCode': 200,
        'body': json.dumps([])
    }


if __name__ == "__main__":
    lambda_handler({}, {})

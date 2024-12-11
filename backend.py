'''
This file is used for running the flask application and connecting to different services:
- SageMaker Inference Endpoint
- S3
- Lambda
- DynamoDB
'''

import json
import os

import boto3
from flask import Flask, request, jsonify
from flask_cors import CORS
from botocore.exceptions import ClientError

app = Flask(__name__)

# Cors - Change this for Prod
CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                "http://localhost:5173",
                "https://main.ds37782qp0di8.amplifyapp.com",
            ]
        }
    },
)


# Required AWS credentials
os.environ["AWS_ACCESS_KEY_ID"] = "REMOVED_FOR_SECURITY"
os.environ["AWS_SECRET_ACCESS_KEY"] = "REMOVED_FOR_SECURITY"
os.environ["AWS_DEFAULT_REGION"] = "us-east-2"

# Dynamo DB required configuration
USER_METADATA_TABLE_NAME = "user-metadata"
DYNAMODB_RESOURCE = boto3.resource("dynamodb")
DYNAMODB_TABLE = "user-metadata"
USER_METADATA_TABLE = DYNAMODB_RESOURCE.Table(USER_METADATA_TABLE_NAME)

# SageMaker Parameters
SAGEMAKER_RESOURCE = boto3.client(
    "sagemaker-runtime",
    aws_access_key_id="REMOVED_FOR_SECURITY",
    aws_secret_access_key="REMOVED_FOR_SECURITY",
    region_name="us-east-2",
)
SAGEMAKER_ENDPOINT_NAME = "huggingface-pytorch-tgi-inference-2024-12-08-15-56-08-806"

# S3 Parameters

S3_CLIENT = boto3.client("s3")
BUCKET_NAME = "ece1779-chat-history"

# Lambda Parameters
LAMBDA_CLIENT = boto3.client("lambda")
LAMBDA_FUNCTION_NAME = "AddChatHistory"


def check_dynamo_db_user_name(username: str):
    """
    Checks if the username exists in the DynamoDB
    - username: string
    """
    response = USER_METADATA_TABLE.get_item(Key={"username": username})
    return response


@app.route("/chatbot_response", methods=["POST"])
def chatbot_response():
    """
    Run model invocation by calling SageMaker Inference Endpoint
    - username: string
    - chat_id: int 
    - prompt: string
    """
    data = request.get_json()
    print(data)

    instructions = """You are a friendly and empathetic companion.
    Engage in meaningful conversations, respond empathetically to the user's
    feelings and thoughts, and gently decline inappropriate or harmful topics. 
    Respond to this prompt only:
    """
    payload = {
        "inputs": instructions + data["prompt"],
        "parameters": {
            "max_new_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "return_full_text": False,
        },
    }

    model_response = SAGEMAKER_RESOURCE.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=json.dumps(payload).encode("utf-8"),
    )

    model_response = model_response["Body"].read().decode("utf-8")
    model_response = json.loads(model_response)
    model_reply = model_response[0]["generated_text"][1:]

    print(f"Model Response: {model_reply}")

    model_history_entry = {"prompt": data["prompt"], "model_response": model_reply}

    payload = {
        "username": data["username"],
        "chat_id": data["chat_id"],
        "model_history_entry": model_history_entry,
    }
    LAMBDA_CLIENT.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType="Event",  # Wait for the response
        Payload=json.dumps(payload),
    )

    return jsonify({"status_code": 200, "response": model_reply})


@app.route("/user_authentication", methods=["POST"])
def user_authentication():
    """
    Checks if the username and password combination exists in the
    DynamoDB. If yes, then return 200 else return 400
    - username: string
    - password: string
    """
    data = request.get_json()

    if not data or not data.get("username") or not data.get("password"):
        return jsonify(
            {"status_code": 400, "message": "Username and password are required."}
        )

    response = check_dynamo_db_user_name(data["username"])
    if "Item" in response.keys():
        if response["Item"]["password"] == data["password"]:
            return jsonify({"status_code": 200, "message": "Login was successful"})

        return jsonify(
            {"status_code": 400, "message": "Incorrect password. Try again."}
        )

    return jsonify({"status_code": 400, "message": "Username does not exist."})


@app.route("/get_chat_history", methods=["POST"])
def get_chat_history():
    """
    Retrieves the chat history by connecting with S3 and parsing JSON files
    - username: string
    """
    data = request.get_json()
    response = check_dynamo_db_user_name(data["username"])

    if "Item" not in response:
        return jsonify({"status_code": 400, "message": "User does not exist"}), 400

    # Convert chat_count to an integer
    chat_count = int(response["Item"]["chat_count"])
    chat_history = []

    if chat_count != 0:
        for i in range(1, chat_count + 1):
            key = f"{data['username']}/{i}.json"
            try:
                # Attempt to fetch the object
                response = S3_CLIENT.get_object(Bucket=BUCKET_NAME, Key=key)
                file_content = response["Body"].read().decode("utf-8")
                json_dict = json.loads(file_content)
                print(f"Successfully read JSON from S3: {json_dict}")
                curr_chat_history = {i: json_dict}
                chat_history.append(curr_chat_history)
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchKey":
                    print(f"Key not found: {key}")
                    continue
                raise FileNotFoundError(f"Error accessing the S3 file: {str(e)}") from e

    return jsonify({"status_code": 200, "chat_history": chat_history})


@app.route("/new_chat", methods=["POST"])
def new_chat():
    """
    Create a new chat by creating an empty JSON file in S3 and incrementing
    chat_id for the user in DynamoDB
    - username: string
    """
    data = request.get_json()
    username = data["username"]

    response = USER_METADATA_TABLE.update_item(
        Key={"username": username},
        UpdateExpression="ADD chat_count :increment",
        ExpressionAttributeValues={":increment": 1},
        ReturnValues="UPDATED_NEW",
    )

    new_chat_id = int(response["Attributes"]["chat_count"])

    # Create a placeholder JSON file in S3 for the new chat
    placeholder = []
    key = f"{username}/{new_chat_id}.json"
    try:
        S3_CLIENT.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(placeholder),
            ContentType="application/json",
        )
        print(f"Created placeholder file in S3: {key}")
    except ClientError as e:
        print(f"Failed to create placeholder file in S3: {e}")
        return (
            jsonify({"status_code": 500, "message": "Failed to initialize new chat"}),
            500,
        )
    return jsonify({"status_code": 200, "chat_id": new_chat_id})


@app.route("/user_creation", methods=["POST"])
def user_creation():
    """
    Checks if the provided username is in the DynamoDB table, if not
    then a new user is created with the provided password. 
    - username: string
    - password: string
    """
    # Read the Dynamo DB
    data = request.get_json()
    response = check_dynamo_db_user_name(data["username"])

    if "Item" in response.keys():
        return jsonify(
            {
                "status_code": 400,
                "message": "User profile already exists. Try logging in.",
            }
        )

    USER_METADATA_TABLE.put_item(
        Item={
            "username": data["username"],
            "password": data["password"],
            "chat_count": 0
            # Can add any other required metadata
        }
    )
    return jsonify(
        {
            "status_code": 200,
            "message": "Account Creation was successful. Now try logging in.",
        }
    )


if __name__ == "__main__":
    # Used to test - local server
    app.run(host="0.0.0.0", port=5000)

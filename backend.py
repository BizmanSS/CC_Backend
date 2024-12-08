from flask import Flask, request, jsonify
from flask_cors import CORS
from botocore.exceptions import ClientError
import boto3
import os
import json

app = Flask(__name__)

#Cors - Change this for Prod
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}})


# Required AWS credentials
os.environ["AWS_ACCESS_KEY_ID"] = ""
os.environ["AWS_SECRET_ACCESS_KEY"] = ""
os.environ["AWS_DEFAULT_REGION"] = "us-east-2"
# Required resources
USER_METADATA_TABLE_NAME = "user-metadata"
DYNAMODB_RESOURCE = boto3.resource('dynamodb')
SAGEMAKER_RESOURCE = boto3.client(
    'sagemaker-runtime',
    aws_access_key_id="",
    aws_secret_access_key="",
    region_name='us-east-2'
)
USER_METADATA_TABLE = DYNAMODB_RESOURCE.Table(USER_METADATA_TABLE_NAME)  
S3_CLIENT = boto3.client('s3')
LAMBDA_CLIENT = boto3.client('lambda')
LAMBDA_FUNCTION_NAME = "AddChatHistory"
BUCKET_NAME = 'ece1779-chat-history'
SAGEMAKER_ENDPOINT_NAME = "huggingface-pytorch-tgi-inference-2024-12-08-15-56-08-806"


def check_dynamo_db_user_name (username: str):
    response = USER_METADATA_TABLE.get_item(Key={'username': username})
    return response

def receive_last_five_prompts (username, chat_id):
    key = f"{username}/{chat_id}.json"
    # Attempt to fetch the object
    response = S3_CLIENT.get_object(Bucket=BUCKET_NAME, Key=key)
    file_content = response['Body'].read().decode('utf-8')
    json_dict = json.loads(file_content)
    print(json_dict)
    print(len(json_dict))
    if len(json_dict)<5:
        num_prompts =  len(json_dict)
    else:
        num_prompts = 5

    recent_prompts = json_dict[-num_prompts:]
    print(len(recent_prompts))
    recent_prompts = [hist["prompt"] for hist in recent_prompts]

    return recent_prompts


DYNAMODB_TABLE = "user-metadata"
# curl -X POST -H "Content-Type: application/json" \
#     -d '{"username":"John", "prompt": "Hello how are you?", "chat_id": 2}' \
#     "http://127.0.0.1:5000/chatbot_response"
@app.route('/chatbot_response', methods=['POST'])
def chatbot_response():
    # Run Model Invocation
    data = request.get_json()
    print(data)


    instructions =  """instructions: You are a friendly and empathetic companion. 
                    Engage in meaningful conversations, respond empathetically to the user's 
                    feelings and thoughts, and gently decline inappropriate or harmful topics by saying,
                    'I'm sorry, but I can't assist with that.' 
                    Keep your responses clear, concise, and supportive. 
                    Use the following past conversation as context to understand and respond appropriately:
                """
    past_five_prompts = receive_last_five_prompts(data['username'], data['chat_id'])
    # Use the following past conversation as context to understand and respond appropriately: My name is Anubhav I live in India I am 23 years old I study in University of Toronto current_task: Current Task: Respond to this prompt only:'Hi, how are you? Do you remember my name?'
    instructions = "You are a friendly and empathetic companion. Engage in meaningful conversations, respond empathetically to the user's feelings and thoughts, and gently decline inappropriate or harmful topics by saying. Respond to this prompt only :"
    payload = {
        "inputs": instructions + " ".join(past_five_prompts) + "Current Task: Respond to this prompt only:" + data['prompt'],
        "parameters": {
            "max_new_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "return_full_text": False

        }
    }

    model_response = SAGEMAKER_RESOURCE.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType='application/json',
        Body=json.dumps(payload).encode('utf-8')
    )

    model_response = model_response['Body'].read().decode('utf-8')
    model_response = json.loads(model_response)
    model_reply = model_response[0]["generated_text"][1:]

    print(f"Model Response: {model_reply}")

    model_history_entry = {
        "prompt": data["prompt"],
        "model_response": model_reply
    }

    payload = {
        "username": data['username'],
        "chat_id": data["chat_id"],
        "model_history_entry": model_history_entry
    }
    LAMBDA_CLIENT.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType='Event',  # Wait for the response
        Payload=json.dumps(payload)
    )


    return jsonify({"status_code":200, "response": model_reply})


@app.route('/user_authentication', methods=['POST'])
# curl -X POST -H "Content-Type: application/json" \
#     -d '{"username":"John","password":"30"}' \
#     "http://127.0.0.1:5000/user_authentication"
def user_authentication():
    data = request.get_json()

    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"status_code": 400, "message": "Username and password are required."})

    response = check_dynamo_db_user_name(data["username"])
    if "Item" in response.keys():
        if response["Item"]['password'] == data['password']:
            return jsonify({"status_code": 200, "message": "Login was successful"})
        else:
            return jsonify({"status_code": 400, "message": "Incorrect password. Try again."})

    return jsonify({"status_code": 400, "message": "Username does not exist."})


@app.route('/get_chat_history', methods=["POST"])
# curl -X GET -H "Content-Type: application/json" \
#     -d '{"username":"John","chat_id": 1}' \
#     "http://127.0.0.1:5000/get_chat_history"
def get_chat_history():
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
                file_content = response['Body'].read().decode('utf-8')
                json_dict = json.loads(file_content)
                print(f"Successfully read JSON from S3: {json_dict}")
                curr_chat_history = {i: json_dict}
                chat_history.append(curr_chat_history)
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    print(f"Key not found: {key}")
                    continue  # Skip missing keys
                else:
                    # Raise unexpected errors
                    raise
            except Exception as e:
                print(f"Unexpected error fetching {key}: {e}")
                return jsonify({"status_code": 500, "message": "Error fetching chat history"}), 500

    return jsonify({"status_code": 200, "chat_history": chat_history})


@app.route('/new_chat', methods=["POST"])
# curl -X POST -H "Content-Type: application/json" \
#     -d '{"username":"John","password":30}' \                                              
#     "http://127.0.0.1:5000/new_chat" 
def new_chat():
    data = request.get_json()
    username = data["username"]

    response = USER_METADATA_TABLE.update_item(
        Key={'username': username},
        UpdateExpression="ADD chat_count :increment",
        ExpressionAttributeValues={':increment': 1},
        ReturnValues="UPDATED_NEW"
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
            ContentType="application/json"
        )
        print(f"Created placeholder file in S3: {key}")
    except ClientError as e:
        print(f"Failed to create placeholder file in S3: {e}")
        return jsonify({"status_code": 500, "message": "Failed to initialize new chat"}), 500
    return jsonify({"status_code": 200, "chat_id": new_chat_id})


@app.route('/user_creation', methods=["POST"])
# curl -X POST -H "Content-Type: application/json" \
#     -d '{"username":"John","password":30}' \
#     "http://127.0.0.1:5000/user_creation"
def user_creation():
    # Read the Dynamo DB
    data = request.get_json()
    response = check_dynamo_db_user_name (data["username"])

    if "Item" in response.keys():
        return jsonify({"status_code": 400, "message": "User profile already exists. Try logging in."})

     
    USER_METADATA_TABLE.put_item(
            Item={
                'username': data["username"],
                'password': data["password"],
                'chat_count': 0
                # Can add any other required metadata
            }
        )
    return jsonify({"status_code": 200, "message": "Account Creation was successful. Now try logging in."})
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
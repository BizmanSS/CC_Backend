# Backend For Chatbot Project

### Endpoints Covered

* User Authentication: 
   - Endpoint: '/user_authentication' - POST
   - Make calls to DynamoDB to ensure user name and password match up
* New User Creation:
     - '/user_creation' - POST
     - Adding an entry to DynamoDB for a new user, if that username is not taken
* List Chat History: 
    - '/get_chat_history' - POST 
    -  List all the past chat IDs and the chat history from each by reading the designated S3 bucket under the username's folder.
* Generate New Chat:
    - '/new_chat' -  POST
    - Generate a new chat id with a clean history. Updates the chat history file with an empty history.
* Generate Chatbot Response:
    - '/chatbot_response' - 'POST'
    - Call the SageMaker inference endpoint and retrieve the response using the user's prompt. This should be update the chat history using lambda (in order to avoid latency) 

### Creating a Docker Image:
- Run: docker build -t flask-backend-app . in the folder with this code to generate a docker image
- Local Testing: run the flask application using this command docker run -p 5000:5000 -it flask-backend-app
- Pushing to AWS: Run the following commands to add this image to ECR
    - docker tag flask-backend-app:latest <AWS_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<ECR_REPO_NAME>:latest
    - docker push <AWS_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<ECR_REPO_NAME>:latest

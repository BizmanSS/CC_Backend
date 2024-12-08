# Use the official Python image
FROM python:3.9

# Set the working directory
WORKDIR /app

# Copy the Flask app into the container
COPY backend.py .

# Install Flask
RUN pip install Flask
RUN pip install boto3
RUN pip install flask_cors

# Expose the port Flask runs on
EXPOSE 5000

# Command to run the app
CMD ["python", "backend.py"]

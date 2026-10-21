import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()az

endpoint = os.getenv("AZURE_AI_ENDPOINT")
deployment = os.getenv("AZURE_AI_DEPLOYMENT")

project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
client = project.get_openai_client()

response = client.chat.completions.create(
    model=deployment,
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
    max_tokens=30,
)
print(response.choices[0].message.content)
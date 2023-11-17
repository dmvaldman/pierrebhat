from openai import OpenAI
client = OpenAI()

files = client.files.list().data

for file in files:
    client.files.delete(file.id)
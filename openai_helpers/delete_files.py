from openai import OpenAI
client = OpenAI()

def delete_files():
    files = client.files.list().data

    for file in files:
        client.files.delete(file.id)

def delete_agents():
    assistants = client.beta.assistants.list(
        order="desc",
        limit="50",
    )

    for assistant in assistants.data:
        client.beta.assistants.delete(assistant.id)

delete_files()
delete_agents()
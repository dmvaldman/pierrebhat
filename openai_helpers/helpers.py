from openai.embeddings_utils import get_embedding, cosine_similarity
import openai
import numpy as np
import os
from utils.utils import retry
import json

from dotenv import load_dotenv
load_dotenv()

MAX_CONTENT_LENGTH = 4097
MAX_CONTENT_LENGTH_COMPLETE = 4097
MAX_CONTENT_LENGTH_COMPLETE_CODE = 8191
EMBED_DIMS = 1536
MODEL_EMBED = 'text-embedding-ada-002'
MODEL_COMPLETION = 'gpt-3.5-turbo-instruct'
MODEL_COMPLETION_CODE = 'gpt-3.5-turbo-instruct'
# MODEL_COMPLETION_CHAT = 'gpt-4'
MODEL_COMPLETION_CHAT = 'gpt-3.5-turbo'

openai.api_key = os.getenv("OPENAI_API_KEY")

# Helpers
def embed(text):
    if isinstance(text, list):
        for i, t in enumerate(text):
            text[i] = t.replace("\n", " ")
            if len(text[i]) > MAX_CONTENT_LENGTH:
                text[i] = text[i][0:MAX_CONTENT_LENGTH]
        embeddings = openai.Embedding.create(input=text, model=MODEL_EMBED)["data"]
        return np.array([np.array(embedding['embedding'], dtype=np.float32) for embedding in embeddings])
    else:
        text = text.replace("\n", " ")
        if len(text) > MAX_CONTENT_LENGTH:
            text = text[0:MAX_CONTENT_LENGTH]
        return np.array(openai.Embedding.create(input=[text], model=MODEL_EMBED)["data"][0]["embedding"], dtype=np.float32)

def compare_embeddings(embed1, embed2):
    return cosine_similarity(embed1, embed2)

def compare_text(text1, text2):
    return compare_embeddings(embed(text1), embed(text2))

@retry(times=3, exceptions=(Exception))
def complete(prompt, tokens_response=512):
    if len(prompt) > MAX_CONTENT_LENGTH_COMPLETE - tokens_response:
        nonsequitor = '\n...truncated\n'
        margin = int(len(nonsequitor))
        first_half = (MAX_CONTENT_LENGTH_COMPLETE - tokens_response - margin) // 2
        prompt = prompt[:first_half] + nonsequitor + prompt[-first_half:]

    try:
        results = openai.Completion.create(
            engine=MODEL_COMPLETION,
            prompt=prompt,
            max_tokens=tokens_response,
            temperature=0.1
        )
        return results['choices'][0]['text'].strip()
    except Exception as e:
        raise Exception(f"Couldn't get response from OpenAI API after 3 tries. Error:{e}")

@retry(times=3, exceptions=(Exception))
def complete_code(prompt, tokens_response=150):
    if len(prompt) > MAX_CONTENT_LENGTH_COMPLETE_CODE - tokens_response:
        nonsequitor = '\n...truncated\n'
        margin = int(len(nonsequitor) / 2)
        first_half = int((MAX_CONTENT_LENGTH_COMPLETE_CODE - tokens_response)/ 2)
        prompt = prompt[:first_half - margin] + nonsequitor + prompt[-first_half + margin:]

    # Try 3 times to get a response
    try:
        results = openai.Completion.create(
            engine=MODEL_COMPLETION_CODE,
            prompt=prompt,
            max_tokens=tokens_response,
            temperature=0.1
        )
        return results['choices'][0]['text'].strip()
    except Exception as e:
        raise Exception(f"Couldn't get response from OpenAI API after 3 tries. Error:{e}")

@retry(times=3, exceptions=(Exception))
def complete_agent_chat(messages, functions):
    try:
        results = openai.ChatCompletion.create(
            model=MODEL_COMPLETION_CHAT,
            messages=messages,
            functions=functions,
            function_call="auto",
            temperature=0.1
        )
        message = results['choices'][0]['message']
        if message['content']:
            return 'message', message['content']
        elif message['function_call']:
            arguments = json.loads(message['function_call']["arguments"])
            function_name = message['function_call']['name']
            return function_name, arguments
    except Exception as e:
        raise Exception(f"Couldn't get response from OpenAI API after 3 tries. Error:{e}")


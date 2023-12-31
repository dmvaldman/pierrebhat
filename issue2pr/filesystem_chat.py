from filesystem import Filesystem
from utils.llm_config import llm_config
from autogen import ConversableAgent

function_specs = [
    {
        "name": "list_files",
        "description": "Returns a prettified list of all files in the codebase",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_summaries",
        "description": "Returns high-level summaries (description, dependencies, classnames) for a given list of filenames",
        "parameters": {
            "type": "object",
            "properties": {
                "filenames": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "A filename"
                    },
                    "description": "An array of filenames to get summaries for"
                }
            }
        },
        "required": ["filenames"]
    },
    {
        "name": "get_content",
        "description": "Returns the content of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to read"
                }
            }
        },
        "required": ["filename"]
    },
    {
        "name": "get_filename_for_object",
        "description": "Returns an array of filenames for where a given class or class method, class attribute or dependency is defined. Class methods should be namespaced to their class name e.g., `class_name.function_name` but class attributes shouldn't be as instances are often renamed.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the class, method or function"
                }
            }
        },
        "required": ["name"]
    }
]

class Filesystem_Chat():
    system_message = """You are a senior software engineer with access to a filesystem to a codebase of a GitHub repository.
    This allows you to read summaries of files and their contents and perform various lookups.
    Reply with TERMINATE when the chat is complete.
    """
    max_consecutive_auto_reply = 50
    def __init__(self, filesystem):
        self.filesystem = filesystem

        self.function_map = {
            "get_summaries": self.filesystem.get_summaries,
            "get_content": self.filesystem.get_content,
            "get_filename_for_object": self.filesystem.get_filename_for_object,
            "list_files": self.filesystem.tree
        }

        # used for other chat bots
        self.function_specs = function_specs.copy()

        self.llm_config = llm_config.copy()
        self.llm_config['functions'] = self.function_specs

        self.chatbot = self.create_chatbot()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def create_chatbot(self):
        chatbot = ConversableAgent("filesystem",
            system_message = Filesystem_Chat.system_message,
            llm_config=self.llm_config,
            code_execution_config=False,
            is_termination_msg = Filesystem_Chat.is_terminal,
            max_consecutive_auto_reply=Filesystem_Chat.max_consecutive_auto_reply,
            human_input_mode="NEVER")

        return chatbot

    def initiate_chat(self, target, message='', **kwargs):
        self.chatbot.initiate_chat(target, message=message, **kwargs)


if __name__ == "__main__":
    owner = "roboflow"
    name = "supervision"

    filesystem = Filesystem(name, create_meta=True)
    filesystem_chat = Filesystem_Chat(filesystem)
    reply = filesystem_chat.chatbot.receive("List all the files in the directory.", filesystem_chat.chatbot, True, silent=False)
    print(reply)
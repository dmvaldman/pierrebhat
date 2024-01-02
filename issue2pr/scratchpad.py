from autogen import ConversableAgent
from utils.llm_config import llm_config

class Scratchpad():
    def __init__(self):
        self.notes = []
        self.plan = None

    def take_note(self, note):
        self.notes.append(note)
        return 'Success.'

    def save_plan(self, plan):
        self.plan = plan
        return 'Success.'

    def read_plan(self):
        return self.plan

    def read_notes(self):
        notes_str = '\n'.join(self.notes)
        return notes_str

function_specs = [
    {
        "name": "save_plan",
        "description": "Save a step-by-step plan of relevant code changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "A step-by-step plan of relevant code changes."
                }
            }
        },
        "required": ["plan"]
    },
    {
        "name": "take_note",
        "description": "Record a note containing relevant information for the plan.",
        "parameters": {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "A note."
                }
            }
        },
        "required": ["note"]
    }
]

class Scratchpad_Chat():
    system_message = """You are a scratchpad for longer-term planning and brainstorming.
    Your plan includes a step-by-step plan of relevant code changes.
    You do not include any steps related to testing, documentation, git actions, or other non-code changes.
    """
    max_consecutive_auto_reply = 50
    def __init__(self):
        self.scratchpad = Scratchpad()

        self.function_map = {
            "save_plan": self.scratchpad.save_plan,
            "take_note": self.scratchpad.take_note
        }

        self.llm_config = llm_config.copy()
        self.function_specs = function_specs.copy()

        self.chatbot = self.create_chatbot()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def update_function_signature(self, func_sig, is_remove=None):
        self.chatbot.update_function_signature(func_sig, is_remove=is_remove)

    def register_function(self, function_map):
        self.chatbot.register_function(function_map)

    def create_chatbot(self):
        self.llm_config['functions'] = self.function_specs

        return ConversableAgent("Code_Planning_Scratchpad",
            system_message = Scratchpad_Chat.system_message,
            llm_config=self.llm_config,
            code_execution_config=False,
            is_termination_msg = Scratchpad_Chat.is_terminal,
            max_consecutive_auto_reply=Scratchpad_Chat.max_consecutive_auto_reply,
            human_input_mode="NEVER"
        )


from autogen import ConversableAgent
from utils.llm_config import llm_config

class PlanScratchpad():
    def __init__(self):
        self.notes = []
        self.plan = None

    def take_note(self, note):
        self.notes.append(note)

    def create_plan(self, plan):
        self.plan = plan

    def read_plan(self):
        return self.plan

    def read_notes(self):
        notes_str = '\n'.join(self.notes)
        return notes_str


planDef = [
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

scratchpad = PlanScratchpad()

max_consecutive_auto_reply = 50

llm_config_planner = llm_config.copy()
llm_config_planner['functions'] = planDef

def is_terminal(message):
    if message['content'] is None:
        return False
    return 'TERMINATE' in message['content']

system_message = """You are a scratchpad for longer-term planning and brainstorming."""

scratchpad_agent = ConversableAgent("Code_Planning_Scratchpad",
    system_message = system_message,
    llm_config=llm_config_planner,
    code_execution_config=False,
    is_termination_msg = is_terminal,
    max_consecutive_auto_reply=max_consecutive_auto_reply,
    human_input_mode="NEVER"
)


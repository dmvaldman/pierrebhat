import concurrent.futures
from autogen import ConversableAgent, GroupChat, GroupChatManager
from filesystem_chat import Filesystem, Filesystem_Chat
from scratchpad import Scratchpad_Chat
from openai_helpers.helpers import MAX_CONTENT_LENGTH
from utils.llm_config import llm_config
from issue import Issue

max_consecutive_auto_reply = 50

on_find_mod_files_def = {
    "name": "submit_files_modify",
    "description": "Submits a list of files to be modified by the PR",
    "parameters": {
        "type": "object",
        "properties": {
            "filenames": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "A filename"
                },
                "description": "An array of filenames to modify"
            }
        }
    }
}

on_find_add_files_def = {
    "name": "submit_files_add",
    "description": "Submits a list of files to be added by a PR",
    "parameters": {
        "type": "object",
        "properties": {
            "filenames": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "A filename"
                },
                "description": "An array of filenames to add"
            }
        }
    }
}

on_find_rem_files_def = {
    "name": "submit_files_remove",
    "description": "Submits a list of files to be removed by a PR",
    "parameters": {
        "type": "object",
        "properties": {
            "filenames": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "A filename"
                },
                "description": "An array of filenames to remove"
            }
        }
    }
}

class ChatFindFiles():
    system_message_user = """You are a senior software engineer working on a GitHub repository. You have been assigned an issue to resolve.
    Your task is to locate the files needed to modify/add/remove to resolve the issue, which you can do by conversing with the filesystem API.
    You must call each of `submit_files_add`, `submit_files_modify`, and `submit_files_remove` with a list of filenames to add, modify, and remove, respectively.
    If no files should be added, modified, or removed, submit an empty list to the respective method.
    Respond with the single word `TERMINATE` to end the chat but only after calling each of these methods, do not write TERMINATE for any other reason.
    """
    system_message_user_plan = """You are a senior software engineer working on a GitHub repository. You have been assigned an issue to resolve.
    Your task is to locate the files needed to modify/add/remove to resolve the issue, which you can do by conversing with the filesystem API.
    Save any notes whenever you find relevant information for resolving the issue.
    You must call each of `submit_files_add`, `submit_files_modify`, and `submit_files_remove` with a list of filenames to add, modify, and remove, respectively.
    If no files should be added, modified, or removed, submit an empty list to the respective method.
    Afterwards, write out and save a detailed step-by-step plan (in markdown format) of what code changes need to be made to resolve the issue. This plan will be used by another engineer to implement the PR.
    The plan should include relevant information such as code snippets, psuedocode and references to filenames where appropriate.
    The plan should NOT include steps to test/document code, the process of creating a PR, aligning stakeholders, or anything else outside the code modifacaitions themselves.
    Respond with the single word `TERMINATE` to end the chat but only after calling each of these methods, do not write TERMINATE for any other reason.
    """
    def __init__(self, filesystem, issue, use_plan=False):
        self.fs = filesystem
        self.issue = issue
        self.use_plan = use_plan

        self.filenames_mod = concurrent.futures.Future()
        self.filenames_add = concurrent.futures.Future()
        self.filenames_rem = concurrent.futures.Future()

        self.filenames = {
            "modify": self.filenames_mod,
            "add": self.filenames_add,
            "remove": self.filenames_rem
        }

        self.filesystem_chat = Filesystem_Chat(self.fs)
        if use_plan: self.scratchpad_chat = Scratchpad_Chat()

        # loop through all functions in filesystem_bot and add them to user_bot
        self.function_map = {}
        self.function_specs = []
        self.function_map.update(self.filesystem_chat.function_map)

        if use_plan:
            self.function_map.update(self.scratchpad_chat.function_map)

        self.llm_config_filesystem = self.filesystem_chat.llm_config.copy()
        self.llm_config_user = llm_config.copy()
        if use_plan: self.llm_config_scratchpad = self.scratchpad_chat.llm_config.copy()

        self.create_callbacks()
        self.create_chatbots()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        return 'TERMINATE' in message['content']

    def on_find_mod_files(self, filenames):
        if not self.filenames_mod.done():
            self.filenames_mod.set_result(filenames)
        else:
            if filenames == self.filenames_mod.result():
                raise Exception(f'Modified files already set to {filenames}. Ignoring.')
            else:
                # take superset of filenames
                filenames_superset = set(filenames).union(set(self.filenames_mod.result()))
                self.filenames_mod = concurrent.futures.Future()
                self.filenames_mod.set_result(list(filenames_superset))
        return 'Success'

    def on_find_add_files(self, filenames):
        self.filenames_add.set_result(filenames)
        return 'Success'

    def on_find_rem_files(self, filenames):
        self.filenames_rem.set_result(filenames)
        return 'Success'

    def on_take_note(self, plan):
        self.scratchpad.take_note(plan)
        return 'All Notes:\n\n' + self.scratchpad.read_notes()

    def on_create_plan(self, plan):
        self.scratchpad.create_plan(plan)
        return 'Success'

    def create_callbacks(self):
        self.add_callback(self.on_find_mod_files, on_find_mod_files_def)
        self.add_callback(self.on_find_add_files, on_find_add_files_def)
        self.add_callback(self.on_find_rem_files, on_find_rem_files_def)

    def add_callback(self, method, method_def):
        method_name = method_def['name']
        self.function_map[method_name] = method
        self.function_specs.append(method_def)

    def generate_user_prompt(self, issue, fs):
        # TODO: better truncation
        prompt = f"{str(issue)}\nHere is the directory structure:\n\n{fs.tree()}\nNavigate/read the codebase using the filesystem API to determine a list of files that need to be added, removed, or modified to fix this issue."
        if len(prompt) > MAX_CONTENT_LENGTH:
            prompt = prompt[:MAX_CONTENT_LENGTH] + '...'
        return prompt

    def create_chatbots(self):
        self.llm_config_user['functions'] = self.function_specs

        if self.use_plan:
            system_message_user = ChatFindFiles.system_message_user_plan
        else:
            system_message_user = ChatFindFiles.system_message_user

        self.user_bot = ConversableAgent("user_find_files",
            system_message = system_message_user,
            llm_config=self.llm_config_user,
            is_termination_msg = ChatFindFiles.is_terminal,
            function_map = self.function_map,
            code_execution_config=False,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode="NEVER")

        if self.use_plan:
            agents = [
                self.user_bot,
                self.filesystem_chat.chatbot,
                self.scratchpad_chat.chatbot
            ]

            group_chat = GroupChat(
                agents=agents,
                messages=[],
                max_round=20,
                speaker_selection_method="auto"
            )

            self.manager = GroupChatManager(
                name="chat_manager",
                groupchat=group_chat,
                human_input_mode="NEVER",
                system_message="Group chat manager."
            )

    def initiate_chat(self, **kwargs):
        prompt = self.generate_user_prompt(self.issue, self.fs)
        if self.use_plan:
            self.user_bot.initiate_chat(self.manager, message=prompt, **kwargs)
        else:
            # self.filesystem_chat.initiate_chat(self.user_bot, message=prompt, **kwargs)
            self.user_bot.initiate_chat(self.filesystem_chat.chatbot, message=prompt, **kwargs)


if __name__ == "__main__":
    use_plan = False
    owner = "roboflow"
    name = "supervision"
    repo_name = f"{owner}/{name}"

    fs = Filesystem(name, create_meta=True)

    issue_num = 464
    issue_title = "Make `sv.LineZone.trigger` return bool `np.ndarray` informing which detections have crossed the line this frame"
    issue_body = """Currently, [`sv.LineZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/line_counter.py#L30) updates `in_count` and `out_count` values but does not return information on which object crossed the line. Unlike [`sv.PolygonZone.trigger`](https://github.com/roboflow/supervision/blob/5b5e0eb88daec92643834b2284e750ad5a1c7dc6/supervision/detection/tools/polygon_zone.py#L45), which returns such information.

    Information about who has crossed the line is needed to update `in_count` and `out_count` and is already calculated in the `trigger` method but does not surface. Let's change that.
    """

    issue = Issue(issue_title, issue_body, repo_name, num=issue_num)

    chat = ChatFindFiles(fs, issue, use_plan=use_plan)

    if use_plan:
        chat.initiate_chat(silent=False)
        print(chat.scratchpad_chat.scratchpad.read_plan())
    else:
        chat.initiate_chat(silent=False)

from autogen import ConversableAgent

# model = "gpt-4-0613"
model = "gpt-4-1106-preview"
llm_config={
    "request_timeout": 600,
    "seed": 42,
    "model": model,  # make sure the endpoint you use supports the model
    "temperature": 0
}

class ChatCompareCode():
    user_system_message = """You are a programmer collaborating on a GitHub issue.
    Your task is to decide whether two solutions to the issue are essentially equivalent.
    If the solutions are roughly equivalent respond YES, otherwise respond NO. To end the conversation, write TERMINATE.
    """
    comparitor_system_message = """You are a proficient programmer.
    Your task is to decide whether two solutions to the issue are essentially equivalent.
    First gather relavant information and explain your reasoning. To end the conversation, write TERMINATE.
    """
    def __init__(self, issue, new_files, actual_files):
        self.issue = issue

        self.actual_files = actual_files
        self.new_files = new_files

        self.create_chatbots()

    @staticmethod
    def is_terminal(message):
        if message['content'] is None:
            return False
        content = message['content']
        return 'TERMINATE' in content or 'YES' in content or 'NO' in content

    def generate_user_prompt(self, issue, new_files, actual_files):
        new_str = '\n\n'.join([f'Filename: {filename}\n\n{contents}' for filename, contents in new_files.items()])
        actual_str = '\n\n'.join([f'Filename: {filename}\n\n{contents}' for filename, contents in actual_files.items()])
        prompt = f"""Here are two solutions written by two different people to fix this issue: {issue}.
        The solutions may differ on the surface, but we are only here to judge whether they resolve the issue, any other differences are irrelevant.
        \n\nSolution 1:\n{new_str}\n\nSolution 2:\n{actual_str}\n\n Do you think they are roughly equivalent with respect to resolving the issue?
        """
        return prompt

    def create_chatbots(self):
        self.compare_bot = ConversableAgent("comparitor",
            system_message = ChatCompareCode.comparitor_system_message,
            llm_config=llm_config,
            code_execution_config=False,
            is_termination_msg = ChatCompareCode.is_terminal,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER"
        )

        self.user_bot = ConversableAgent("user",
            system_message = ChatCompareCode.user_system_message,
            is_termination_msg = ChatCompareCode.is_terminal,
            code_execution_config=False,
            max_consecutive_auto_reply=10,
            human_input_mode="NEVER")

    def initiate_chat(self, **kwargs):
        user_prompt = self.generate_user_prompt(self.issue, self.new_files, self.actual_files)
        self.user_bot.initiate_chat(self.compare_bot, message=user_prompt, **kwargs)

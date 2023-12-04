import json
import time
import autogen
from contextlib import redirect_stdout
import sys
from repo import Repo
from filesystem import Filesystem
from chat_find_files import Issue, ChatFindFiles, onFindFilesDef
from chat_write_code import ChatWriteCode, onCheckCodeDef
from gpt_write_code import GPTWriteCode
from chat_compare_code import ChatCompareCode

def config_to_str(config):
    config_str = ''
    for key, val in config.items():
        config_str += f'{key}_{val}_'
    return config_str

def print_logs():
    logs = autogen.ChatCompletion.logged_history

    config_str = config_to_str(config)

    # write to json
    filename = f'logs/{config_str}.json'
    with open(filename, 'w') as f:
        json.dump(logs, f, indent=2)

def onAssessPR(issue, answer, patches, results):
    #find nad label PR in dataset
    for result in results:
        if result['repo_name'] == issue.repo_name and result['issue_num'] == issue.num:
            result['correct_patches'] = patches
            result['correct_pr'] = (answer == 'YES')
            break

    # save results to file
    with open('data/test_results.json', 'w') as f:
        json.dump(results, f, indent=2)

def main(issue_dataset=None):
    results = []
    response = {
        "attempts": 0,
        "correct": 0,
        "config": config,
        "results": results
    }

    for repo_name, issues in issues_dataset.items():
        if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
            continue

        repo = Repo(repo_name)
        repo.download()
        fs = Filesystem(repo.name, create_meta=True)
        # snippet_type = 'diff' #['all', 'diff', 'snippet']
        snippet_type = config['snippet_type']

        for issue in issues:
            sha = issue['pr']['base_sha']
            repo.checkout(sha)

            issue_title = issue['title']
            issue_body = issue['body']
            issue_pr = issue['pr']
            issue_num = issue['num']

            issue = Issue(issue_title, issue_body, repo_name, num=issue_num, pr=issue_pr)

            chat_find_files = ChatFindFiles(fs, issue)
            chat_find_files.initiate_chat(silent=False)

            if not chat_find_files.filenames.done():
                print('ERROR: ChatFindFiles did not finish. Increase max_consecutive_auto_reply in chat')
                continue

            filenames = chat_find_files.filenames.result()

            if config['write_code'] == 'agent':
                chat_write_code = GPTWriteCode(issue, filenames, fs, snippet_type=snippet_type)
            elif config['write_code'] == 'autogen':
                chat_write_code = ChatWriteCode(issue, filenames, fs, snippet_type=snippet_type)

            chat_write_code.initiate_chat(silent=False)

            if not chat_write_code.new_files.done() or not chat_write_code.patches.done():
                print('ERROR: ChatWriteCode did not finish. Increase max_consecutive_auto_reply in chat')
                continue

            new_files = chat_write_code.new_files.result()
            patches = chat_write_code.patches.result()
            actual_files = issue.get_changed_file_contents()

            chat_compare_code = ChatCompareCode(issue, new_files, actual_files)
            chat_compare_code.initiate_chat(silent=False)
            answer = chat_compare_code.user_bot.last_message()['content']

            # save results to file
            if not chat_find_files.result.done():
                print('ERROR: ChatFindFiles did not finish. Increase max_consecutive_auto_reply in chat')
                continue

            response['attempts'] += 1
            result = chat_find_files.result.result().copy()
            result['correct_patches'] = patches

            if answer == 'YES':
                result['correct_pr'] = True
                result['correct_pr_reason'] = ''
                response['correct'] += 1
            else:
                result['correct_pr'] = False
                result['correct_pr_reason'] = chat_compare_code.user_bot.last_message()['content']

            results.append(result)

            # save results to file
            config_str = config_to_str(config)
            with open(f'data/{config_str}.json', 'w') as f:
                response['results'] = results
                json.dump(response, f, indent=2)

    return results

if __name__ == "__main__":
    config = {
        "ts": time.strftime("%Y%m%d-%H%M"),
        "snippet_type": "snippet",
        "write_code": "agent"
    }

    with open('data/datasets/repo_issues.json') as json_file:
        issues_dataset = json.load(json_file)

    output_file = 'logs/' + config_to_str(config) + '.txt'
    print("Outputting to", output_file)

    with open(output_file, 'w') as file:
        with redirect_stdout(file):
            results = main(issues_dataset)

import json
from repo import Repo
from filesystem import Filesystem
from chat_find_files import Issue, ChatFindFiles, onFindFilesDef
from chat_write_code import ChatWriteCode, onWriteCodeDef
from chat_compare_code import ChatCompareCode

with open('data/datasets/repo_issues.json') as json_file:
    issues_dataset = json.load(json_file)

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

for repo_name, issues in issues_dataset.items():
    if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
        continue

    repo = Repo(repo_name)
    repo.download()
    fs = Filesystem(repo.name, create_meta=True)

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
        filenames = chat_find_files.filenames.result()

        chat_write_code = ChatWriteCode(issue, filenames, fs)
        chat_write_code.initiate_chat(silent=False)

        new_files = chat_write_code.new_files.result()
        patches = chat_write_code.patches.result()
        actual_files = issue.get_changed_file_contents()

        chat_compare_code = ChatCompareCode(issue, new_files, actual_files)
        chat_compare_code.initiate_chat(silent=False)
        answer = chat_compare_code.user_bot.last_message()['content']

        onAssessPR(issue, answer, patches, chat_find_files.results)
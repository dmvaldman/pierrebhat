import json
from repo import Repo
from filesystem import Filesystem
from chat_find_files import Issue, ChatFindFiles
from chat_write_code import ChatWriteCode

with open('data/datasets/repo_issues.json') as json_file:
    issues_dataset = json.load(json_file)

results = []

def callback(issue, filesystem):
    changed_files = issue.changed_files
    actual_filenames = [file['filename'] for file in changed_files if file['status'] == 'modified']

    # filter actual_filenames to remove any tests
    actual_filenames = [filename for filename in actual_filenames if 'test' not in filename]

    def onSubmit(filenames):
        # strip repo name from filenames
        repo_name = issue.repo_name.split('/')[1]
        filenames = [filename.replace(repo_name + '/', '', 1) for filename in filenames]

        test_result = set(actual_filenames) <= set(filenames)
        print(f"Actual changed files: {actual_filenames}")
        print(f"Proposed changed files: {filenames}")
        print(f"Correct: {test_result}")

        result = {
            'repo_name': issue.repo_name,
            'issue_num': issue.num,
            'actual_filenames': actual_filenames,
            'proposed_filenames': filenames,
            'correct': test_result
        }
        filenames = [repo_name + '/' + filename for filename in filenames]
        chat_write_code = ChatWriteCode(issue, filenames, filesystem, submit_pr)
        chat_write_code.initiate_chat(silent=False)

        results.append(result)
        return test_result

    return onSubmit

def submit_pr(patches, tests=None):
    print(patches, tests)

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

        onSubmit = callback(issue, fs)

        chat_find_files = ChatFindFiles(fs, issue, onSubmit)
        chat_find_files.initiate_chat(silent=True)

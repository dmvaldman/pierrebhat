import json
from repo import Repo
from filesystem import Filesystem
from chat_find_files import Issue, ChatFindFiles
from chat_write_code import ChatWriteCode
from chat_compare_code import ChatCompareCode
import requests

with open('data/datasets/repo_issues.json') as json_file:
    issues_dataset = json.load(json_file)

file_change_test_results = []

def get_changed_files_form_issue(issue):
    changed_files = issue.changed_files
    actual_filenames = [file['filename'] for file in changed_files if file['status'] == 'modified']

    #filter filenames to match extensions in Filesystem.extensions
    actual_filenames = [filename for filename in actual_filenames if filename.endswith(Filesystem.extensions)]

    # filter filenames to remove any directories in Filesystem.directory_blacklist
    actual_filenames = [filename for filename in actual_filenames if not any(directory in filename for directory in Filesystem.directory_blacklist)]

    return actual_filenames

def create_onSubmit(issue, filesystem):
    actual_filenames = get_changed_files_form_issue(issue)

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
            'correct_files': test_result
        }
        file_change_test_results.append(result)

        check_pr = create_check_pr(issue)

        filenames = [repo_name + '/' + filename for filename in filenames]
        chat_write_code = ChatWriteCode(issue, filenames, filesystem, check_pr)
        chat_write_code.initiate_chat(silent=False)

    return onSubmit

def create_check_pr(issue):
    # get actual files to compare against PR
    actual_files = get_actual_files(issue)

    def check_pr(patches, tests=None):
        new_files = apply_patches(patches)
        chat_compare_code = ChatCompareCode(issue, new_files, actual_files)
        chat_compare_code.initiate_chat(silent=False)
        answer = chat_compare_code.user_bot.last_message()['content']

        #find nad label PR in dataset
        for result in file_change_test_results:
            if result['repo_name'] == issue.repo_name and result['issue_num'] == issue.num:
                result['correct_patches'] = patches
                result['correct'] = answer == 'YES'
                break

        # save results to file
        with open('data/test_results.json', 'w') as f:
            json.dump(file_change_test_results, f, indent=2)

    return check_pr

def get_actual_files(issue):
    actual_files = {}
    changed_filenames = get_changed_files_form_issue(issue)
    repo_name = issue.repo_name
    sha = issue.pr['merge_commit_sha']
    for filename in changed_filenames:
        url = f'https://raw.githubusercontent.com/{repo_name}/{sha}/{filename}'
        response = requests.get(url)
        if response.status_code == 200:
            actual_files[filename] = response.text
        else:
            raise Exception("Error getting file from GitHub")
    return actual_files

def apply_patches(patches):
    original_files = {}
    # get unique 'filename' keys in patches
    filenames = set([patch['filename'] for patch in patches])
    for filename in filenames:
        try:
            with open('repos/' + filename, 'r') as f:
                file_content = f.read()
                original_files[filename] = file_content
        except Exception as e:
            print(f"Could not find file repo/{filename}: {e}")

    for patch in patches:
        content = original_files[patch['filename']]
        new_content = apply_patch_to_file(content, patch['searchString'], patch['replaceString'])
        original_files[patch['filename']] = new_content

    return original_files

def apply_patch_to_file(file_content, searchString, replaceString):
    if searchString in file_content:
        file_content = file_content.replace(searchString, replaceString)
    else:
        raise Exception("Patch not applicable to file")
    return file_content

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

        onSubmit = create_onSubmit(issue, fs)

        chat_find_files = ChatFindFiles(fs, issue, onSubmit)
        chat_find_files.initiate_chat(silent=False)

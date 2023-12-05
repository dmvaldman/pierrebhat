import json
import time
from contextlib import redirect_stdout
from chat_compare_code import ChatCompareCode
from Issue2PR import Issue2PR, Issue

def config_to_str(config):
    config_str = ''
    for key, val in config.items():
        config_str += f'{key}_{val}_'
    return config_str

def main(issues_dataset=None, config=None, save=True):
    patches_all = {}
    new_files_all = {}
    issue2PR = Issue2PR(options=config)

    for repo_name, issues in issues_dataset.items():
        if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
            continue

        repo = Issue2PR.create_repo(repo_name)
        issue2PR.set_repo(repo)

        for issue in issues:
            sha = issue['pr']['base_sha']
            repo.checkout(sha)

            issue = Issue2PR.create_issue(issue['title'], issue['body'], repo_name)
            issue2PR.set_issue(issue)

            new_files, patches = issue2PR.resolve()
            patches_all[issue.id] = patches
            new_files_all[issue.id] = new_files

            # save results to file
            if save:
                config_str = config_to_str(config)
                with open(f'data/patches_{config_str}.json', 'w') as f:
                    json.dump(patches_all, f, indent=2)
                with open(f'data/files_{config_str}.json', 'w') as f:
                    json.dump(new_files_all, f, indent=2)

    return new_files_all

def test(issues_dataset, config):
    results = []

    response = {
        "attempts": 0,
        "correct": 0,
        "config": config
    }

    # load patches
    config_str = config_to_str(config)
    with open(f'data/files_{config_str}.json') as f:
        new_files_all = json.load(f)

    with open(f'data/patches_{config_str}.json') as f:
        patches_all = json.load(f)

    for repo_name, issues in issues_dataset.items():
        if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
            continue

        issue = Issue(issue['title'], issue['body'], repo_name, num=issue['num'], pr=issue['pr'])
        proposed_files = new_files_all[issue.id]
        proposed_patches = patches_all[issue.id]
        actual_files = issue.get_changed_file_contents()

        proposed_filenames = list(proposed_files.keys())
        actual_filenames = list(actual_files.keys())

        chat_compare_code = ChatCompareCode(issue, proposed_files, actual_files)
        chat_compare_code.initiate_chat(silent=False)

        is_solution_correct = chat_compare_code.result.result()
        reason = chat_compare_code.reason.result()

        result = {
            "repo_name": repo_name,
            "issue_num": issue.num,
            "actual_filenames": list(actual_files.keys()),
            "proposed_filenames": list(proposed_files.keys()),
            "correct_filenames": set(actual_filenames) <= set(proposed_filenames),
            "correct_patches": proposed_patches,
            "correct_pr": is_solution_correct,
            "correct_pr_reason": reason
        }

        results.append(result)

        response['attempts'] += 1
        if is_solution_correct:
            response['correct'] += 1

        response['results'] = results

        # save results to file
        with open(f'data/test_{config_str}.json', 'w') as f:
            response['results'] = results
            json.dump(response, f, indent=2)

if __name__ == "__main__":
    import os

    config = {
        "ts": time.strftime("%Y%m%d-%H%M"),
        "snippet_type": "snippet",
        "write_code": "agent"
    }

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(curr_dir, 'logs', config_to_str(config) + '.txt')

    with open(os.path.join('data', 'datasets', 'repo_issues.json')) as json_file:
        issues_dataset = json.load(json_file)

    print("Outputting to", output_path)

    with open(output_path, 'w') as file:
        with redirect_stdout(file):
            results = main(issues_dataset, config)
